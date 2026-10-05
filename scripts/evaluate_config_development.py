"""Prepare/review six frozen development inputs; --live needs a NEW authorization.

Uses the real Config graph/domain and one new Config -> A2A -> QA chain. Never
uses the confirmation split, substitutes model fixtures, or resets a paid ledger.
"""
import argparse
import asyncio
import hashlib
import json
import time

from demo_v1 import ROOT, load_local_credential
from agent_workbench.cli import write
from agent_workbench.config import ConfigAgent
from agent_workbench.domain import CandidateRepository
from agent_workbench.domain._shared import source_snapshot, TRUSTED_GAME_ROOT
from agent_workbench.game_tools import GameTools, connect_tools
from agent_workbench.jobs import JobStore
from agent_workbench.models import ModelGateway
from agent_workbench.protocol import delegate, local_verifier
from agent_workbench.qa import Decision, VerificationAgent
from agent_workbench.report_view import facts_for_report, render_report

DATA = ROOT / 'local-data/config-development-v1'
CASES = ROOT / 'research/evals/config-qa-v1/cases.json'
GOAL = '比较修改前后的胜负和行动值，看看本批战斗有没有变快；出现退步时读取相关战斗记录，不把小样本当总体保证。'


def model():
    return ModelGateway(model='deepseek-flash', max_calls=16, max_input_chars=18000,
                        max_output_tokens=2048, audit_path=DATA / 'model-calls.jsonl')


def cases():
    selected = [c for c in json.loads(CASES.read_text(encoding='utf-8'))['cases']
                if c['kind'] == 'config' and c['split'] == 'development']
    if [c['id'] for c in selected] != [f'dev-c0{i}' for i in range(1, 7)]:
        raise RuntimeError('unexpected development set; refusing to select tasks adaptively')
    return selected


def prepare():
    DATA.mkdir(parents=True, exist_ok=True)
    previews = []
    repo = CandidateRepository(DATA / 'preview')
    for case in cases():
        previews.append({'case_id': case['id'], 'preview': ConfigAgent(repo, model()).preview(case['prompt'])})
    # Inspect an example only to make the prospective QA input reviewable. This
    # candidate never substitutes for the live Config result in the paid run.
    first = cases()[0]
    candidate = repo.create(first['prompt'], [{'path': 'skills.breaker_skill.multiplier', 'value': 1.6}])
    request = {'request_id': 'dev-c01-qa', 'manifest_hash': candidate['manifest_hash'],
               'goal': GOAL, 'max_battles': 4, 'status': 'new', 'charged_battles': 0, 'report': None}
    state = {'candidate': GameTools(DATA / 'preview').inspect_candidate(candidate['manifest_hash']),
             'observations': [], 'errors': [], 'steps': 0}
    qa = model().preview(VerificationAgent.preview(request, state), Decision)
    write(DATA / 'config-outbound-previews.json', previews)
    write(DATA / 'qa-outbound-preview.json', qa)
    scope = {'endpoint': 'https://api.deepseek.com/chat/completions', 'model': 'deepseek-flash',
             'case_ids': [c['id'] for c in cases()], 'cases_sha256': hashlib.sha256(CASES.read_bytes()).hexdigest(),
             'max_calls_total_including_failed_unknown': 16, 'max_calls_config': 12, 'max_calls_qa': 4,
             'max_input_chars_per_call': 18000, 'max_output_tokens_per_call': 2048,
             'new_batch_cap_usd': 0.50,
             'conservative_bound_usd': 16 * ((18000 * 4 + 2048) * .30 + 2048 * 1.20) / 1_000_000,
             'pricing_basis': '2026-10-05 peak input miss $0.30/M, output $1.20/M; no cache discount; up to four UTF-8 bytes per input character plus 2048 token protocol margin.',
             'price_source': 'https://api-docs.deepseek.com/quick_start/pricing/',
             'data': ['six development requests and exact Config preview payloads',
                      'same-request proposed changes and deterministic repair feedback, at most one repair each',
                      'dev-c01 live Config candidate only: diff, validation, 4-battle paired metrics and necessary bounded Trace excerpts',
                      'structured Agent decisions and dynamic remaining resource counts'],
             'excluded': ['confirmation tasks', 'whole repository', 'source code', 'credentials in content', 'unrelated files'],
             'qa_selection': 'dev-c01 only, if live Config produces its exact 1.4->1.6 diff and valid candidate; no replacement task if it fails',
             'automatic_confirmation': 'authorized demonstration operator confirms this one exact live candidate for QA, never applies it to baseline',
             'budget_relation': 'NEW batch requires explicit approval; old 8-call batch is closed and never reset',
             'stage': 'development results only; independent confirmation and full product acceptance remain later'}
    write(DATA / 'outbound-scope.json', scope)
    return scope


