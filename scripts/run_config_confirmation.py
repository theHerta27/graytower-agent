"""Run one newly authorized frozen Config confirmation batch, once only.

No credential loader: live ModelGateway uses the externally supplied environment.
--live and the reviewed exact scope hash are required. Preparation is separate.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import time

from prepare_config_confirmation import (DATA, MODEL_KWARGS, ROOT, ConfigAgent,
    CandidateRepository, ModelGateway, TRUSTED_GAME_ROOT, canonical,
    public_cases, save, sha, source_hashes, source_snapshot)


class CaseModel:
    def __init__(self, model, first_payload, max_calls=2):
        self.model, self.first_payload, self.max_calls = model, first_payload, max_calls
        self.attempts = 0

    def complete(self, messages, schema):
        if self.attempts >= self.max_calls:
            raise RuntimeError('per-case model call limit exhausted')
        preview = self.model.preview(messages, schema)
        if self.attempts == 0 and canonical(preview['payload']) != canonical(self.first_payload):
            raise RuntimeError('initial wire payload changed from frozen preview')
        self.attempts += 1
        return self.model.complete(messages, schema)


def ledger(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def append_event(path, value):
    with path.open('a', encoding='utf-8', newline='\n') as stream:
        stream.write(canonical(value) + '\n')
        stream.flush()
        os.fsync(stream.fileno())


def no_battles_or_confirmations(root):
    database = root / 'jobs.sqlite'
    if not database.exists():
        return True
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as db:
        return all(db.execute(f'SELECT COUNT(*) FROM {name}').fetchone()[0] == 0
                   for name in ('confirmations', 'requests', 'jobs'))


def run_batch(data, scope_sha256, *, model_factory=None, source='live'):
    data = Path(data).resolve()
    if (data / 'batch-started.json').exists():
        raise RuntimeError('batch already started; preserve first results and reconcile, never rerun')
    if source not in ('live', 'fixture') or ((model_factory is not None) != (source == 'fixture')):
        raise ValueError('fixture source requires an injected model; live source forbids injection')
    scope_path = data / 'outbound-scope.json'
    if sha(scope_path) != scope_sha256:
        raise RuntimeError('reviewed scope hash mismatch')
    scope = json.loads(scope_path.read_text(encoding='utf-8'))
    cases = public_cases()
    if (scope['case_ids'] != [case['id'] for case in cases]
            or scope['max_calls_total_including_failed_unknown'] != 24
            or scope['max_calls_per_case'] != 2 or scope['output_method'] != 'json_mode'):
        raise RuntimeError('frozen batch limits or case order mismatch')
    if scope['source_hashes'] != source_hashes():
        raise RuntimeError('execution source seal mismatch; prepare a newly reviewed scope')
    for name, expected in scope['sealed_files'].items():
        if sha(data / name) != expected:
            raise RuntimeError('preparation seal mismatch: ' + name)
    baseline = source_snapshot(TRUSTED_GAME_ROOT)
    saved_sources = json.loads((data / 'source-hashes.json').read_text(encoding='utf-8'))
    if baseline != saved_sources['game_snapshot']:
        raise RuntimeError('trusted game snapshot changed since preparation')
    if any((data / name).exists() for name in ('model-calls.jsonl', 'observations.json', 'batch-events.jsonl')):
        raise RuntimeError('unexpected existing execution evidence; no ledger reuse')
    for case in cases:
        case_root = data / 'cases' / case['id']
        if any((case_root / 'artifacts').glob('*.json')) or not no_battles_or_confirmations(case_root):
            raise RuntimeError('case data contains execution evidence before batch start')
    previews = json.loads((data / 'outbound-previews.json').read_text(encoding='utf-8'))
    if [item['case_id'] for item in previews] != scope['case_ids']:
        raise RuntimeError('preview order mismatch')
    # Exclusive create plus fsync before constructing the live gateway. Any
    # interruption permanently closes this first-run entry, including unknowns.
    try:
        save(data / 'batch-started.json', {'scope_sha256': scope_sha256, 'source': source,
             'created_at': datetime.now(timezone.utc).isoformat(), 'case_ids': scope['case_ids']})
    except FileExistsError:
        raise RuntimeError('batch already started; refusing concurrent or repeated execution') from None
    started = time.monotonic()
    observations, fatal = {}, None
    model = (model_factory or ModelGateway)(**MODEL_KWARGS,
        max_input_chars=scope['max_input_chars_per_call'], audit_path=data / 'model-calls.jsonl')
    for case, preview in zip(cases, previews, strict=True):
        case_root, tick = data / 'cases' / case['id'], time.monotonic()
        try:
            remaining_before = model.remaining_calls()
        except Exception as exc:
            fatal = {'error_type': type(exc).__name__, 'stage': 'ledger_read', 'before_case': case['id']}
            break
        append_event(data / 'batch-events.jsonl', {'event': 'case_started', 'case_id': case['id'],
                                                  'remaining_calls': remaining_before})
        wrapper = CaseModel(model, preview['preview']['payload'])
        try:
            output = ConfigAgent(CandidateRepository(case_root), wrapper, max_repairs=1).draft(case['prompt'])
        except Exception as exc:
            output = {'status': 'rejected', 'message': '执行失败；保留现场，不补跑。',
                      'error_type': type(exc).__name__}
        try:
            remaining_after = model.remaining_calls()
            new_calls = remaining_before - remaining_after
            unchanged = source_snapshot(TRUSTED_GAME_ROOT) == baseline
            no_side_effect = no_battles_or_confirmations(case_root)
        except Exception as exc:
            new_calls, unchanged, no_side_effect = None, False, False
            fatal = {'error_type': type(exc).__name__, 'stage': 'post_case_audit', 'case_id': case['id']}
        observation = {'output': output, 'audit': {
            'source': source, 'completed': not bool(output.get('error_type')) and fatal is None,
            'baseline_unchanged': unchanged, 'battle_count': 0 if no_side_effect else None,
            'candidate_created': output.get('candidate') is not None,
            'model_reserved_calls': new_calls, 'model_decision_attempts': wrapper.attempts,
            'elapsed_seconds': time.monotonic() - tick}}
        save(case_root / 'observation.json', observation)
        observations[case['id']] = observation
        append_event(data / 'batch-events.jsonl', {'event': 'case_finished', 'case_id': case['id'],
            'observation_sha256': sha(case_root / 'observation.json'), 'reserved_calls': new_calls})
        if fatal or not unchanged or not no_side_effect or new_calls is None or not 0 <= new_calls <= 2:
            fatal = fatal or {'stage': 'case_boundary_failed', 'case_id': case['id']}
            break
    save(data / 'observations.json', observations)
    records = ledger(data / 'model-calls.jsonl')
    reservations = [item for item in records if item['status'] == 'reserved']
    terminals = {item['call_id']: item for item in records if item['status'] in ('completed', 'failed')}
    summary = {'source': source, 'fixed_denominator': 12, 'recorded_cases': list(observations),
               'not_run': [case['id'] for case in cases if case['id'] not in observations],
               'reserved_calls': len(reservations),
               'completed_calls': sum(item['status'] == 'completed' for item in terminals.values()),
               'failed_calls': sum(item['status'] == 'failed' for item in terminals.values()),
               'unknown_calls': sum(item['call_id'] not in terminals for item in reservations),
               'elapsed_seconds': time.monotonic() - started, 'fatal': fatal,
               'scope_sha256': scope_sha256, 'scoring_status': 'PENDING_INDEPENDENT_REVIEW',
               'new_battles': 0 if fatal is None else None,
               'limit': 'No self-grade. Preserve all first and repaired outputs; use frozen score_case and separate independent reviews. No candidate confirmation or QA follows this batch.'}
    save(data / 'run-summary.json', summary)
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=DATA)
    parser.add_argument('--live', action='store_true', help='Use only after explicit new authorization of this exact scope')
    parser.add_argument('--scope-sha256', required=True, help='SHA256 of the reviewed outbound-scope.json')
    args = parser.parse_args()
    if not args.live:
        parser.error('this runner requires --live after authorization; use prepare_config_confirmation.py for zero-call preparation')
    print(json.dumps(run_batch(args.data, args.scope_sha256), ensure_ascii=False, indent=2))
