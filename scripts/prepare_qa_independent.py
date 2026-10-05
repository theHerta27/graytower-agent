"""Offline preparation only: no credentials, network, confirmation or simulation.

Freezes two trusted-domain candidates and exact initial QA payload previews.
Historical observations are used only in a separate, local input-size check.
This script has no live mode and refuses to replace prior preparation files.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
for tracing_name in ('LANGSMITH_TRACING', 'LANGCHAIN_TRACING_V2', 'LANGCHAIN_TRACING', 'LANGCHAIN_HANDLER'):
    os.environ[tracing_name] = 'false'

import httpx

from agent_workbench.domain import CandidateRepository
from agent_workbench.game_tools import GameTools, _trace_excerpt, validate_game_result
from agent_workbench.jobs import canonical
from agent_workbench.models import ModelGateway, no_external_tracing
from agent_workbench.qa import Decision, VerificationAgent

PACK = ROOT / 'research/evals/qa-independent-v1'
DATA = ROOT / 'local-data/qa-independent-v1-32k'
DOMAIN = ROOT / 'local-data/workbench-v1'
HISTORICAL = ROOT / 'local-data/config-development-v1/dev-c01'
INPUT_LIMIT = 32000
OUTPUT_LIMIT = 2048
MAX_CALLS = 8


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def database_snapshot(root):
    # Read-only connection: preparation never admits, confirms, or starts a job.
    with sqlite3.connect((root / 'jobs.sqlite').as_uri() + '?mode=ro', uri=True) as db:
        return {name: [list(row) for row in db.execute(f'SELECT * FROM {name} ORDER BY 1')]
                for name in ('confirmations', 'requests', 'jobs')}


def snapshot_digest(snapshot):
    return hashlib.sha256(canonical(snapshot).encode('utf-8')).hexdigest()


def deny_http(_request):
    raise RuntimeError('offline preparation forbids HTTP requests')


def gateway(client, *, input_limit=INPUT_LIMIT):
    return ModelGateway(model='deepseek-flash', max_calls=MAX_CALLS,
                        max_input_chars=input_limit, max_output_tokens=OUTPUT_LIMIT,
                        audit_path=DATA / 'model-calls.jsonl', http_client=client)


def capacity_check(prepared, client):
    """Use old actual observations solely to measure serialized prompt sizes."""
    with sqlite3.connect((HISTORICAL / 'jobs.sqlite').as_uri() + '?mode=ro', uri=True) as db:
        rows = db.execute("SELECT receipt FROM jobs WHERE request_id=? AND state='completed' ORDER BY id",
                          ('dev-c01-qa',)).fetchall()
    if len(rows) != 1:
        raise RuntimeError('expected one fixed historical dev-c01 receipt for size checking')
    receipt = json.loads(rows[0][0])
    result = receipt['result']
    validate_game_result(result, receipt['manifest_hash'], receipt['args']['seeds'], receipt['args']['policies'])
    summary = {key: result[key] for key in ('metrics', 'trace_refs', 'structural_verdict', 'overall_verdict', 'limitations')}
    summary['job_id'] = receipt['job_id']
    traces, metadata = [], []
    for variant in ('candidate', 'baseline'):
        ref = next(r for r in result['trace_refs']
                   if r['seed'] == 7 and r['policy'] == 'balanced' and r['variant'] == variant)
        path = HISTORICAL / 'artifacts' / (ref['sha256'] + '.json')
        if sha(path) != ref['sha256']:
            raise RuntimeError('historical trace hash mismatch')
        trace = json.loads(path.read_text(encoding='utf-8'))
        excerpt, selection = _trace_excerpt(trace, ref)
        traces.append({'tool': 'read_trace', 'result': {
            'artifact_hash': ref['sha256'], 'characters': len(canonical(trace)),
            'excerpt': excerpt, 'truncated': True, 'selection': selection, 'reference': ref}})
        metadata.append({'artifact_hash': ref['sha256'], 'variant': variant,
                         'seed': 7, 'policy': 'balanced',
                         'total_events': selection['total_events'],
                         'selected_events': selection['selected_events'],
                         'excerpt_characters': len(excerpt)})
    measurements = []
    # This larger guard is solely an offline ruler so even an over-limit size can
    # be recorded. No live gateway or external-send scope receives that limit.
    ruler = gateway(client, input_limit=1000000)
    for item in prepared:
        for trace_count in (0, 1, 2):
            request = deepcopy(item['request'])
            request.update(status='running', charged_battles=4)
            state = deepcopy(item['state'])
            state.update(observations=[{'tool': 'simulate', 'result': summary}] + traces[:trace_count],
                         steps=1 + trace_count)
            messages = VerificationAgent.preview(request, state,
                remaining_model_calls=item['preview_remaining_calls'] - 1 - trace_count)
            preview = ruler.preview(messages, Decision)
            measurements.append({'case_id': item['case_id'], 'simulated_observation_count': 1,
                                 'trace_observation_count': trace_count,
                                 'input_chars': preview['input_chars'],
                                 'within_input_limit': preview['input_chars'] <= INPUT_LIMIT,
                                 'remaining_character_margin': INPUT_LIMIT - preview['input_chars']})
    return {'purpose': 'LOCAL_SIZE_ONLY_SYNTHETIC_STATE_NOT_NEW_BUSINESS_RESULT',
            'sent_to_model': False, 'excluded_from_new_qa_previews_and_outbound_scope': True,
            'historical_receipt_request': 'dev-c01-qa', 'historical_job_id': receipt['job_id'],
            'historical_database_sha256': sha(HISTORICAL / 'jobs.sqlite'),
            'receipt_sha256': hashlib.sha256(canonical(receipt).encode('utf-8')).hexdigest(),
            'trace_metadata': metadata, 'measurements': measurements,
            'limitations': ['Old 1.6 results are combined with new candidate metadata for size only; identities are not a valid new execution.',
                            'No historical metric or excerpt is copied into a new initial outbound preview.',
                            'Representative sizes do not bound all future observations or guarantee two trace reads fit.',
                            'Live inputs retain the 32000-character hard limit; this check grants no retries.']}


def prepare():
    started = time.monotonic()
    if DATA.exists():
        raise RuntimeError('preparation root already exists; refusing to replace a frozen batch')
    freeze = json.loads((PACK / 'freeze.json').read_text(encoding='utf-8'))
    for name, expected in freeze['files'].items():
        if sha(PACK / name) != expected:
            raise RuntimeError('task pack seal mismatch: ' + name)
    pack_hashes = {name: sha(PACK / name) for name in ('README.md', 'cases.json', 'freeze.json')}
    cases = json.loads((PACK / 'cases.json').read_text(encoding='utf-8'))['cases']
    if [case['id'] for case in cases] != ['ind-qa-01', 'ind-qa-02']:
        raise RuntimeError('unexpected task selection')
    if [case['changes'] for case in cases] != [
            [{'path': 'skills.breaker_skill.multiplier', 'value': 1.52}],
            [{'path': 'skills.breaker_skill.multiplier', 'value': 1.68}]]:
        raise RuntimeError('unexpected frozen candidate parameters')
    before = database_snapshot(DOMAIN)
    DATA.mkdir()
    prepared, bindings = [], []
    with httpx.Client(transport=httpx.MockTransport(deny_http), trust_env=False) as client, no_external_tracing():
        model = gateway(client)
        repo, tools = CandidateRepository(DOMAIN), GameTools(DOMAIN)
        for case, remaining in zip(cases, (8, 4), strict=True):
            candidate = repo.create(case['candidate_request'], case['changes'])
            expected_diff = [{'path': 'skills.breaker_skill.multiplier', 'before': 1.4,
                              'after': case['changes'][0]['value']}]
            if candidate['diff'] != expected_diff or candidate['validation']['passed'] is not True:
                raise RuntimeError('candidate diff or validation differs from frozen task')
            request = {'request_id': case['id'], 'manifest_hash': candidate['manifest_hash'],
                       'goal': case['goal'], 'max_battles': 4, 'status': 'new',
                       'charged_battles': 0, 'report': None}
            state = {'candidate': tools.inspect_candidate(candidate['manifest_hash']),
                     'observations': [], 'errors': [], 'steps': 0}
            preview = model.preview(VerificationAgent.preview(request, state, remaining_model_calls=remaining), Decision)
            name = case['id'] + '-outbound-preview.json'
            save(DATA / name, preview)
            prepared.append({'case_id': case['id'], 'request': request, 'state': state,
                             'preview_remaining_calls': remaining})
            bindings.append({'case_id': case['id'], 'request': request,
                             'manifest_hash': candidate['manifest_hash'], 'diff': candidate['diff'],
                             'validation': candidate['validation'], 'confirmed': False,
                             'admitted': False, 'max_model_decisions': 4,
                             'initial_preview_remaining_calls': remaining,
                             'preview_file': name, 'preview_sha256': sha(DATA / name),
                             'preview_input_chars': preview['input_chars']})
        capacity = capacity_check(prepared, client)
        if model.calls or model.remaining_calls() != MAX_CALLS or (DATA / 'model-calls.jsonl').exists():
            raise RuntimeError('offline preparation unexpectedly reserved a model call')
    after = database_snapshot(DOMAIN)
    if after != before:
        raise RuntimeError('shared confirmations, requests or jobs changed during prepare')
    if any(sha(PACK / name) != expected for name, expected in pack_hashes.items()):
        raise RuntimeError('frozen task pack changed during prepare')
    source_names = ['scripts/prepare_qa_independent.py', 'requirements-v1.lock.txt',
                    'src/agent_workbench/qa.py', 'src/agent_workbench/models.py',
                    'src/agent_workbench/game_tools.py', 'src/agent_workbench/jobs.py',
                    'src/agent_workbench/protocol.py', 'src/agent_workbench/report_view.py',
                    'src/agent_workbench/domain/__init__.py', 'src/agent_workbench/domain/candidates.py',
                    'src/agent_workbench/domain/_shared.py', 'src/agent_workbench/domain/worker.py']
    save(DATA / 'source-hashes.json', {'scope': 'local execution inputs, not sent as source code',
                                     'files': {name: sha(ROOT / name) for name in source_names},
                                     'task_pack_files': pack_hashes})
    save(DATA / 'capacity-check.json', capacity)
    save(DATA / 'execution-bindings.json', {
        'schema_version': 'qa-independent-bindings-v1', 'status': 'PREPARED_NOT_AUTHORIZED_NOT_RUN',
        'domain_root': str(DOMAIN), 'metadata_root': str(DATA),
        'candidate_source': 'offline trusted-domain Author; no Config model generation',
        'task_pack_files': pack_hashes, 'cases': bindings,
        'preview_budget_note': 'First case shows 8 shared calls; second shows 4 assuming first used its maximum. Live budgets must refresh the actual shared ledger and enforce each case maximum of 4.',
        'shared_sqlite_rows_unchanged': True, 'shared_sqlite_rows_sha256': snapshot_digest(after),
        'new_confirmations': 0, 'new_requests': 0, 'new_model_calls': 0, 'new_battles': 0,
        'prepare_seconds': time.monotonic() - started})
    bound = MAX_CALLS * ((INPUT_LIMIT * 4 + 2048) * .30 + OUTPUT_LIMIT * 1.20) / 1000000
    scope = {'schema_version': 'qa-independent-outbound-scope-v1', 'authorized': False,
             'endpoint': 'https://api.deepseek.com/chat/completions', 'model': 'deepseek-flash',
             'fixed_case_ids': [case['id'] for case in cases],
             'shared_domain_root': str(DOMAIN), 'new_shared_model_ledger': str(DATA / 'model-calls.jsonl'),
             'max_calls_total_including_failed_unknown': 8, 'max_calls_per_case': 4,
             'max_new_battles_total': 8, 'max_battles_per_case': 4,
             'max_input_chars_per_call': INPUT_LIMIT, 'max_output_tokens_per_call': OUTPUT_LIMIT,
             'new_batch_cap_usd': 0.40, 'conservative_bound_usd': round(bound, 6),
             'preflight_revision': 'Supersedes the unexecuted 18000-character/USD0.25 proposal only. Local size check measured 25083 characters for two Trace views. Before authorization or live outcomes, raise input cap to 32000 and monetary cap to USD0.40; tasks, order, rubric, 8 calls and 8 battles stay frozen. Original preparation remains at local-data/qa-independent-v1.',
             'pricing_basis': 'Official pricing rechecked 2026-10-05 by parent: peak uncached input USD0.30/M, output USD1.20/M; no cache discount; 4 UTF-8 bytes per input character plus 2048 protocol tokens.',
             'price_source': 'https://api-docs.deepseek.com/quick_start/pricing/',
             'bound_formula': '8*((32000*4+2048)*0.30+2048*1.20)/1000000 = 0.331776',
             'data': ['the two frozen natural goals and exact initial QA messages/Decision schema',
                      'frozen candidate identity, diff, Schema/rules references and deterministic validation feedback',
                      'actual paired metrics within each 4-battle grant and necessary Trace excerpts, each at most 6000 characters',
                      'structured Agent decisions, tool feedback and latest persistent resource counts'],
             'excluded': ['credentials', 'source code or whole repository', 'Config confirmation tasks',
                          'unrelated files', 'historical results or size-only synthetic capacity states',
                          'extra explanation calls, replacement cases or selective reruns'],
             'candidate_confirmation': 'Not performed; future authorization must explicitly cover confirming these exact manifests and delegating both fixed tasks. No baseline apply.',
             'budget_policy': 'New explicit authorization required; one new shared ledger and per-case limits; no reset/copy/reuse of either exhausted old ledger; failed and unknown reservations consume calls.',
             'capacity_policy': 'Keep the hard input limit. The local capacity file is representative only; no automatic cap expansion or evidence trimming.',
             'review_files': {name: sha(DATA / name) for name in (
                 'execution-bindings.json', 'source-hashes.json', 'ind-qa-01-outbound-preview.json', 'ind-qa-02-outbound-preview.json')},
             'local_capacity_check_sha256': sha(DATA / 'capacity-check.json'),
             'new_model_calls': 0, 'new_battles': 0, 'authorization': None}
    save(DATA / 'outbound-scope.json', scope)
    return {'metadata_root': str(DATA), 'scope_sha256': sha(DATA / 'outbound-scope.json'),
            'bindings_sha256': sha(DATA / 'execution-bindings.json'),
            'candidates': [{key: b[key] for key in ('case_id', 'manifest_hash', 'preview_input_chars')} for b in bindings],
            'capacity': capacity['measurements'], 'conservative_bound_usd': scope['conservative_bound_usd'],
            'new_model_calls': 0, 'new_battles': 0, 'new_confirmations': 0}


if __name__ == '__main__':
    print(json.dumps(prepare(), ensure_ascii=False, indent=2))
