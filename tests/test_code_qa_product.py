import asyncio
import base64
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agent_workbench.code_candidates import CodeWorkspace, PROFILE
from agent_workbench.domain._shared import Artifacts
from agent_workbench.jobs import JobStore, RecoveryRequired
from agent_workbench.code_tools import CodeCatalog, CodeTools
from agent_workbench.verification.code_agent import CodeVerificationAgent
from agent_workbench.protocol import delegate, local_verifier


def fixture(root):
    control = root / 'source'
    artifacts = Artifacts(control / 'artifacts')
    target = 'game-core/combat_core/v2/effects.py'
    def tree(raw):
        return {'schema_version': 'code-tree-v1', 'files': {target: {
            'sha256': hashlib.sha256(raw).hexdigest(), 'content': base64.b64encode(raw).decode()}}}
    before = artifacts.put(tree(b'x=1\n'), 'code-tree-v1')
    after = artifacts.put(tree(b'x=2\n'), 'code-tree-v1')
    prep = dict(profile=PROFILE, game_commit='a'*40, baseline_commit='b'*40, baseline_tree=before)
    manifest = dict(schema_version='code-candidate-v1', kind='code', profile=PROFILE,
        request='修复护盾', case='D-01-controlled-fault', game_commit=prep['game_commit'],
        baseline_commit=prep['baseline_commit'], baseline_tree=before, candidate_tree=after,
        changed_files=[target], added_files=[], deleted_files=[],
        patch=artifacts.put({'text': f'diff --git a/{target} b/{target}\n--- a/{target}\n+++ b/{target}\n@@ -1 +1 @@\n-x=1\n+x=2\n'}, 'code-patch-v1'))
    candidate = artifacts.put(manifest, 'code-candidate-v1')['sha256']
    return CodeWorkspace(control, root/'absent', prep), candidate


class CodeQATests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)/'data'
        self.root.mkdir()
        workspace, self.candidate = fixture(Path(self.tmp.name))
        CodeCatalog(self.root).register(workspace, self.candidate)
        self.jobs = JobStore(self.root)
        self.jobs.confirm(self.candidate)

    def result(self, tree):
        return {'verdict': 'PASS', 'exit_code': 0,
                'tests': [{'name':f'test_{i}', 'status':'PASS'} for i in range(4)],
                'game_events': [{'hp':100}], 'image':'fixture',
                'oracle_hash':'fixture', 'runner_hash':'fixture'}

    async def test_shared_a2a_code_pass_and_repeated_delivery_zero_execution(self):
        tools = CodeTools(self.root)
        async def callback(request_id):
            return await CodeVerificationAgent(self.root, None, tools).run(request_id)
        with patch('agent_workbench.code_sandbox.execute_tree', side_effect=self.result) as execute:
            async with local_verifier(self.root, callback) as base:
                first = await delegate(base, 'code-qa', self.candidate, '检查护盾修复', 2, kind='code', profile=PROFILE)
                again = await delegate(base, 'code-qa', self.candidate, '检查护盾修复', 2, kind='code', profile=PROFILE)
            self.assertEqual(execute.call_count, 2)
        self.assertEqual(first['report']['verdict'], 'PASS')
        self.assertEqual(first['report'], again['report'])
        self.assertEqual(first['report']['kind'], 'code')

    async def test_receipt_completed_before_graph_checkpoint_reconciles(self):
        self.jobs.admit('recover', self.candidate, '检查', 2)
        tools = CodeTools(self.root)
        with patch('agent_workbench.code_sandbox.execute_tree', side_effect=self.result) as execute:
            # Inner execution has a completed receipt, but the outer claim and
            # graph checkpoint were interrupted before the response returned.
            with patch.object(self.jobs, '_check_result', side_effect=RuntimeError('lost reply')):
                with self.assertRaises(RuntimeError):
                    self.jobs.run('recover', {'variant':'baseline','profile':PROFILE}, 1,
                                  lambda: tools.test_jobs.run(tools.catalog.workspace(self.candidate), self.candidate, 'baseline', run_id='recover'))
            report = await CodeVerificationAgent(self.root, None, tools).run('recover')
            self.assertEqual(execute.call_count, 2)
        self.assertEqual(report['verdict'], 'PASS')
        self.assertEqual(self.jobs.get('recover')['charged_battles'], 2)

    async def test_unknown_attempt_does_not_silently_execute_again(self):
        self.jobs.admit('unknown', self.candidate, '检查', 2)
        tools = CodeTools(self.root)
        with patch('agent_workbench.code_sandbox.execute_tree', side_effect=RuntimeError('killed')) as execute:
            with self.assertRaises(RuntimeError):
                tools.run_test_profile('unknown', 'baseline')
            with self.assertRaises(RecoveryRequired):
                tools.run_test_profile('unknown', 'baseline')
        self.assertEqual(execute.call_count, 1)

    async def test_explicit_new_run_is_new_execution_and_failure_is_not_overridden(self):
        self.jobs.admit('first', self.candidate, '检查', 2)
        self.jobs.admit('replay', self.candidate, '重新测试', 2)
        tools = CodeTools(self.root)
        def failed(tree):
            return self.result(tree) | {'verdict':'FAIL','exit_code':1,
                'tests':[{'name':'failure', 'status':'FAIL'}]}
        with patch('agent_workbench.code_sandbox.execute_tree', side_effect=failed) as execute:
            for request in ('first','replay'):
                report = await CodeVerificationAgent(self.root, None, tools).run(request)
                self.assertEqual(report['verdict'], 'FAIL')
            self.assertEqual(execute.call_count, 4)

    async def test_evidence_cannot_be_read_from_another_request(self):
        self.jobs.admit('empty', self.candidate, '检查', 2)
        with self.assertRaises(ValueError):
            CodeTools(self.root).query_game_events('empty', 'a'*64)

    async def test_real_mcp_startup_exposes_structured_code_inspection(self):
        from agent_workbench.game_tools import connect_tools
        async with connect_tools(self.root,module='agent_workbench.code_tools') as tools:
            view=await tools.call('inspect_code_candidate',{'manifest_hash':self.candidate})
        self.assertEqual(view['manifest_hash'],self.candidate)
