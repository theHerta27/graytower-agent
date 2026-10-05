"""Local receipts must prevent unconfirmed, duplicate and ambiguous work."""
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from agent_workbench.jobs import JobStore, RecoveryRequired


class LocalJobTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = JobStore(Path(self.tmp.name))

    def test_admission_requires_exact_confirmed_manifest_and_conflict_is_rejected(self):
        with self.assertRaises(ValueError):
            self.store.admit('qa-1', 'a'*64, '检查变快没有', 4)
        self.store.confirm('a'*64)
        first = self.store.admit('qa-1', 'a'*64, '检查变快没有', 4)
        self.assertEqual(first['status'], 'new')
        with self.assertRaises(ValueError):
            self.store.admit('qa-1', 'a'*64, 'different goal', 4)

    def test_completed_job_reused_after_store_reopen_before_graph_checkpoint(self):
        self.store.confirm('a'*64)
        self.store.admit('qa-1', 'a'*64, 'goal', 4)
        args = {'seeds': [7, 11], 'policies': ['balanced']}
        result = self.store.run('qa-1', args, 4, lambda: {'n': 4, 'verdict': 'INCONCLUSIVE'})
        reopened = JobStore(Path(self.tmp.name))
        def forbidden():
            self.fail('receipt recovery must not execute battles again')
        self.assertEqual(reopened.run('qa-1', args, 4, forbidden), result)
        self.assertEqual(reopened.get('qa-1')['charged_battles'], 4)

    def test_unknown_job_is_not_reexecuted_or_recharged(self):
        self.store.confirm('a'*64)
        self.store.admit('qa-1', 'a'*64, 'goal', 4)
        def crash():
            raise SystemExit('worker died before receipt')
        with self.assertRaises(SystemExit):
            self.store.run('qa-1', {'seeds': [7], 'policies': ['balanced']}, 2, crash)
        with self.assertRaises(RecoveryRequired):
            self.store.run('qa-1', {'seeds': [7], 'policies': ['balanced']}, 2, lambda: {})
        self.assertEqual(self.store.get('qa-1')['charged_battles'], 2)

    def test_completed_request_replay_and_budget_are_durable(self):
        self.store.confirm('a'*64)
        self.store.admit('qa-1', 'a'*64, 'goal', 2)
        self.store.run('qa-1', {'x': 1}, 2, lambda: {'n': 2})
        with self.assertRaises(ValueError):
            self.store.run('qa-1', {'x': 2}, 2, lambda: {})
        self.store.complete('qa-1', {'verdict': 'INCONCLUSIVE', 'manifest_hash': 'a'*64})
        replay = self.store.admit('qa-1', 'a'*64, 'goal', 2)
        self.assertEqual(replay['report']['verdict'], 'INCONCLUSIVE')
        self.assertEqual(replay['charged_battles'], 2)

    def test_foreign_self_consistent_receipt_cannot_be_replayed_or_enumerated(self):
        """A fixture swaps valid bytes and their hash, modeling a receipt routing bug."""
        args = {'seeds': [7], 'policies': ['balanced']}
        receipts = []
        for request_id, manifest in [('qa-1', 'a'*64), ('qa-2', 'b'*64)]:
            self.store.confirm(manifest)
            self.store.admit(request_id, manifest, 'goal', 2)
            receipts.append(self.store.run(request_id, args, 2, lambda: {'fixture': True}))
        with closing(self.store.connect()) as db, db:
            other = db.execute('SELECT receipt,receipt_hash FROM jobs WHERE id=?', (receipts[1]['job_id'],)).fetchone()
            db.execute('UPDATE jobs SET receipt=?,receipt_hash=? WHERE id=?', (*other, receipts[0]['job_id']))
        with self.assertRaises(ValueError):
            self.store.run('qa-1', args, 2, lambda: self.fail('must not execute'))
        with self.assertRaises(ValueError):
            self.store.receipts('qa-1')

    def test_existing_job_cannot_change_units_on_replay(self):
        self.store.confirm('a'*64)
        self.store.admit('qa-1', 'a'*64, 'goal', 4)
        self.store.run('qa-1', {'seeds': [7]}, 2, lambda: {'fixture': True})
        for units in (4, True, 0):
            with self.subTest(units=units), self.assertRaises(ValueError):
                self.store.run('qa-1', {'seeds': [7]}, units, lambda: self.fail('must not execute'))
        self.assertEqual(self.store.get('qa-1')['charged_battles'], 2)

    def test_unknown_job_prevents_new_args_from_bypassing_recovery(self):
        self.store.confirm('a'*64)
        self.store.admit('qa-1', 'a'*64, 'goal', 4)
        def unknown():
            raise SystemExit('fixture physical exit')
        with self.assertRaises(SystemExit):
            self.store.run('qa-1', {'seeds': [7]}, 2, unknown)
        reopened = JobStore(Path(self.tmp.name))
        with self.assertRaises(RecoveryRequired):
            reopened.run('qa-1', {'seeds': [11]}, 2, lambda: self.fail('unknown work must be reconciled first'))
        self.assertEqual(reopened.get('qa-1')['charged_battles'], 2)

    def test_present_game_result_identity_and_units_must_match_before_receipt(self):
        self.store.confirm('a'*64)
        cases = [{'manifest_hash': 'b'*64}, {'identity': {'manifest_hash': 'b'*64}},
                 {'identity': {}}, {'completed_battles': 200}, {'completed_battles': True}]
        for i, result in enumerate(cases):
            request_id = f'qa-{i}'
            self.store.admit(request_id, 'a'*64, 'goal', 2)
            with self.subTest(result=result), self.assertRaises(ValueError):
                self.store.run(request_id, {'seeds': [7]}, 2, lambda result=result: result)
            self.assertEqual(self.store.receipts(request_id), [])
            self.assertEqual(self.store.get(request_id)['charged_battles'], 2)

    def test_v1_cannot_promote_descriptive_execution_to_pass(self):
        self.store.confirm('a'*64)
        self.store.admit('qa-1', 'a'*64, 'goal', 2)
        with self.assertRaises(ValueError):
            self.store.complete('qa-1', {'manifest_hash': 'a'*64, 'verdict': 'PASS'})
        self.assertIsNone(self.store.get('qa-1')['report'])


if __name__ == '__main__':
    unittest.main()
