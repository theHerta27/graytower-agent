"""Business-loop tests: scripted model only replaces the external model boundary."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
import test_development_checks as fixtures

try:
    from agent_workbench.development.agent import run_agent
    from agent_workbench.development.context import bounded_messages
except ImportError:
    run_agent = bounded_messages = None


class ScriptModel:
    def __init__(self, steps, limit=20):
        self.steps = iter(steps); self.limit = limit; self.saved = {}; self.inputs = []

    def remaining_calls(self):
        return self.limit - len(self.saved)

    def complete(self, messages, decision_id, final_only=False):
        if decision_id not in self.saved:
            self.inputs.append((messages, final_only))
            step = next(self.steps)
            self.saved[decision_id] = step(messages) if callable(step) else step
        return self.saved[decision_id]

    def summary(self):
        return {'reserved': len(self.saved), 'known_cost_usd': '0', 'max_calls': self.limit}


def call(name, args, identity):
    return AIMessage(content='', tool_calls=[{'name': name, 'args': args, 'id': identity}])


class DevelopmentAgentTests(unittest.TestCase):
    def setUp(self):
        fixtures.DevelopmentCheckTests.setUp(self)
        self.assertIsNotNone(run_agent, 'LangGraph研发主循环尚未实现')
        self.control = self.root/'graph-run'

    def run_graph(self, model, **kwargs):
        return run_agent(workspace=self.workspace, jobs=self.jobs, control=self.control,
                         model=model, request='将VALUE调整为2，并检查规则。', wait_seconds=0, **kwargs)

    def test_real_candidate_edit_check_and_final_handoff(self):
        path = 'game-core/combat_core/v2/effects.py'
        def edit(messages):
            value = json.loads(next(m.content for m in reversed(messages) if isinstance(m, ToolMessage)))
            return call('replace_text', {'path': path, 'expected_sha256': value['sha256'],
                'old_text': 'VALUE = 1', 'new_text': 'VALUE = 2'}, 'edit-1')
        def launcher(request):
            self.jobs.complete(request['job_id'], {'exit_code': 0, 'tests': [{'name': 'value_two', 'status': 'PASS'}]})
        self.jobs.launcher = launcher
        model = ScriptModel([call('read_file', {'path': path}, 'read-1'), edit,
            call('start_check', {'check_set': 'rules'}, 'check-1'), AIMessage(content='已将VALUE改为2；完整规则检查通过。')])
        result = self.run_graph(model)
        self.assertEqual(result['status'], 'completed')
        self.assertIn('+VALUE = 2', self.workspace.inspect()['patch'])
        self.assertEqual((self.root/'source'/path).read_text(), 'VALUE = 1\n')
        self.assertEqual(self.jobs.list(self.workspace)[0]['result']['verdict'], 'PASS')
        self.assertIn('VALUE', result['summary'])

    def test_clarification_resumes_same_graph_without_repeating_question_call(self):
        model = ScriptModel([call('ask_user', {'question': '上限应为多少？'}, 'ask-1'),
                             AIMessage(content='收到，上限为7；目前仅完成澄清，尚未修改。')])
        first = self.run_graph(model)
        self.assertEqual(first['status'], 'waiting_user')
        self.assertEqual(first['question'], '上限应为多少？')
        result = self.run_graph(model, resume=True, answer='上限为7')
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(len(model.saved), 2)
        self.assertTrue(any('上限为7' in str(m.content) for m in model.inputs[-1][0]))

    def test_missing_resume_answer_does_not_poison_saved_question(self):
        model=ScriptModel([call('ask_user',{'question':'目标是多少？'},'ask'),AIMessage(content='已收到7。')])
        self.run_graph(model)
        with self.assertRaises(ValueError):self.run_graph(model,resume=True)
        self.assertEqual(self.run_graph(model,resume=True,answer='7')['status'],'completed')

    def test_invalid_question_arguments_can_be_corrected_by_agent(self):
        model=ScriptModel([call('ask_user',{},'bad-ask'),AIMessage(content='问题参数无效，未修改候选。')])
        self.assertEqual(self.run_graph(model)['status'],'completed')

    def test_completed_job_after_pause_is_read_without_new_launch_or_paid_poll(self):
        model = ScriptModel([call('start_check', {'check_set': 'rules'}, 'job-1'), AIMessage(content='检查已完成。')])
        first = self.run_graph(model)
        self.assertEqual(first['status'], 'waiting_checks')
        self.assertEqual(len(model.saved), 1)
        job = self.jobs.list()[0]
        self.jobs.complete(job['job_id'], {'exit_code': 0, 'tests': [{'name': 'rule', 'status': 'PASS'}]})
        result = self.run_graph(model, resume=True)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(len(self.launched), 1)
        self.assertTrue(any('PASS' in str(m.content) for m in model.inputs[-1][0]))

    def test_last_call_is_reserved_for_final_response(self):
        model = ScriptModel([AIMessage(content='额度即将用尽，本次只完成调查，未修改。')], limit=1)
        result = self.run_graph(model)
        self.assertTrue(model.inputs[0][1])
        self.assertIn('未修改', result['summary'])

    def test_raw_tool_envelope_is_partial_and_never_dispatched(self):
        model=ScriptModel([AIMessage(content='<｜｜DSML｜｜ calls>\n<｜｜DSML｜｜ invoke name="write_file">\n</｜｜DSML｜｜ calls>')],limit=1)
        result=self.run_graph(model)
        self.assertEqual(result['status'],'partial')
        self.assertEqual(result['reason'],'model_protocol')
        self.assertNotIn('<｜｜DSML',result['summary'])
        self.assertFalse(self.workspace.inspect()['patch'])
        self.assertEqual(len(model.saved),1)

    def test_each_decision_receives_remaining_allowance_without_forcing_an_edit(self):
        model=ScriptModel([call('read_file',{'path':'game-core/combat_core/v2/effects.py'},'read'),AIMessage(content='完成只读核查，不需要修改。')],limit=4)
        result=self.run_graph(model)
        self.assertEqual(result['status'],'completed')
        self.assertIn('剩余可用调用：4',model.inputs[0][0][0].content)
        self.assertIn('剩余可用调用：3',model.inputs[1][0][0].content)

    def test_crash_after_edit_before_checkpoint_reuses_edit_receipt(self):
        path = 'game-core/combat_core/v2/effects.py'
        before = self.workspace.read_file(path)
        model = ScriptModel([call('replace_text', {'path': path, 'expected_sha256': before['sha256'],
            'old_text': 'VALUE = 1', 'new_text': 'VALUE = 2'}, 'edit-once'), AIMessage(content='修复完成。')])
        original = self.workspace.replace_text
        def crashed(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError('simulated crash after physical write')
        with patch.object(self.workspace, 'replace_text', side_effect=crashed), self.assertRaises(RuntimeError):
            self.run_graph(model)
        result = self.run_graph(model, resume=True)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(self.workspace.read_file(path)['text'], 'VALUE = 2\n')
        self.assertEqual(len(model.saved), 2)

    def test_saved_model_decision_is_reused_when_budget_changed_before_checkpoint(self):
        class CrashModel(ScriptModel):
            crash = True
            def complete(self, messages, decision_id, final_only=False):
                if decision_id in self.saved:
                    self_outer.assertFalse(final_only, 'replay must use the original decision request')
                result = super().complete(messages, decision_id, final_only)
                if self.crash:
                    self.crash = False
                    raise RuntimeError('crash after model response was saved')
                return result
        self_outer = self
        model = CrashModel([AIMessage(content='调查完成，未修改。')], limit=2)
        with self.assertRaises(RuntimeError):
            self.run_graph(model)
        result = self.run_graph(model, resume=True)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(len(model.saved), 1)

    def test_context_retains_current_tool_pair_and_fits_utf8_budget(self):
        history = [HumanMessage(content='调查资源规则')]
        for index in range(12):
            history += [call('read_file', {'path': 'effects.py'}, str(index)),
                        ToolMessage(content='护盾数值'*4000, tool_call_id=str(index), name='read_file')]
        actual = bounded_messages(history, instructions='遵循权限边界', memories=[], max_bytes=14000)
        size = len(json.dumps([m.model_dump() for m in actual], ensure_ascii=False).encode())
        self.assertLessEqual(size, 14000)
        self.assertIsInstance(actual[-1], ToolMessage)
        self.assertEqual(actual[-1].tool_call_id, '11')
        self.assertIn('11', [c['id'] for m in actual if isinstance(m, AIMessage) for c in m.tool_calls])


if __name__ == '__main__':
    unittest.main()
