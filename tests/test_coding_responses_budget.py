from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

from agent_workbench.coding.responses_transport import CallBudget


class ResponsesBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.grant = {'max_calls': 4, 'max_input_bytes': 70000, 'max_output_tokens': 2048,
                      'cost_cap_usd': '0.11', 'authorization_sha256': 'a'*64,
                      'input_usd_per_million': '0.30', 'cached_input_usd_per_million': '0.006',
                      'output_usd_per_million': '1.20'}

    def test_parallel_reservations_share_cap_and_restart_does_not_reset(self):
        budget = CallBudget(self.root, self.grant)
        def reserve(_):
            try:
                return budget.reserve({'model': 'deepseek-flash', 'input': 'hello'})
            except ValueError:
                return None
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(reserve, range(8)))
        self.assertEqual(len([r for r in results if r is not None]), 4)
        with self.assertRaises(ValueError):
            CallBudget(self.root, self.grant).reserve({'input':'hello'})
        self.assertEqual(budget.summary()['unknown'], 4)

    def test_changed_grant_rejected_and_failure_remains_charged(self):
        budget = CallBudget(self.root, self.grant)
        call = budget.reserve({'input': 'hello'})
        budget.finish(call, 'failed', None)
        with self.assertRaises(ValueError):
            CallBudget(self.root, self.grant | {'max_calls': 8})
        self.assertEqual(budget.summary()['reserved'], 1)
        self.assertEqual(budget.summary()['failed'], 1)

    def test_unknown_usage_reserves_worst_case_and_known_usage_is_recorded(self):
        budget = CallBudget(self.root, self.grant)
        call = budget.reserve({'input':'hello'})
        budget.finish(call, 'completed', {'input_tokens': 100, 'output_tokens': 10,
                                        'input_tokens_details': {'cached_tokens': 40}})
        self.assertEqual(Decimal(budget.summary()['known_cost_usd']), Decimal('0.00003024'))
        self.assertEqual(budget.summary()['unknown'], 0)
        with self.assertRaises(ValueError):
            budget.finish(call, 'failed', None)

    def test_oversized_payload_and_underfunded_grant_rejected(self):
        budget = CallBudget(self.root, self.grant)
        with self.assertRaises(ValueError):
            budget.reserve({'input':'x'*70000})
        self.assertEqual(budget.summary()['reserved'], 0)
        with self.assertRaises(ValueError):
            CallBudget(self.root / 'bad', self.grant | {'cost_cap_usd':'0.001'})


if __name__ == '__main__':
    unittest.main()
