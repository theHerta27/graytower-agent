"""Use the last two authorized calls on one fresh QA request; never reset the cap.

This reuses the original frozen Config candidate. It is not a new Config run or
an independent statistical sample. The fixed output directory is the sole budget
continuation; the sealed first-run directory remains byte-for-byte unchanged.
"""
import argparse
import asyncio
import hashlib
import json
import time

from demo_v1 import ROOT, load_local_credential
from agent_workbench.cli import gateway, verify, write
from agent_workbench.domain import CandidateRepository
from agent_workbench.game_tools import GameTools
from agent_workbench.jobs import JobStore, digest
from agent_workbench.protocol import delegate, local_verifier
from agent_workbench.qa import Decision, VerificationAgent
from agent_workbench.report_view import facts_for_report, render_report

SOURCE = ROOT / 'local-data/v1-demo'
DESTINATION = ROOT / 'local-data/v1-qa-continuation'
REQUEST_ID = 'v1-clean-qa'
LEDGER_HASH = '21e57d4b741b698bbad6f71e7ce293f021db707c3af34d84aac1c98476b77bf4'


def original_ledger():
    raw = (SOURCE / 'model-calls.jsonl').read_bytes()
    if hashlib.sha256(raw).hexdigest() != LEDGER_HASH:
        raise RuntimeError('original model ledger changed; refusing continuation')
    return raw


def prepare():
    raw = original_ledger()
    DESTINATION.mkdir(parents=True, exist_ok=True)
    ledger = DESTINATION / 'model-calls.jsonl'
    if not ledger.exists():
        with ledger.open('xb') as stream:
            stream.write(raw)
    if not ledger.read_bytes().startswith(raw):
        raise RuntimeError('continuation must preserve all six inherited calls')
    old = JobStore(SOURCE).get('v1-live-demo')
    old_repo, repo = CandidateRepository(SOURCE), CandidateRepository(DESTINATION)
    candidate = old_repo.get(old['manifest_hash'])
    hashes = [old['manifest_hash']] + [v['sha256'] for v in candidate['manifest'].values()
                                      if isinstance(v, dict) and 'artifact_id' in v]
    for sha in hashes:
        old_repo.read_artifact(sha)
        path = repo.artifacts.path(sha)
        data = old_repo.artifacts.path(sha).read_bytes()
        if not path.exists():
            with path.open('xb') as stream:
                stream.write(data)
        if path.read_bytes() != data:
            raise RuntimeError('candidate copy differs from frozen original')
    assert repo.get(old['manifest_hash']) == candidate
    store = JobStore(DESTINATION)
    store.confirm(old['manifest_hash'])
    request = store.admit(REQUEST_ID, old['manifest_hash'], old['goal'], old['max_battles'])
    state = {'candidate': GameTools(DESTINATION).inspect_candidate(old['manifest_hash']),
             'observations': [], 'errors': [], 'steps': 0}
    preview = gateway(DESTINATION).preview(VerificationAgent.preview(request, state), Decision)
    write(DESTINATION / 'qa-outbound-preview.json', preview)
    scope = {
        'purpose': 'Fresh independent QA execution on the already frozen Config candidate; no new Config generation.',
        'original_scope': str(SOURCE / 'outbound-scope.json'),
        'endpoint': preview['endpoint'], 'model': 'deepseek-flash',
        'original_ledger_sha256': LEDGER_HASH, 'inherited_reserved_calls': 6,
        'max_total_calls': 8, 'max_additional_calls': 2, 'original_batch_cap_usd': 0.50,
        'max_battles': old['max_battles'], 'manifest_hash': old['manifest_hash'],
        'data': 'Same candidate summary, bounded paired metrics / necessary trace excerpts and structured QA decisions already authorized.',
        'no_independent_quality_claim': 'Same game intent and preferred seeds; these are engineering rerun evidence, not new statistical n.'}
    write(DESTINATION / 'continuation-scope.json', scope)
    return request


async def live():
    request = prepare()
    marker = DESTINATION / 'live-started.json'
    # A crashed/unknown paid attempt requires inspection; never silently rerun.
    with marker.open('x', encoding='utf-8') as stream:
        json.dump({'request_id': REQUEST_ID, 'inherited_ledger_sha256': LEDGER_HASH}, stream)
    load_local_credential()
    started = time.monotonic()
    result = await verify(DESTINATION, REQUEST_ID, request['manifest_hash'], request['goal'], request['max_battles'])
    elapsed = time.monotonic() - started
    store = JobStore(DESTINATION)
    saved = store.get(REQUEST_ID)
    calls_before = (DESTINATION / 'model-calls.jsonl').read_bytes()

    async def must_not_run(_):
        raise AssertionError('completed business request started QA again')

    async with local_verifier(DESTINATION, must_not_run) as endpoint:
        replay = await delegate(endpoint, REQUEST_ID, request['manifest_hash'], request['goal'], request['max_battles'])
    assert replay['report'] == result['report'] and store.get(REQUEST_ID) == saved
    assert (DESTINATION / 'model-calls.jsonl').read_bytes() == calls_before
    assert calls_before.startswith(original_ledger())
    events = [json.loads(line) for line in calls_before.splitlines()]
    reserved = {e['call_id'] for e in events if e['status'] == 'reserved'}
    completed = {e['call_id']: e for e in events if e['status'] == 'completed'}
    assert len(reserved) <= 8
    report = result['report']
    summary = {'request_id': REQUEST_ID, 'manifest_hash': request['manifest_hash'],
               'task_id': result['task_id'], 'task_state': result['task_state'],
               'verdict': report['verdict'], 'structural_verdict': report['structural_verdict'],
               'report_hash': digest(report), 'errors': report['errors'],
               'charged_battles': report['charged_battles'],
               'qa_end_to_end_seconds': elapsed, 'total_reserved_calls': len(reserved),
               'total_completed_calls': len(completed), 'additional_reserved_calls': len(reserved) - 6,
               'original_ledger_unchanged': True, 'inherited_ledger_prefix_unchanged': True,
               'duplicate_report_unchanged': True, 'duplicate_new_model_calls': 0,
               'duplicate_new_battles': 0, 'facts': facts_for_report(report),
               'scope_limit': 'Engineering rerun of QA only, same frozen candidate; no new Config or model-quality/generalization acceptance.'}
    write(DESTINATION / 'continuation-result.json', summary)
    write(DESTINATION / 'duplicate-delivery.json', replay)
    (DESTINATION / 'report.txt').write_text(render_report(report) + '\n', encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    if args.live:
        asyncio.run(live())
    else:
        prepare()
        print('Prepared same-scope QA continuation, zero model calls: ' + str(DESTINATION))
