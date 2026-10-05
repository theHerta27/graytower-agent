"""Serve the authorized two-task acceptance through the real workbench UI.

This harness only restricts the live scope and measures the existing A2A path.
It cannot draft, add a third task, reset the shared ledger, or apply a candidate.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]
from agent_workbench.models import ModelGateway
from agent_workbench.workbench import Workbench, create_app
from demo_v1 import load_local_credential

DATA = ROOT / 'local-data/qa-independent-v1-32k'
DOMAIN = ROOT / 'local-data/workbench-v1'


def read(name):
    return json.loads((DATA / name).read_text(encoding='utf-8'))


def save(name, value):
    with (DATA / name).open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    scope, auth, bindings = read('outbound-scope.json'), read('authorization.json'), read('execution-bindings.json')
    if auth['scope_sha256'] != sha(DATA / 'outbound-scope.json') or auth['answer'] != '授权本批，按上述范围与上限执行':
        raise RuntimeError('exact scope authorization is required')
    for name, expected in scope['review_files'].items():
        if sha(DATA / name) != expected:
            raise RuntimeError('prepared input changed: ' + name)
    for name, expected in read('source-hashes.json')['files'].items():
        if sha(ROOT / name) != expected:
            raise RuntimeError('prepared source changed: ' + name)
    cases = bindings['cases']
    by_manifest = {case['manifest_hash']: case for case in cases}

    def match(request):
        case = by_manifest.get(request['manifest_hash'])
        if not case or any(request[key] != case['request'][key] for key in ('manifest_hash', 'goal', 'max_battles')):
            raise RuntimeError('request is outside the two authorized tasks')
        return case

    class ScopedModel(ModelGateway):
        def complete(self, messages, schema):
            request = json.loads(messages[1]['content'])['request']
            case = match(request)
            starts = []
            if self.audit_path.exists():
                starts = [json.loads(line) for line in self.audit_path.read_text(encoding='utf-8').splitlines() if line]
            used = sum(record['status'] == 'reserved' and json.loads(
                record['preview']['payload']['messages'][1]['content'])['request']['manifest_hash'] == case['manifest_hash']
                for record in starts)
            if used >= 4:
                raise RuntimeError('this case has used its four model reservations')
            return super().complete(messages, schema)

    original_run = Workbench.run_verification

    async def measured_run(workbench, payload):
        case = match(payload)
        name = case['case_id']
        start_path = DATA / (name + '-start.json')
        if start_path.exists():
            previous = read(name + '-start.json')
            if previous['request'] != payload or workbench.jobs.get(payload['request_id'])['report'] is None:
                raise RuntimeError('no replacement or repeated live run is authorized')
            return await original_run(workbench, payload)
        index = cases.index(case)
        if index and not (DATA / (cases[index - 1]['case_id'] + '-observation.json')).exists():
            raise RuntimeError('fixed case order must be preserved')
        save(name + '-start.json', {'request': payload, 'started_utc': datetime.now(timezone.utc).isoformat(),
                                  'case_id': name, 'source': 'real browser workbench submission'})
        started = time.perf_counter()
        try:
            delivery = await original_run(workbench, payload)
        except Exception as exc:
            save(name + '-observation.json', {'case_id': name, 'request': payload,
                 'qa_delegate_to_stop_seconds': time.perf_counter() - started,
                 'failure_type': type(exc).__name__, 'delivery': None})
            raise
        save(name + '-observation.json', {'case_id': name, 'request': payload,
             'qa_delegate_to_stop_seconds': time.perf_counter() - started, 'delivery': delivery})
        return delivery

    Workbench.run_verification = measured_run
    sources = list((ROOT / 'src/agent_workbench').rglob('*.py')) + [Path(__file__)]
    source_seal = {str(path.relative_to(ROOT)).replace('\\', '/'): sha(path) for path in sources}
    seal = DATA / 'live-source-hashes.json'
    if seal.exists():
        if read(seal.name) != source_seal:
            raise RuntimeError('live implementation changed since first startup')
    else:
        save(seal.name, source_seal)
    load_local_credential()  # Exact authorized local credential; never printed or persisted.
    import uvicorn
    app = create_app(DOMAIN, call_cap=8, audit_path=DATA / 'model-calls.jsonl',
                     model_actions=('verify',), model_factory=ScopedModel)
    uvicorn.run(app, host='127.0.0.1', port=8765, access_log=False, log_level='warning')


if __name__ == '__main__':
    main()
