"""Prepare exact, offline Config confirmation payloads; never read credentials."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
for name in ('LANGSMITH_TRACING', 'LANGCHAIN_TRACING_V2', 'LANGCHAIN_TRACING', 'LANGCHAIN_HANDLER'):
    os.environ[name] = 'false'

import httpx

from agent_workbench.config import ConfigAgent, ConfigDecision
from agent_workbench.domain import CandidateRepository
from agent_workbench.domain._shared import TRUSTED_GAME_ROOT, check_changes, source_snapshot
from agent_workbench.models import ModelGateway, no_external_tracing

PACK = ROOT / 'research/evals/config-qa-v1'
DATA = ROOT / 'local-data/config-confirmation-v1'
CASE_IDS = [f'confirm-c{i:02d}' for i in range(1, 13)]
MODEL_KWARGS = dict(model='deepseek-flash', max_calls=24, max_output_tokens=2048, output_method='json_mode')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def save(path, value):
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
        stream.flush()
        os.fsync(stream.fileno())


def public_cases():
    freeze = json.loads((PACK / 'freeze.json').read_text(encoding='utf-8'))
    for name, expected in freeze['files'].items():
        if sha(ROOT / name) != expected:
            raise RuntimeError('frozen task pack seal mismatch: ' + name)
    package = json.loads((PACK / 'cases.json').read_text(encoding='utf-8'))
    selected = [case for case in package['cases'] if case['kind'] == 'config' and case['split'] == 'confirmation']
    if [case['id'] for case in selected] != CASE_IDS:
        raise RuntimeError('fixed confirmation order or denominator changed')
    # No expected, criteria, input, provenance, judge or oracle enters an Agent.
    return [{'id': case['id'], 'prompt': case['prompt']} for case in selected]


def source_hashes():
    paths = ['scripts/prepare_config_confirmation.py', 'scripts/run_config_confirmation.py',
             'src/agent_workbench/models.py', 'src/agent_workbench/config/workflow.py',
             'src/agent_workbench/config/__init__.py', 'src/agent_workbench/domain/__init__.py',
             'src/agent_workbench/domain/_shared.py', 'src/agent_workbench/domain/candidates.py',
             'src/agent_workbench/domain/worker.py', 'requirements-v1.lock.txt',
             'research/evals/config-qa-v1/cases.json', 'research/evals/config-qa-v1/freeze.json',
             'research/evals/config-qa-v1/evaluate.py']
    return {name: sha(ROOT / name) for name in paths}


def repair_messages(agent, messages, decision):
    try:
        check_changes('capacity-only', decision['changes'], 'config')
    except ValueError as exc:
        error = str(exc)
    else:
        raise RuntimeError('size-only repair fixture must fail deterministic precheck')
    state = {'attempts': 1, 'messages': messages, 'validation_errors': []}
    return agent._failure(state, error, decision)['messages']


def prepare(data=DATA):
    data = Path(data).resolve()
    if data.exists():
        raise RuntimeError('preparation directory already exists; refusing overwrite')
    cases, sources = public_cases(), source_hashes()
    snapshot = source_snapshot(TRUSTED_GAME_ROOT)
    data.mkdir(parents=True)
    measurements, payloads = [], []
    def deny_http(request):
        raise RuntimeError('offline preview forbids network requests')
    with httpx.Client(transport=httpx.MockTransport(deny_http), trust_env=False) as client, no_external_tracing():
        ruler = ModelGateway(**MODEL_KWARGS, max_input_chars=1000000,
                             audit_path=data / 'model-calls.jsonl', http_client=client)
        for case in cases:
            case_root = data / 'cases' / case['id']
            agent = ConfigAgent(CandidateRepository(case_root), ruler, max_repairs=1)
            initial = agent.preview(case['prompt'])['model_preview']
            payloads.append({'case_id': case['id'], 'preview': initial})
            messages = agent.preview(case['prompt'])['messages']
            scenarios = {
                'initial': messages,
                'one_out_of_range_repair': repair_messages(agent, messages, {
                    'status': 'candidate', 'message': '容量检查：越界候选，非确认题答案。',
                    'changes': [{'path': 'skills.breaker_skill.multiplier', 'value': 1.9}]}),
                'one_schema_max_string_repair': repair_messages(agent, messages, {
                    'status': 'candidate', 'message': '\\' * 2000,
                    'changes': [{'path': '\\' * 200, 'value': 1.7} for _ in range(8)]})}
            for label, repair in scenarios.items():
                preview = ruler.preview(repair, ConfigDecision)
                measurements.append({'case_id': case['id'], 'profile': label,
                                     'input_chars': preview['input_chars'],
                                     'full_payload_chars': len(json.dumps(preview['payload'], ensure_ascii=False, sort_keys=True)),
                                     'fits_8000': preview['input_chars'] <= 8000})
        limit = max(8000, math.ceil(max(row['input_chars'] for row in measurements) / 1000) * 1000)
        exact = ModelGateway(**MODEL_KWARGS, max_input_chars=limit,
                             audit_path=data / 'model-calls.jsonl', http_client=client)
        # Regenerate with the chosen live hard cap; do not publish the ruler cap.
        payloads = [{'case_id': case['id'], 'preview': ConfigAgent(
            CandidateRepository(data / 'cases' / case['id']), exact, max_repairs=1).preview(case['prompt'])['model_preview']}
            for case in cases]
        if exact.calls or ruler.calls or (data / 'model-calls.jsonl').exists():
            raise RuntimeError('preparation unexpectedly recorded a model call')
    if source_snapshot(TRUSTED_GAME_ROOT) != snapshot or source_hashes() != sources:
        raise RuntimeError('execution sources changed during preparation')
    save(data / 'outbound-previews.json', payloads)
    save(data / 'repair-capacity.json', {
        'purpose': 'offline full-wire size check, not confirmation output or live result',
        'start_limit': 8000, 'selected_limit': limit, 'measurements': measurements,
        'profiles': ['Normal complete initial payload', 'Real deterministic out-of-range feedback and one prior decision',
                     'Schema-valid maximum message/path lengths with escaping, eight edits; real multiple-edit rejection feedback'],
        'limits': 'Representative plus schema string stress sizing; not a universal bound on arbitrary numeric or error text. Oversized real feedback fails closed at the frozen hard limit, is retained, and is not retried with a larger cap.',
        'synthetic_decisions_sent': False})
    save(data / 'source-hashes.json', {'files': sources, 'game_snapshot': snapshot})
    bound = 24 * ((limit * 4 + 2048) * .30 + 2048 * 1.20) / 1000000
    scope = {'schema_version': 'config-confirmation-scope-v1', 'status': 'PREPARED_AWAITING_NEW_AUTHORIZATION',
             'case_ids': CASE_IDS, 'fixed_denominator': 12, 'model': 'deepseek-flash', 'output_method': 'json_mode',
             'endpoint': 'https://api.deepseek.com/chat/completions',
             'max_calls_total_including_failed_unknown': 24, 'max_calls_per_case': 2,
             'max_repairs_per_case': 1, 'max_input_chars_per_call': limit, 'max_output_tokens_per_call': 2048,
             'max_new_battles': 0, 'max_candidate_confirmations': 0,
             'conservative_bound_usd': round(bound, 6), 'proposed_cap_usd': math.ceil(bound * 20) / 20,
             'price_basis': '2026-10-05 previously verified official peak pricing: USD0.30/M uncached input, USD1.20/M output; 4 UTF-8 bytes per input character plus 2048 protocol tokens; no cache discount.',
             'price_source': 'https://api-docs.deepseek.com/quick_start/pricing/',
             'data': ['12 frozen natural requests with normal repository schema/rules/catalog and Config JSON schema',
                      'At most one same-request generated decision and deterministic validation feedback per case'],
             'excluded': ['expected', 'criteria', 'oracle', 'other cases in any case payload', 'source code',
                          'credentials', 'historical outputs', 'QA/Trace/battle data', 'synthetic size-only decisions'],
             'ledger': 'model-calls.jsonl', 'case_data_roots': 'cases/<fixed case id>',
             'policy': 'Fixed order, first complete attempt including at most one standard repair; no restart, replacement, selective rerun or old-ledger reuse. Failed/unknown reservations consume calls.',
             'independent_review': 'Use frozen evaluate.py per-case score_case with observation hash and independent_assistant/human source; no model self-score. Missing confirmation report tasks are outside this 12-Config batch, not silently added.',
             'source_hashes': sources,
             'sealed_files': {name: sha(data / name) for name in ('outbound-previews.json', 'repair-capacity.json', 'source-hashes.json')},
             'new_model_calls': 0, 'new_battles': 0}
    save(data / 'outbound-scope.json', scope)
    return scope


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=DATA)
    args = parser.parse_args()
    scope = prepare(args.data)
    print(json.dumps({'path': str(args.data.resolve() / 'outbound-scope.json'),
                      'sha256': sha(args.data / 'outbound-scope.json'),
                      'max_input_chars': scope['max_input_chars_per_call'],
                      'conservative_bound_usd': scope['conservative_bound_usd'],
                      'proposed_cap_usd': scope['proposed_cap_usd']}, ensure_ascii=False, indent=2))
