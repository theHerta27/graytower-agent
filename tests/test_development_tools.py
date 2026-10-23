import json
import unittest
import test_development_checks as fixtures

try:
    from agent_workbench.development.tools import DevelopmentTools, TOOL_SPECS
except ModuleNotFoundError:
    DevelopmentTools = None; TOOL_SPECS = []


class DevelopmentToolTests(unittest.TestCase):
    # Reuse the real Git fixture, not inherited test methods.
    def setUp(self):
        fixtures.DevelopmentCheckTests.setUp(self)
        self.assertIsNotNone(DevelopmentTools)
        self.tools=DevelopmentTools(self.workspace,self.jobs)

    def call(self,name,args,thread='primary',call_id='call-1'):
        result=self.tools.handle('item/tool/call',{'threadId':thread,'callId':call_id,'tool':name,'arguments':args},'primary')
        return result,json.loads(result['contentItems'][0]['text'])

    def test_tools_offer_narrow_files_checks_and_diagnostic_not_shell(self):
        names={t['name'] for t in TOOL_SPECS}
        self.assertEqual(names,{'project_status','read_file','search_code','write_file','replace_text','start_check','read_check','start_diagnostic'})
        for t in TOOL_SPECS:self.assertFalse(t['inputSchema']['additionalProperties'])

    def test_read_search_and_real_edit_then_stale_check(self):
        _,before=self.call('read_file',{'path':'game-core/combat_core/v2/effects.py'})
        _,hits=self.call('search_code',{'query':'VALUE'})
        self.assertEqual(hits[0]['line'],1)
        _,job=self.call('start_check',{'check_set':'effects'})
        self.jobs.complete(job['job_id'],{'exit_code':1,'tests':[{'name':'test','status':'FAIL'}]})
        args={'path':before['path'],'expected_sha256':before['sha256'],'content':'VALUE = 2\n'}
        result,_=self.call('write_file',args,call_id='edit-a')
        self.assertTrue(result['success'])
        _,old=self.call('read_check',{'job_id':job['job_id']})
        self.assertFalse(old['matches_current_candidate'])
        self.assertEqual(old['result']['verdict'],'FAIL')

    def test_repeated_call_id_is_same_edit_and_other_thread_denied(self):
        _,before=self.call('read_file',{'path':'game-core/combat_core/v2/effects.py'})
        args={'path':before['path'],'expected_sha256':before['sha256'],'content':'VALUE = 3\n'}
        first=self.call('write_file',args,call_id='edit-repeat')
        self.assertEqual(first,self.call('write_file',args,call_id='edit-repeat'))
        denied,_=self.call('write_file',args,thread='child')
        self.assertFalse(denied['success'])

    def test_invalid_extra_args_unknown_tools_and_non_tool_methods_fail_closed(self):
        for name,args in [('read_file',{'path':'../key'}),('project_status',{'command':'dir'}),
                          ('start_check',{'check_set':'shell'}),('read_file',{'path':123}),('shell',{})]:
            result,value=self.call(name,args)
            self.assertFalse(result['success']);self.assertIn('error',value)
        self.assertEqual(self.tools.handle('item/commandExecution/requestApproval',{},'primary'),{'decision':'decline'})

    def test_diagnostic_stays_observation_in_tool_output(self):
        _,job=self.call('start_diagnostic',{'python':'print(1)'})
        self.jobs.complete(job['job_id'],{'exit_code':0,'log':'1'})
        _,value=self.call('read_check',{'job_id':job['job_id']})
        self.assertEqual(value['result']['verdict'],'OBSERVATION')


if __name__=='__main__':unittest.main()