async def run_qa(candidate, gateway):
    root = DATA / 'dev-c01'
    JobStore(root).confirm(candidate['manifest_hash'])
    async with connect_tools(root) as tools:
        agent = VerificationAgent(root, gateway, tools)
        async with local_verifier(root, agent.run) as endpoint:
            result = await delegate(endpoint, 'dev-c01-qa', candidate['manifest_hash'], GOAL, 4)
    write(DATA / 'qa-delivery.json', result)
    (DATA / 'qa-report.txt').write_text(render_report(result['report']) + '\n', encoding='utf-8')
    write(DATA / 'qa-facts.json', facts_for_report(result['report']))
    return result


def live():
    scope = json.loads((DATA / 'outbound-scope.json').read_text(encoding='utf-8'))
    if scope['cases_sha256'] != hashlib.sha256(CASES.read_bytes()).hexdigest():
        raise RuntimeError('case pack changed since preview')
    with (DATA / 'live-started.json').open('x', encoding='utf-8') as stream:
        json.dump({'cases_sha256': scope['cases_sha256'], 'max_calls': 16}, stream)
    load_local_credential()
    gateway = model()
    observations = {}
    started = time.monotonic()
    baseline = source_snapshot(TRUSTED_GAME_ROOT)
    for case in cases():
        case_root = DATA / case['id']
        before = len([e for e in gateway.calls if e['status'] == 'reserved'])
        tick = time.monotonic()
        output = ConfigAgent(CandidateRepository(case_root), gateway).draft(case['prompt'])
        audit = {'source': 'live', 'completed': not bool(output.get('error_type')),
                 'baseline_unchanged': source_snapshot(TRUSTED_GAME_ROOT) == baseline,
                 'battle_count': 0, 'candidate_created': output.get('candidate') is not None,
                 'model_reserved_calls': len([e for e in gateway.calls if e['status'] == 'reserved']) - before,
                 'elapsed_seconds': time.monotonic() - tick}
        observations[case['id']] = {'output': output, 'audit': audit}
        write(DATA / 'observations.json', observations)
        print(case['id'] + ': ' + output['status'], flush=True)
    first = observations['dev-c01']['output']
    candidate = first.get('candidate')
    qa_result = None
    if (candidate and candidate['diff'] == cases()[0]['expected']['diff']
            and candidate['validation']['passed'] is True):
        qa_result = asyncio.run(run_qa(candidate, gateway))
    write(DATA / 'run-summary.json', {'config_cases': len(observations),
          'model_reserved_calls': len([e for e in gateway.calls if e['status'] == 'reserved']),
          'baseline_unchanged': source_snapshot(TRUSTED_GAME_ROOT) == baseline,
          'elapsed_seconds': time.monotonic() - started,
          'qa_task_state': qa_result['task_state'] if qa_result else None,
          'qa_errors': qa_result['report']['errors'] if qa_result else None,
          'qa_charged_battles': qa_result['report']['charged_battles'] if qa_result else 0,
          'limits': 'Development only; semantic review separate. No confirmation tasks run.'})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    if args.live:
        live()
    else:
        scope = prepare()
        print(json.dumps({'scope': str(DATA / 'outbound-scope.json'), 'conservative_bound_usd': scope['conservative_bound_usd']}, ensure_ascii=False))
