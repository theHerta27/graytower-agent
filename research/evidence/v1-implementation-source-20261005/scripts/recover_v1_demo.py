"""Read existing live evidence, prove replay, then add one bounded explanation."""
import asyncio
import json
from pathlib import Path
import sys

from demo_v1 import ROOT, load_local_credential
from agent_workbench.cli import gateway, write
from agent_workbench.explain import explain_report
from agent_workbench.game_tools import connect_tools
from agent_workbench.jobs import JobStore, digest
from agent_workbench.protocol import delegate, local_verifier
from a2a.client import ClientConfig, create_client
from a2a.types import GetTaskRequest
from google.protobuf.json_format import MessageToDict
import httpx


async def main():
    root = ROOT / 'local-data/v1-demo'
    store = JobStore(root)
    request_id = 'v1-live-demo'
    before = store.get(request_id)
    receipt_hashes = [digest(r) for r in store.receipts(request_id)]
    async def must_not_run(_):
        raise AssertionError('duplicate delivery must not start QA again')
    async with local_verifier(root, must_not_run) as endpoint:
        original_id = json.loads((root / 'demo-result.json').read_text(encoding='utf-8'))['task_id']
        async with httpx.AsyncClient(trust_env=False, timeout=30) as http:
            client = await create_client(endpoint, client_config=ClientConfig(streaming=False, httpx_client=http))
            original = await client.get_task(GetTaskRequest(id=original_id))
            write(root / 'original-a2a-task-readback.json', MessageToDict(original))
        delivered = await delegate(endpoint, request_id, before['manifest_hash'], before['goal'], before['max_battles'])
    write(root / 'recovery-a2a-delivery.json', delivered)
    load_local_credential()
    async with connect_tools(root) as tools:
        # Exercise the repaired response path against the already completed job.
        receipt = store.receipts(request_id)[0]
        replay = await tools.call('run_simulation', dict(request_id=request_id, **receipt['args']))
        assert replay == receipt
        trace = await tools.call('read_trace', {'request_id': request_id, 'artifact_hash': receipt['result']['trace_refs'][0]['sha256']})
        appendix = await explain_report(root, request_id, gateway(root), tools)
        # Persistent reuse must not call either the model or new physical work.
        class NoModel:
            def complete(self, *args):
                raise AssertionError('appendix replay called model')
        assert await explain_report(root, request_id, NoModel(), tools) == appendix
    after = store.get(request_id)
    assert before == after
    assert receipt_hashes == [digest(r) for r in store.receipts(request_id)]
    result = {'original_report_hash': digest(before['report']), 'original_report_unchanged': True,
              'receipt_hashes': receipt_hashes, 'receipt_hashes_unchanged': True,
              'new_battles': 0, 'charged_battles': after['charged_battles'],
              'replayed_task_id': delivered['task_id'], 'task_state': delivered['task_state'],
              'mcp_receipt_replay_ok': True, 'mcp_trace_read_ok': bool(trace['excerpt']),
              'appendix': appendix, 'original_error_count': len(before['report']['errors'])}
    write(root / 'recovery-result.json', result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
