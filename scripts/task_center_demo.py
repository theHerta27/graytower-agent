"""Prepare or serve exactly three Config tasks and one independent QA; no fallback."""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from agent_workbench.config import ConfigAgent
from agent_workbench.domain import CandidateRepository
from agent_workbench.game_tools import GameTools
from agent_workbench.models import ModelGateway
from agent_workbench.verification.agent import Decision, VerificationAgent
from agent_workbench.workbench import APIError, Workbench, create_app

CASES = [
    {'id': 'C-01', 'request': '将击破手战技倍率从1.4调整为1.6，其他字段全部保持不变。'},
    {'id': 'C-02', 'request': '把首领的生命值改成10000，其他不变。'},
    {'id': 'C-03', 'request': '把击破手战技倍率同时改成1.5和1.6，请先给我候选。'},
]
GOAL = '核对倍率仅从1.4改为1.6、战技消耗及削韧不变；用balanced策略、种子7和11比较两版本，共4场。需要时读取必要Trace；样本只做描述，不证明总体改善。'


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(root):
    root.mkdir(parents=True, exist_ok=False)
    repo = CandidateRepository(root / 'preview-data')
    model = ModelGateway(model='deepseek-flash', max_calls=10, max_input_chars=32000,
                         max_output_tokens=2048, audit_path=root / 'model-calls.jsonl')
    config = ConfigAgent(repo, model)
    previews = {case['id']: config.preview(case['request']) for case in CASES}
    sample = repo.create(CASES[0]['request'], [{'path': 'skills.breaker_skill.multiplier', 'value': 1.6}])
    request = {'request_id': 'preview-only', 'manifest_hash': sample['manifest_hash'], 'goal': GOAL,
               'max_battles': 4, 'status': 'new', 'charged_battles': 0, 'report': None}
    state = {'candidate': GameTools(root / 'preview-data').inspect_candidate(sample['manifest_hash']),
             'observations': [], 'errors': [], 'steps': 0}
    previews['QA'] = model.preview(VerificationAgent.preview(request, state, 4), Decision)
    save(root / 'outbound-preview.json', previews)
    save(root / 'outbound-scope.json', {
        'cases': CASES, 'qa_goal': GOAL, 'endpoint': 'https://api.deepseek.com/chat/completions',
        'model': 'deepseek-flash', 'max_calls': 10, 'config_calls': 6, 'qa_calls': 4,
        'max_input_chars': 32000, 'max_output_tokens': 2048, 'max_new_battles': 4,
        'cost_cap_usd': 0.45, 'conservative_bound_usd': 0.41472,
        'price_source': 'https://api-docs.deepseek.com/quick_start/pricing/', 'price_checked': '2026-10-08',
        'bound': '10*( (32000*4+2048)*0.30 + 2048*1.20)/1e6; peak price, no cache discount',
        'data': ['three fixed requests, game Schema/rules/catalog', 'candidate diff and validation/repair feedback',
                 'QA decisions, at most 4 battle metrics and bounded trace excerpts'],
        'not_sent': ['program source', 'credentials as content', 'whole repository', 'old answers or unrelated files'],
        'preview_sha256': sha(root / 'outbound-preview.json'),
        'source_hashes': {str(p.relative_to(ROOT)): sha(p) for p in [Path(__file__), *sorted((ROOT / 'src').rglob('*.py'))]},
        'purpose': 'new P1 functional demonstration; not statistical or collaboration quality confirmation',
        'applies_candidate': False})
    print(str(root / 'outbound-scope.json'))


class ScopedGateway(ModelGateway):
    def complete(self, messages, schema):
        title = schema.__name__
        cap = {'ConfigDecision': 6, 'Decision': 4}.get(title, 0)
        records = [] if not self.audit_path.exists() else [json.loads(s) for s in self.audit_path.read_text(encoding='utf-8').splitlines() if s]
        used = sum(r['status'] == 'reserved' and r.get('preview', {}).get('schema', {}).get('title') == title for r in records)
        if used >= cap:
            raise RuntimeError('action scope exhausted')
        return super().complete(messages, schema)


class ScopedWorkbench(Workbench):
    async def draft(self, value):
        if value.request not in [case['request'] for case in CASES] or value.parent_manifest is not None:
            raise APIError('outside_scope', '本批只运行三道封存任务。', 403)
        with closing(self.operations.connect()) as db:
            for row in db.execute("SELECT id,input FROM operations WHERE kind='draft'"):
                if json.loads(row['input'])['request'] == value.request and row['id'] != value.operation_id:
                    raise APIError('outside_scope', '同一道题不可换编号重复消费本批额度。', 403)
        return await super().draft(value)

    async def verify(self, value, *, resume=False):
        if value.goal != GOAL or value.max_battles != 4:
            raise APIError('outside_scope', '请使用本批固定 QA 目标与4场预算。', 403)
        if self.repo.get(value.manifest_hash)['manifest']['request'] != CASES[0]['request']:
            raise APIError('outside_scope', '仅 C-01 实际候选可交付独立QA。', 403)
        if any(r['request_id'] != value.request_id for r in self.request_list()):
            raise APIError('outside_scope', '本批只允许一次独立 QA。', 403)
        return await super().verify(value, resume=resume)


def serve(root, port):
    scope = json.loads((root / 'outbound-scope.json').read_text(encoding='utf-8'))
    auth = json.loads((root / 'authorization.json').read_text(encoding='utf-8'))
    if auth.get('authorized') is not True or auth.get('scope_sha256') != sha(root / 'outbound-scope.json'):
        raise RuntimeError('explicit authorization bound to this scope is required')
    if (root / 'closed.json').exists():
        raise RuntimeError('batch is closed')
    if sha(root / 'outbound-preview.json') != scope['preview_sha256']:
        raise RuntimeError('outbound preview changed')
    amendment_path = root / 'execution-code-amendment.json'
    amendments = json.loads(amendment_path.read_text(encoding='utf-8')) if amendment_path.exists() else {}
    for name, expected in scope['source_hashes'].items():
        if name in amendments:
            if amendments[name]['original_sha256'] != expected:
                raise RuntimeError('invalid pre-call code amendment')
            expected = amendments[name]['fixed_sha256']
        if sha(ROOT / name) != expected:
            raise RuntimeError('reviewed source changed: '+name)
    from demo_v1 import load_local_credential
    load_local_credential()
    import agent_workbench.workbench as web
    original = web.Workbench
    web.Workbench = ScopedWorkbench
    try:
        app = create_app(root / 'data', call_cap=10, audit_path=root / 'model-calls.jsonl',
                         model_factory=ScopedGateway, model_actions=('draft', 'verify'))
    finally:
        web.Workbench = original
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=port, access_log=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['prepare', 'serve'])
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--port', type=int, default=18783)
    args = parser.parse_args()
    prepare(args.data.resolve()) if args.action == 'prepare' else serve(args.data.resolve(), args.port)
