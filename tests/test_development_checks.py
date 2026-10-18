from pathlib import Path
import subprocess
import tempfile
import unittest
from agent_workbench.development.workspace import ProjectWorkspace

try:
    from agent_workbench.development.checks import CheckJobs
except ModuleNotFoundError:
    CheckJobs = None


class DevelopmentCheckTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(CheckJobs, '候选检查回执尚未实现')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        source = self.root / 'source'; source.mkdir()
        def git(*args):
            return subprocess.check_output(['git','-c','safe.directory='+source.as_posix(),'-C',str(source),*args],stderr=subprocess.PIPE)
        git('init','-q');git('config','user.email','fixture@example.invalid');git('config','user.name','Fixture')
        for name, text in {'game-core/combat_core/v2/effects.py':'VALUE = 1\n',
                           'game-core/tests/v2/test_effects.py':'def test_value():\n    assert True\n'}.items():
            p=source/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(text.encode())
        git('add','.');git('commit','-qm','initial')
        self.workspace=ProjectWorkspace.create(source,self.root/'task')
        self.launched=[]
        self.jobs=CheckJobs(self.root/'checks',launcher=self.launched.append)

    def test_start_freezes_real_tree_and_replay_does_not_launch_twice(self):
        first=self.jobs.start(self.workspace,'rules')
        again=self.jobs.start(self.workspace,'rules')
        self.assertEqual(first['job_id'],again['job_id'])
        self.assertEqual(len(self.launched),1)
        self.assertEqual(first['tree_hash'],self.workspace.inspect()['tree_hash'])
        self.assertEqual(first['status'],'running')

    def test_reopened_running_job_is_unknown_and_never_restarted(self):
        first=self.jobs.start(self.workspace,'rules')
        reopened=CheckJobs(self.root/'checks',launcher=self.launched.append)
        result=reopened.start(self.workspace,'rules')
        self.assertEqual(result['status'],'unknown')
        self.assertEqual(len(self.launched),1)

    def test_completed_receipt_survives_reopen_and_detects_stale_candidate(self):
        first=self.jobs.start(self.workspace,'effects')
        self.jobs.complete(first['job_id'],{'verdict':'PASS','tests':[{'name':'rule','status':'PASS'}],'exit_code':0})
        reopened=CheckJobs(self.root/'checks',launcher=self.launched.append)
        saved=reopened.read(first['job_id'],self.workspace)
        self.assertEqual(saved['status'],'completed')
        self.assertTrue(saved['matches_current_candidate'])
        name='game-core/combat_core/v2/effects.py';before=self.workspace.read_file(name)
        self.workspace.write_file('next',name,before['sha256'],'VALUE = 2\n')
        self.assertFalse(reopened.read(first['job_id'],self.workspace)['matches_current_candidate'])
        second=reopened.start(self.workspace,'effects')
        self.assertNotEqual(second['job_id'],first['job_id'])

    def test_diagnostic_is_observation_not_trusted_pass_and_has_separate_identity(self):
        first=self.jobs.start(self.workspace,'diagnostic',diagnostic='print(1)')
        self.jobs.complete(first['job_id'],{'verdict':'PASS','exit_code':0,'log':'1'})
        saved=self.jobs.read(first['job_id'])
        self.assertEqual(saved['result']['verdict'],'OBSERVATION')
        other=self.jobs.start(self.workspace,'diagnostic',diagnostic='print(2)')
        self.assertNotEqual(first['job_id'],other['job_id'])

    def test_unknown_set_and_oversized_or_misplaced_diagnostic_are_rejected(self):
        for kind,code in [('shell',None),('diagnostic',''),('diagnostic','x'*8001),('rules','print(1)')]:
            with self.subTest(kind=kind),self.assertRaises(ValueError):
                self.jobs.start(self.workspace,kind,diagnostic=code)
        self.assertEqual(self.launched,[])

    def test_empty_trusted_result_cannot_be_pass_and_receipt_is_immutable(self):
        first=self.jobs.start(self.workspace,'rules')
        self.jobs.complete(first['job_id'],{'verdict':'PASS','tests':[],'exit_code':0})
        result=self.jobs.read(first['job_id'])
        self.assertEqual(result['result']['verdict'],'INCONCLUSIVE')
        with self.assertRaises(ValueError):
            self.jobs.complete(first['job_id'],{'verdict':'PASS','tests':[{'name':'fake','status':'PASS'}],'exit_code':0})

    def test_failed_or_skipped_trusted_checks_cannot_be_overridden_by_claim(self):
        first=self.jobs.start(self.workspace,'rules')
        self.jobs.complete(first['job_id'],{'verdict':'PASS','tests':[{'name':'rule','status':'FAIL'}],'exit_code':1})
        self.assertEqual(self.jobs.read(first['job_id'])['result']['verdict'],'FAIL')

    def test_archive_uses_frozen_files_not_later_workspace_edits(self):
        import json
        first=self.jobs.start(self.workspace,'rules')
        request=self.launched[0]
        name='game-core/combat_core/v2/effects.py'
        frozen=json.loads(Path(request['input_path']).read_text(encoding='utf-8'))
        before=self.workspace.read_file(name)
        self.workspace.write_file('after-start',name,before['sha256'],'VALUE = 99\n')
        self.assertEqual(frozen['tree']['files'][name]['sha256'],before['sha256'])

    def test_resource_input_checks_are_host_owned_not_candidate_tests(self):
        from agent_workbench.development.sandbox import archive
        import tarfile
        from io import BytesIO
        first=self.jobs.start(self.workspace,'resource_inputs')
        payload=self.jobs.payload(first['job_id'])
        with tarfile.open(fileobj=BytesIO(archive(payload))) as tar:
            oracle=tar.extractfile('runner/test_resource_inputs.py').read().decode()
        self.assertIn('negative',oracle)
        self.assertIn('state.skill_points == before',oracle)


if __name__=='__main__':
    unittest.main()
