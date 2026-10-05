import unittest
from agent_workbench.report_view import facts_for_report, render_report


class ReportViewTests(unittest.TestCase):
    def report(self, candidate_av='90', outcome='win'):
        return {'verdict': 'INCONCLUSIVE', 'errors': [], 'jobs': [{'result': {'rows': [
            {'seed': 7, 'policy': 'balanced', 'baseline': {'outcome': 'win', 'elapsed_av': '100'},
             'candidate': {'outcome': outcome, 'elapsed_av': candidate_av}}]}}]}

    def test_negative_delta_is_less_av_even_for_fractional_values(self):
        report = self.report('100/7')
        result = facts_for_report(report)
        self.assertEqual(result['comparisons'][0]['delta_av'], '-600/7')
        self.assertEqual(result['comparisons'][0]['direction'], '行动值减少')
        self.assertEqual(result['comparisons'][0]['candidate_av'], '100/7')

    def test_loss_is_not_reported_as_a_faster_win(self):
        result = facts_for_report(self.report('1', 'loss'))
        self.assertEqual(result['comparisons'], [])
        self.assertEqual(result['transitions'], {'balanced:win->loss': 1})

    def test_render_displays_regression_and_timeouts_when_no_av_pair_exists(self):
        report = self.report('1', 'loss')
        row = {'seed': 11, 'policy': 'balanced',
               'baseline': {'outcome': 'win', 'elapsed_av': '100'},
               'candidate': {'outcome': 'timeout', 'elapsed_av': '500'}}
        report['jobs'][0]['result']['rows'].append(row)
        text = render_report(report)
        self.assertIn('胜利 → 失败：1 对', text)
        self.assertIn('胜利 → 超时：1 对', text)
        self.assertIn('没有双方都获胜的配对', text)
        self.assertNotIn('行动值减少（', text)

    def test_model_error_without_receipt_is_not_reported_as_a_tool_receipt(self):
        text = render_report({'verdict': 'INCONCLUSIVE', 'errors': ['RuntimeError: model call failed'], 'jobs': []})
        self.assertIn('运行错误', text)
        self.assertIn('没有已完成的战斗收据', text)
        self.assertNotIn('工具错误', text)
        self.assertNotIn('展示已保存', text)

    def test_budget_stop_is_visible_without_inventing_a_provider_error(self):
        report = self.report()
        report['stop_reason'] = 'model_budget_exhausted'
        text = render_report(report)
        self.assertIn('模型调用额度已用尽', text)
        self.assertIn('保留已有证据', text)
        self.assertNotIn('运行错误', text)

    def test_higher_and_equal_av_and_duplicate_evidence(self):
        self.assertEqual(facts_for_report(self.report('110'))['comparisons'][0]['direction'], '行动值增加')
        self.assertEqual(facts_for_report(self.report('100'))['comparisons'][0]['direction'], '行动值不变')
        duplicated = self.report()
        duplicated['jobs'].append(duplicated['jobs'][0])
        self.assertEqual(len(facts_for_report(duplicated)['comparisons']), 1)


if __name__ == '__main__':
    unittest.main()
