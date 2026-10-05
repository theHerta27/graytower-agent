import unittest
from agent_workbench.report_view import facts_for_report


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

    def test_higher_and_equal_av_and_duplicate_evidence(self):
        self.assertEqual(facts_for_report(self.report('110'))['comparisons'][0]['direction'], '行动值增加')
        self.assertEqual(facts_for_report(self.report('100'))['comparisons'][0]['direction'], '行动值不变')
        duplicated = self.report()
        duplicated['jobs'].append(duplicated['jobs'][0])
        self.assertEqual(len(facts_for_report(duplicated)['comparisons']), 1)


if __name__ == '__main__':
    unittest.main()
