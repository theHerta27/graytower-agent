import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from agent_workbench.coding.service import CodingAuthorization,CodingService
from agent_workbench.code_candidates import runtime_workspace, TARGET
from agent_workbench.code_tools import CodeCatalog

class PythonCodingServiceTests(unittest.TestCase):
    def test_formal_service_freezes_python_candidate_and_receipt_only_recovery(self):
        with tempfile.TemporaryDirectory(dir='D:/Desktop') as directory:
            root=Path(directory);data=root/'data'
            payload={'operation_id':'python1','request':'技能点应最多为5点，修复资源上限问题。','mode':'single'}
            scope=root/'scope.json'
            scope.write_text(json.dumps({'schema':'coding-service-grant-v1',
                'tasks':{'python1':{'request':payload['request'],'mode':'single'}},
                'case_profiles':{'python1':'skill-points-python-v1'},
                'coding_grant':{'max_calls':2,'max_input_bytes':10000,'max_output_tokens':100,
                    'cost_cap_usd':'0.1','input_usd_per_million':'0.30','cached_input_usd_per_million':'0.006','output_usd_per_million':'1.20'}}),encoding='utf-8')
            auth=CodingAuthorization(scope,hashlib.sha256(scope.read_bytes()).hexdigest(),root/'ledger')
            count=[]
            def runner(**args):
                count.append(1)
                case=runtime_workspace(args['data'],args['workspace'],args['preparation'])
                target=args['workspace']/TARGET
                target.write_bytes(target.read_bytes().replace(b'state.skill_points=min(4,before+gained-spent)',b'state.skill_points=min(5,before+gained-spent)'))
                after=case.inspect_changes()
                receipt={'schema':'coding-runtime-run-v1','mode':'single','status':'completed','sdk':'0.160.0','runtime':'0.160.0',
                    'thread_id':'fixture','review_tree_hash':after['after_tree_hash'],'after_tree_hash':after['after_tree_hash'],
                    'review_file_sha256':after['after_hash'],'after_sha256':after['after_hash'],
                    'task_turn':{'status':'completed','items':[]},'review_turn':{'status':'completed','items':[]}}
                args['control'].mkdir(parents=True)
                (args['control']/'result.json').write_text(json.dumps(receipt),encoding='utf-8')
                return receipt
            service=CodingService(data,authorization=auth,sender=lambda x:b'',runner=runner,runtime_python=Path('fixture'))
            service.admit(payload)
            result=service.execute('python1')
            self.assertEqual(result['status'],'completed',result)
            candidate=result['result']['candidate']['manifest_hash']
            self.assertEqual(CodeCatalog(data).view(candidate)['kind'],'code')
            self.assertEqual(service.recover('python1'),result)
            self.assertEqual(len(count),1)
            from agent_workbench.code_candidates import CodeWorkspace
            details=service.store.coding_details('python1')
            CodeWorkspace(data/'coding-runs/python1/python-data/control',data/'coding-runs/python1/workspace',details['preparation']).remove()
