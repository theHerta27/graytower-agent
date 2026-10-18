import unittest
from starlette.testclient import TestClient
import test_development_checks as fixtures
try:
    from agent_workbench.development.web import create_app
except ModuleNotFoundError:
    create_app=None


class DevelopmentWebTests(unittest.TestCase):
    def setUp(self):
        fixtures.DevelopmentCheckTests.setUp(self)
        self.assertIsNotNone(create_app)
        self.app=create_app(self.root/'web',api_key='never-expose-fixture-key',runtime_python='unused')
        self.client=TestClient(self.app,base_url='http://127.0.0.1:18790')
        self.client.__enter__();self.addCleanup(self.client.__exit__,None,None,None)

    def create(self):
        r=self.client.post('/api/development/tasks',json={'project':str(self.root/'source'),'request':'修复新的规则问题'})
        self.assertEqual(r.status_code,200,r.text);return r.json()

    def test_real_project_new_request_and_initial_empty_diff(self):
        task=self.create()
        self.assertEqual(task['request'],'修复新的规则问题')
        self.assertEqual(task['changed_files'],[])
        self.assertEqual(task['model_state'],'not_started')
        self.assertNotIn('never-expose',self.client.get('/api/development/status').text)
        self.assertEqual(len(self.client.get('/api/development/tasks').json()['tasks']),1)

    def test_cross_origin_bad_paths_and_unknown_fields_are_rejected(self):
        self.assertEqual(self.client.post('/api/development/tasks',headers={'Origin':'https://evil.invalid'},json={}).status_code,403)
        task=self.create();prefix='/api/development/tasks/'+task['task_id']
        self.assertEqual(self.client.get(prefix+'/file',params={'path':'../secret'}).status_code,422)
        self.assertEqual(self.client.post(prefix+'/check',json={'check_set':'effects','command':'dir'}).status_code,422)
        self.assertEqual(self.client.get('/local-data/requests.json').status_code,404)

    def test_model_preview_is_free_and_run_needs_explicit_both_consents(self):
        from unittest.mock import patch
        task=self.create();prefix='/api/development/tasks/'+task['task_id']
        with patch('agent_workbench.development.web.deepseek_sender') as sender:
            prepared=self.client.post(prefix+'/prepare',json={})
            self.assertEqual(prepared.status_code,200,prepared.text)
            scope=prepared.json()
            denied=self.client.post(prefix+'/run',json={'run_id':scope['run_id'],'scope_sha256':scope['scope_sha256']})
            self.assertEqual(denied.status_code,422)
            sender.assert_not_called()

    def test_human_edit_real_diff_and_discard_does_not_touch_source(self):
        task=self.create();prefix='/api/development/tasks/'+task['task_id']
        file=self.client.get(prefix+'/file',params={'path':'game-core/combat_core/v2/effects.py'}).json()
        result=self.client.post(prefix+'/edit',json={'operation_id':'manual1','path':file['path'],
              'expected_sha256':file['sha256'],'content':'VALUE = 9\n'})
        self.assertEqual(result.status_code,200,result.text)
        self.assertIn('+VALUE = 9',result.json()['patch'])
        abandoned=self.client.post(prefix+'/discard',json={'tree_hash':result.json()['tree_hash']})
        self.assertEqual(abandoned.status_code,200,abandoned.text)
        self.assertEqual(abandoned.json()['workflow_state'],'discarded')
        self.assertEqual((self.root/'source/game-core/combat_core/v2/effects.py').read_text(),'VALUE = 1\n')

if __name__=='__main__':unittest.main()
