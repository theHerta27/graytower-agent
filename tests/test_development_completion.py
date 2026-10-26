"""Campaign boundaries use real Git/scope/ledger, with only providers/grader replaced."""
import hashlib
import json
import unittest
from unittest.mock import patch
import test_development_checks as fixtures
from test_development_assessment import LedgerScript
from langchain_core.messages import AIMessage
from starlette.testclient import TestClient
from agent_workbench.development.web import create_app
from agent_workbench.development.workspace import git
try:
    from agent_workbench.development.completion import prepare_campaign,verify_campaign,run_stage,close_campaign
except ImportError:
    prepare_campaign=verify_campaign=run_stage=close_campaign=None

class CompletionTests(unittest.TestCase):
    def setUp(self):
        fixtures.DevelopmentCheckTests.setUp(self)
        self.assertIsNotNone(prepare_campaign,'completion runner not implemented')
        source=self.root/'source';text='# Rules\n\n## Current rule\n\nCurrent stable rule.\n'
        (source/'docs').mkdir();(source/'docs/rules.md').write_bytes(text.encode('utf-8'))
        git(source,'add','docs/rules.md');git(source,'commit','-qm','rules')
        head=git(source,'rev-parse','HEAD').decode().strip()
        self.corpus=self.root/'corpus.json';self.corpus.write_text(json.dumps({'game_head':head,'sources':[
            {'path':'docs/rules.md','heading':'Current rule','sha256':hashlib.sha256(text.encode()).hexdigest()}]}))
        self.batch=self.root/'campaign';self.scope=prepare_campaign(source,self.batch,corpus_path=self.corpus)

    def factory(self,task,cell):return LedgerScript(task,cell,[AIMessage(content='已核对，证据见检查记录。')])

    def canary(self,*args):return {'pass':True,'budget':{'reserved':2,'known_cost_usd':'0.001','unknown':0}}

    def test_prepare_freezes_seven_tasks_materials_and_one_total_limit(self):
        self.assertEqual(self.scope['max_calls'],106)
        self.assertEqual(self.scope['cost_cap_usd'],'5.10')
        self.assertEqual(len(self.scope['cells']),7)
        self.assertEqual(verify_campaign(self.batch,self.scope['scope_sha256']),self.scope)
        preview=json.loads((self.batch/'outbound-preview.json').read_text())
        self.assertNotIn('Local post-run program checks',json.dumps(preview))
        self.assertEqual([c['knowledge_mode'] for c in self.scope['cells']].count('lexical'),2)

    def test_wrong_scope_does_not_claim_or_construct_provider(self):
        with self.assertRaises(ValueError):run_stage(self.batch,'wrong','canary','',model_factory=self.factory)
        self.assertFalse((self.batch/'phase-canary.json').exists())

    def test_confirmed_campaign_documents_remain_visible_in_the_workbench(self):
        with TestClient(create_app(self.batch),base_url='http://127.0.0.1:18790') as client:
            result=client.get('/api/development/tasks/speed-review-lexical/knowledge')
            self.assertEqual(result.status_code,200,result.text)
            self.assertEqual(len(result.json()['documents']),1)

    def test_stages_run_once_with_shared_limit_and_close_unused_allowances(self):
        with patch('agent_workbench.development.completion._run_canary',side_effect=self.canary),patch('agent_workbench.development.completion.grade_cell',return_value={'verdict':'PASS'}):
            run_stage(self.batch,self.scope['scope_sha256'],'canary','',model_factory=self.factory)
            run_stage(self.batch,self.scope['scope_sha256'],'development','',model_factory=self.factory)
            with self.assertRaises(ValueError):run_stage(self.batch,self.scope['scope_sha256'],'development','',model_factory=self.factory)
            run_stage(self.batch,self.scope['scope_sha256'],'revisions','',model_factory=self.factory)
            run_stage(self.batch,self.scope['scope_sha256'],'rag','',model_factory=self.factory)
            result=close_campaign(self.batch,self.scope['scope_sha256'])
        self.assertEqual(result['reserved_calls'],9)
        self.assertEqual(result['unused_calls_closed'],97)
        with self.assertRaises(ValueError):run_stage(self.batch,self.scope['scope_sha256'],'rag','',model_factory=self.factory)

    def test_revision_is_new_candidate_and_has_no_extra_unallocated_attempt(self):
        def grade(task,cell,*args,**kwargs):return {'verdict':'FAIL' if cell['task_id']=='configurable-cap' and 'revision' not in cell['cell_id'] else 'PASS',
            'independent_checks':[{'status':'FAIL','error_type':'RuntimeError','message':'PRIVATE_ORACLE_SENTINEL source text'}]}
        with patch('agent_workbench.development.completion._run_canary',side_effect=self.canary),patch('agent_workbench.development.completion.grade_cell',side_effect=grade):
            run_stage(self.batch,self.scope['scope_sha256'],'canary','',model_factory=self.factory)
            run_stage(self.batch,self.scope['scope_sha256'],'development','',model_factory=self.factory)
            revision=run_stage(self.batch,self.scope['scope_sha256'],'revisions','',model_factory=self.factory)
        self.assertEqual(len(revision['records']),1)
        self.assertIn('revision',revision['records'][0]['cell_id'])
        self.assertTrue((self.batch/'model-results/configurable-cap.json').exists())
        preview=(self.batch/'tasks'/revision['records'][0]['cell_id']/'runs/completion-v1/outbound-preview.json').read_text(encoding='utf-8')
        self.assertNotIn('PRIVATE_ORACLE_SENTINEL',preview)

    def test_original_project_drift_invalidates_new_execution_but_allows_closure(self):
        source=self.root/'source';(source/'game-core/combat_core/v2/effects.py').write_bytes(b'VALUE = 9\n')
        git(source,'add','.');git(source,'commit','-qm','new source revision')
        with self.assertRaises(ValueError):verify_campaign(self.batch,self.scope['scope_sha256'])
        self.assertTrue(close_campaign(self.batch,self.scope['scope_sha256'])['closed'])

    def test_missing_usage_and_missing_core_tasks_cannot_enter_rag(self):
        class MissingUsage(LedgerScript):
            def complete(self,messages,decision_id,final_only=False):
                identity=self.budget.reserve({'decision':decision_id});self.budget.finish(identity,'completed',None)
                return AIMessage(content='已交付。')
        def factory(task,cell):return MissingUsage(task,cell,[])
        with patch('agent_workbench.development.completion._run_canary',side_effect=self.canary),patch('agent_workbench.development.completion.grade_cell',return_value={'verdict':'PASS'}):
            run_stage(self.batch,self.scope['scope_sha256'],'canary','',model_factory=factory)
            result=run_stage(self.batch,self.scope['scope_sha256'],'development','',model_factory=factory)
            self.assertEqual(len(result['records']),1)
            with self.assertRaises(ValueError):run_stage(self.batch,self.scope['scope_sha256'],'rag','',model_factory=self.factory)
            with self.assertRaises(ValueError):run_stage(self.batch,self.scope['scope_sha256'],'revisions','',model_factory=self.factory)

    def test_canary_with_unknown_usage_cannot_start_project_calls(self):
        bad={'pass':True,'budget':{'reserved':2,'unknown':1,'known_cost_usd':'0'}}
        with patch('agent_workbench.development.completion._run_canary',return_value=bad):
            run_stage(self.batch,self.scope['scope_sha256'],'canary','',model_factory=self.factory)
        with self.assertRaises(ValueError):run_stage(self.batch,self.scope['scope_sha256'],'development','',model_factory=self.factory)

if __name__=='__main__':unittest.main()
