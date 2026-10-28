import json
import unittest
from unittest.mock import patch
from starlette.testclient import TestClient
from test_development_git_workspace import GitFixture
from agent_workbench.development.web import create_app
from agent_workbench.development.adoption import Adoption


class GitWebTests(GitFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.app = create_app(self.root/'web',api_key='')
        self.client = TestClient(self.app,base_url='http://127.0.0.1:18790')
        self.client.__enter__(); self.addCleanup(self.client.__exit__,None,None,None)

    def task(self):
        response = self.client.post('/api/development/tasks',json={'project':str(self.project),'request':'修复负数伤害'})
        self.assertEqual(response.status_code,200,response.text)
        value = response.json()
        self.assertEqual(value['mode'],'git_worktree')
        self.assertIn('delivery',value)
        return self.app.state.workbench.task(value['task_id']), '/api/development/tasks/'+value['task_id']

    def test_new_api_review_merge_revert_and_archive(self):
        task,prefix = self.task()
        task.delivery.launcher=lambda request: None
        self.change(task.workspace)
        with self.assertRaises(ValueError): Adoption(task.workspace).apply(task.workspace.inspect()['tree_hash'])
        self.assertEqual(self.client.post(prefix+'/apply',json={'tree_hash':task.workspace.inspect()['tree_hash']}).status_code,422)
        prepared = self.client.post(prefix+'/delivery-prepare',json={'kind':'merge'})
        self.assertEqual(prepared.status_code,200,prepared.text)
        prep = prepared.json()['delivery']
        checked = self.client.post(prefix+'/delivery-check',json={'preparation_id':prep['preparation_id']})
        self.assertEqual(checked.status_code,200,checked.text)
        from agent_workbench.development.git_delivery import GitDelivery
        delivery = GitDelivery(task.workspace)
        checks = delivery.jobs(prep['preparation_id'])
        job = checks.list()[0]
        checks.complete(job['job_id'],{'exit_code':0,'tests':[{'name':'rule','status':'PASS'}]})
        view = self.client.get(prefix).json()['delivery']
        approved = self.client.post(prefix+'/delivery-approve',json={'preparation_id':view['preparation_id'],'approval_hash':view['approval_hash']})
        self.assertEqual(approved.status_code,200,approved.text)
        self.assertEqual(approved.json()['delivery']['state'],'applied')
        revert = self.client.post(prefix+'/delivery-prepare',json={'kind':'revert','operation_id':view['preparation_id']})
        self.assertEqual(revert.status_code,200,revert.text)
        restored = revert.json()['delivery']
        response = self.client.post(prefix+'/delivery-check',json={'preparation_id':restored['preparation_id']})
        self.assertEqual(response.status_code,200,response.text)
        checks = delivery.jobs(restored['preparation_id']); job = checks.list()[0]
        checks.complete(job['job_id'],{'exit_code':0,'tests':[{'name':'rule','status':'PASS'}]})
        ready = self.client.get(prefix).json()['delivery']
        response = self.client.post(prefix+'/delivery-approve',json={'preparation_id':ready['preparation_id'],'approval_hash':ready['approval_hash']})
        self.assertEqual(response.status_code,200,response.text)
        response = self.client.post(prefix+'/archive',json={'tree_hash':task.workspace.inspect()['tree_hash']})
        self.assertEqual(response.status_code,200,response.text)
        self.assertTrue(response.json()['archived'])
        self.assertEqual(self.client.get(prefix).status_code,200)

    def test_scope_binds_workspace_and_unfinished_run_blocks_delivery(self):
        task,prefix = self.task()
        scope = task.prepare('pending',{'max_calls':2,'max_input_bytes':10000,'max_output_tokens':512,
            'cost_cap_usd':'0','input_usd_per_million':'0','cached_input_usd_per_million':'0','output_usd_per_million':'0'})
        self.assertEqual(scope.get('workspace_identity',{}).get('mode'),'git_worktree')
        self.change(task.workspace)
        (task._batch('pending')/'claimed').mkdir()
        response = self.client.post(prefix+'/delivery-prepare',json={'kind':'merge'})
        self.assertEqual(response.status_code,422,response.text)

    def test_running_model_allows_status_read_but_rejects_human_writes(self):
        task,prefix=self.task()
        import threading
        from langchain_core.messages import AIMessage
        entered,release=threading.Event(),threading.Event()
        failures=[]
        class BlockingModel:
            def remaining_calls(self):return 2
            def summary(self):return {'reserved':0,'known_cost_usd':'0'}
            def complete(self,messages,decision_id,final_only=False):
                entered.set();release.wait(30)
                return AIMessage(content='工程检查：没有修改源码。')
        scope=task.prepare('blocking',{'max_calls':2,'max_input_bytes':10000,'max_output_tokens':512,
            'cost_cap_usd':'0','input_usd_per_million':'0','cached_input_usd_per_million':'0','output_usd_per_million':'0'})
        file=task.workspace.read_file(self.file)
        def execute():
            try:task.execute('blocking',scope['scope_sha256'],model=BlockingModel())
            except Exception as exc:failures.append(exc)
        worker=threading.Thread(target=execute);worker.start()
        try:
            self.assertTrue(entered.wait(30))
            response=self.client.get(prefix)
            self.assertEqual(response.status_code,200,response.text)
            response=self.client.post(prefix+'/edit',json={'operation_id':'concurrent',
                'path':self.file,'expected_sha256':file['sha256'],'content':'OVERWRITE=1\n'})
            self.assertEqual(response.status_code,422,response.text)
        finally:
            release.set();worker.join(30)
        self.assertFalse(worker.is_alive())
        self.assertEqual(failures,[])
