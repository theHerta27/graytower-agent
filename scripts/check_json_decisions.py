"""Replay two previously anomalous QA inputs twice, without executing decisions.

Default: offline preparation. --live requires new exact-scope authorization.
This is a known-input protocol regression, not new QA quality or battle evidence.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]
from agent_workbench.models import ModelGateway
from agent_workbench.qa import Decision

DATA = ROOT / 'local-data/json-decision-regression-v2'
HISTORY = ROOT / 'local-data/qa-independent-v1-32k/model-calls.jsonl'
HISTORY_HASH = '975fdc3c277ad558ea480b7e09b17b52bfc3f82adff166d5aaf6da13dbac355c'
INPUT_LIMIT = 16000
OUTPUT_LIMIT = 2048


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save(path, data):
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def gateway(data):
    return ModelGateway(model='deepseek-flash', output_method='json_mode', max_calls=4,
                        max_input_chars=INPUT_LIMIT, max_output_tokens=OUTPUT_LIMIT,
                        audit_path=data / 'model-calls.jsonl')


def prepare(data=DATA):
    if data.exists():
        raise RuntimeError('prepared batch already exists; do not replace it')
    if sha(HISTORY) != HISTORY_HASH:
        raise RuntimeError('historical evidence changed')
    completed = [json.loads(line) for line in HISTORY.read_text(encoding='utf-8').splitlines()
                 if json.loads(line)['status'] == 'completed']
    anomalies = [(index + 1, record) for index, record in enumerate(completed)
                 if len(record['raw']['tool_calls']) != 1]
    if [index for index, _ in anomalies] != [2, 5]:
        raise RuntimeError('unexpected historical anomalies')
    data.mkdir(parents=True)
    model = gateway(data)
    cases = []
    # Fixed interleaved order; later repetitions never receive earlier answers.
    for repeat in (1, 2):
        for index, record in anomalies:
            case_id = f'qa-wire-{index}-repeat-{repeat}'
            messages = deepcopy(record['preview']['payload']['messages'])
            preview = model.preview(messages, Decision)
            cases.append({'case_id': case_id, 'historical_call_index': index,
                          'historical_call_id': record['call_id'], 'messages': messages})
            save(data / (case_id + '-preview.json'), preview)
    save(data / 'inputs.json', cases)
    source_paths = ['scripts/check_json_decisions.py', 'src/agent_workbench/models.py',
                    'src/agent_workbench/qa.py', 'requirements-v1.lock.txt']
    save(data / 'source-hashes.json', {name: sha(ROOT / name) for name in source_paths})
    bound = 4 * ((INPUT_LIMIT * 4 + 2048) * .30 + OUTPUT_LIMIT * 1.20) / 1_000_000
    save(data / 'outbound-scope.json', {
        'status': 'PREPARED_NOT_AUTHORIZED_NOT_RUN', 'endpoint': model.endpoint + '/chat/completions',
        'model': model.model, 'output_method': model.output_method,
        'historical_ledger_sha256': HISTORY_HASH, 'case_order': [c['case_id'] for c in cases],
        'max_calls_including_failed_unknown': 4, 'max_input_chars_per_call': INPUT_LIMIT,
        'max_output_tokens_per_call': OUTPUT_LIMIT, 'max_new_battles': 0,
        'new_batch_cap_usd': .10, 'conservative_bound_usd': round(bound, 8),
        'price_source': 'https://api-docs.deepseek.com/quick_start/pricing/',
        'pricing_basis': '2026-10-05 peak uncached input USD0.30/M, output USD1.20/M; 4 UTF-8 bytes/input char plus 2048 protocol-token margin.',
        'data': ['Two historical QA input contexts that produced multiple Decision calls, each twice',
                 'Candidate diff/identity, Schema/rules, actual paired metrics, remaining-resource snapshot',
                 'Current Decision schema and explicit single JSON object instructions'],
        'excluded': ['Historical answers, confirmation-set labels, source code, credentials, unrelated files'],
        'purpose': 'Known-input structural protocol regression only; no tools, graph, simulation or updated business report executed; no quality/rate guarantee.',
        'pass_gate': 'All four first responses must satisfy full raw JSON and Decision validation. Any failure keeps Config confirmation pending; no selective rerun/fallback.',
        'budget_policy': 'New authorization; old ledger stays closed and untouched. Failed/unknown calls consume the new four-call cap. Unused calls close with this batch.',
        'review_files': {p.name: sha(p) for p in sorted(data.glob('*.json'))}})
    return {'scope': str(data / 'outbound-scope.json'), 'scope_sha256': sha(data / 'outbound-scope.json'),
            'input_chars': [read(data / (c['case_id'] + '-preview.json'))['input_chars'] for c in cases],
            'conservative_bound_usd': bound, 'model_calls': 0}


def live(data=DATA):
    scope = read(data / 'outbound-scope.json')
    auth = read(data / 'authorization.json')
    if auth.get('scope_sha256') != sha(data / 'outbound-scope.json') or auth.get('approved') is not True:
        raise RuntimeError('exact scope authorization required')
    for name, expected in scope['review_files'].items():
        if sha(data / name) != expected:
            raise RuntimeError('prepared input changed: ' + name)
    for name, expected in read(data / 'source-hashes.json').items():
        if sha(ROOT / name) != expected:
            raise RuntimeError('prepared implementation changed: ' + name)
    if sha(HISTORY) != HISTORY_HASH:
        raise RuntimeError('historical evidence changed')
    model = gateway(data)
    if model.remaining_calls() != 4 or (data / 'closed.json').exists():
        raise RuntimeError('batch was already started or closed')
    save(data / 'started.json', {'scope_sha256': auth['scope_sha256'], 'at': time.time()})
    from demo_v1 import load_local_credential
    load_local_credential()
    observations = []
    for case in read(data / 'inputs.json'):
        expected_preview = read(data / (case['case_id'] + '-preview.json'))
        if model.preview(case['messages'], Decision) != expected_preview:
            raise RuntimeError('live preview differs from approved input')
        started = time.monotonic()
        observation = {'case_id': case['case_id'], 'source': 'live', 'tools_executed': 0,
                       'new_battles': 0}
        try:
            observation.update(status='passed', decision=model.complete(case['messages'], Decision))
        except Exception as exc:
            observation.update(status='failed', error_type=type(exc).__name__)
        observation['elapsed_seconds'] = time.monotonic() - started
        observations.append(observation)
        save(data / (case['case_id'] + '-observation.json'), observation)
        print(case['case_id'] + ': ' + observation['status'], flush=True)
    save(data / 'summary.json', {'protocol_gate_passed': all(o['status'] == 'passed' for o in observations),
                                'observations': observations, 'model_calls': 4, 'new_battles': 0,
                                'historical_ledger_unchanged': sha(HISTORY) == HISTORY_HASH})
    save(data / 'closed.json', {'remaining_calls_closed': model.remaining_calls(),
                               'no_fallback_or_selective_rerun': True})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    if args.live:
        live()
    else:
        print(json.dumps(prepare(), ensure_ascii=False, indent=2))
