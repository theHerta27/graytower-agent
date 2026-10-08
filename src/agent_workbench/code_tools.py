"""Bounded code QA ports and MCP. Candidate bytes never execute on the host."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from typing import Any

from .code_candidates import CodeWorkspace, PROFILES
from .code_sandbox import CodeTestJobs
from .domain._shared import Artifacts, encoded, valid_hash
from .jobs import JobStore, digest

TEST_LABELS = {
    PROFILES[0]: ['完全吸收：生命不变', '部分吸收：只扣剩余伤害', '无护盾：正常扣血', '致死溢出与事件记录'],
    PROFILES[1]: ['技能点未满：获得1点', '技能点已满：保持5点', '花费战技：扣除1点', '先花费再获得：资源与事件一致'],
}
CODE_QA_GOALS={
    PROFILES[0]:'独立复核护盾修复：完全吸收不扣血，部分吸收只扣剩余伤害，无护盾正常扣血，并核对伤害与护盾事件。只说明固定4项检查的证据及限制。',
    PROFILES[1]:'独立复核战技点上限修复：普通攻击补给、5点上限、溢出、消耗及资源事件。只说明固定4项检查的证据及限制。',
}


class CodeCatalog:
    """Registration is a trusted local adapter operation, never a client path."""
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root/'code-catalog.sqlite'
        self.artifacts = Artifacts(self.root/'artifacts')
        with closing(self.connect()) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS candidates(id TEXT PRIMARY KEY,preparation TEXT NOT NULL,hash TEXT NOT NULL)')

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def register(self, workspace, candidate_id):
        manifest = workspace.inspect(candidate_id)['manifest']
        # Copy hash-verified bytes, including the exact baseline preparation.
        for ref in [manifest['baseline_tree'], manifest['candidate_tree'], manifest['patch']]:
            value = workspace.artifacts.read_ref(ref, ref['schema'])
            if self.artifacts.put(value, ref['schema'])['sha256'] != ref['sha256']:
                raise ValueError('code artifact import mismatch')
        runtime = manifest.get('provenance',{}).get('runtime_receipt')
        if runtime:
            value = workspace.artifacts.read_ref(runtime,'coding-runtime-receipt-v1')
            if self.artifacts.put(value,'coding-runtime-receipt-v1')['sha256'] != runtime['sha256']:
                raise ValueError('Runtime receipt import mismatch')
        if self.artifacts.put(manifest, 'code-candidate-v1')['sha256'] != candidate_id:
            raise ValueError('code manifest import mismatch')
        prep = workspace.preparation
        raw = encoded(prep).decode('utf-8')
        with closing(self.connect()) as db, db:
            old = db.execute('SELECT preparation FROM candidates WHERE id=?', (candidate_id,)).fetchone()
            if old and old[0] != raw:
                raise ValueError('registered code baseline is immutable')
            db.execute('INSERT OR IGNORE INTO candidates VALUES (?,?,?)', (candidate_id, raw, digest(prep)))
        return candidate_id

    def ids(self):
        with closing(self.connect()) as db:
            return [r[0] for r in db.execute('SELECT id FROM candidates ORDER BY rowid DESC')]

    def workspace(self, candidate_id):
        with closing(self.connect()) as db:
            row = db.execute('SELECT preparation,hash FROM candidates WHERE id=?', (valid_hash(candidate_id),)).fetchone()
        if row is None:
            raise KeyError(candidate_id)
        prep = json.loads(row[0])
        if digest(prep) != row[1]:
            raise ValueError('code preparation integrity failure')
        workspace = CodeWorkspace(self.root, self.root/'no-live-workspace', prep)
        workspace.inspect(candidate_id)
        return workspace

    def view(self, candidate_id):
        workspace = self.workspace(candidate_id)
        manifest = workspace.inspect(candidate_id)['manifest']
        store = JobStore(self.root)
        with closing(store.connect()) as db:
            confirmed = db.execute('SELECT 1 FROM confirmations WHERE manifest=?', (candidate_id,)).fetchone() is not None
        return {'manifest_hash':candidate_id, 'kind':'code', 'profile':manifest['profile'],
                'request':manifest['request'], 'case':manifest.get('case'), 'diff':[],
                'patch':self.artifacts.read_ref(manifest['patch'], 'code-patch-v1')['text'],
                'validation':{'verdict':'PASS'}, 'confirmed':confirmed, 'execution_compatible':True,
                'compatibility_note':'仅在隔离测试环境运行；不会修改当前游戏。',
                'test_labels':TEST_LABELS[manifest['profile']], 'verification_goal':CODE_QA_GOALS[manifest['profile']]}


class CodeTools:
    def __init__(self, root):
        self.root = Path(root)
        self.catalog, self.store, self.test_jobs = CodeCatalog(root), JobStore(root), CodeTestJobs(root)

    def inspect_code_candidate(self, manifest_hash):
        return self.catalog.view(manifest_hash)

    def run_test_profile(self, request_id, variant):
        request = self.store.get(request_id)
        workspace = self.catalog.workspace(request['manifest_hash'])
        profile = workspace.preparation['profile']
        args = {'variant':variant, 'profile':profile}
        # Reconcile the independently committed physical job before looking at
        # the graph/outer claim: completed execution is authoritative.
        existing = self.test_jobs.receipt(workspace, request['manifest_hash'], variant, request_id)
        if existing is not None:
            self.store.reconcile_completed(request_id, args, 1, existing)
        return self.store.run(request_id, args, 1,
            lambda: self.test_jobs.run(workspace, request['manifest_hash'], variant, run_id=request_id))

    def read_test_receipt(self, request_id):
        return {'receipts':self.store.receipts(request_id)}

    def query_game_events(self, request_id, job_id):
        matches = [r for r in self.store.receipts(request_id) if r['job_id'] == valid_hash(job_id)]
        if len(matches) != 1:
            raise ValueError('events are outside this verification')
        result = matches[0]['result']
        return {'job_id':job_id, 'variant':matches[0]['args']['variant'],
                'events':result.get('game_events', []), 'coverage':'本批固定测试产生的事件；不是完整战斗。'}

    async def call(self, name, args):
        import asyncio
        if name not in ('inspect_code_candidate','run_test_profile','read_test_receipt','query_game_events'):
            raise ValueError('unsupported code tool')
        return await asyncio.to_thread(getattr(self, name), **args)


def serve(root):
    from mcp.server import MCPServer
    tools = CodeTools(root)
    server = MCPServer('local-code-tests', version='v1', log_level='WARNING')
    def logged(name, args, value):
        from .jobs import canonical
        with (Path(root)/'code-tool-calls.jsonl').open('a',encoding='utf-8') as stream:
            stream.write(canonical({'tool':name,'arguments':args,'ok':True})+'\n')
        return value
    @server.tool(structured_output=True)
    def inspect_code_candidate(manifest_hash:str) -> dict[str, Any]:
        """Inspect a registered frozen Python patch and its permitted tests."""
        return logged('inspect_code_candidate', {'manifest_hash':manifest_hash}, tools.inspect_code_candidate(manifest_hash))
    @server.tool(structured_output=True)
    def run_test_profile(request_id:str, variant:str) -> dict[str, Any]:
        """Run baseline or candidate in an approved isolated worker; reuse receipts."""
        return logged('run_test_profile', {'request_id':request_id,'variant':variant}, tools.run_test_profile(request_id,variant))
    @server.tool(structured_output=True)
    def read_test_receipt(request_id:str) -> dict[str, Any]:
        """Read completed test results; never execute code."""
        return logged('read_test_receipt', {'request_id':request_id}, tools.read_test_receipt(request_id))
    @server.tool(structured_output=True)
    def query_game_events(request_id:str, job_id:str) -> dict[str, Any]:
        """Read game events belonging to this verification only."""
        return logged('query_game_events', {'request_id':request_id,'job_id':job_id}, tools.query_game_events(request_id,job_id))
    server.run(transport='stdio')


if __name__ == '__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--data',required=True,type=Path)
    serve(parser.parse_args().data)
