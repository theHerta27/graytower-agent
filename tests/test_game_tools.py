import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from contextlib import closing
import hashlib
import json
import shutil
import sqlite3

from agent_workbench.game_tools import GameTools, connect_tools
from agent_workbench.domain._shared import digest

DEMO_ROOT = Path(__file__).resolve().parents[1] / 'local-data/v1-demo'


def result_fixture():
    """Complete protocol fixture. No simulation or model effectiveness evidence."""
    plan = {'manifest_hash': 'a'*64, 'seeds': [7], 'policies': ['balanced']}
    refs = [{'artifact_id': char*64, 'sha256': char*64, 'schema': 'combat-trace-v2',
             'seed': 7, 'policy': 'balanced', 'variant': label} for label, char in [('baseline', 'b'), ('candidate', 'c')]]
    row = {'seed': 7, 'policy': 'balanced'}
    for ref in refs:
        row[ref['variant']] = {'seed': 7, 'strategy': 'balanced', 'outcome': 'win',
                              'elapsed_av': '100', 'trace_sha256': ref['sha256']}
    return {'manifest_hash': 'a'*64, 'identity': {**plan, 'execution_hash': digest(plan)},
            'completed_battles': 2, 'rows': [row], 'trace_refs': refs}


class GameToolTests(unittest.IsolatedAsyncioTestCase):
    @unittest.skipUnless((DEMO_ROOT / 'jobs.sqlite').is_file(), 'requires saved real demo receipt; never starts battles')
    async def test_saved_real_receipt_and_trace_return_over_mcp_without_new_battles(self):
        """Replay a read-only snapshot of existing real evidence, never rerun the demo."""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            shutil.copytree(DEMO_ROOT / 'artifacts', root / 'artifacts')
            # SQLite backup gives one consistent read-only snapshot even while
            # the live service owns the source DB; no live records are changed.
            with closing(sqlite3.connect((DEMO_ROOT / 'jobs.sqlite').as_uri() + '?mode=ro', uri=True)) as source:
                with closing(sqlite3.connect(root / 'jobs.sqlite')) as target:
                    source.backup(target)
            game = GameTools(root)
            with closing(game.store.connect()) as db:
                row = db.execute("SELECT request_id,receipt FROM jobs WHERE state='completed' ORDER BY id LIMIT 1").fetchone()
            self.assertIsNotNone(row, 'saved demo must contain its completed real battle receipt')
            expected = json.loads(row['receipt'])
            self.assertTrue(expected['result']['metrics'])
            charged = game.store.get(row['request_id'])['charged_battles']
            files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (root / 'artifacts').glob('*.json')}
            async with connect_tools(root) as client:
                observed = await client.call('run_simulation', {'request_id': row['request_id'], **expected['args']})
                self.assertEqual(observed, expected)
                self.assertTrue(observed['result']['metrics'])
                trace_hash = observed['result']['trace_refs'][0]['sha256']
                trace = await client.call('read_trace', {'request_id': row['request_id'], 'artifact_hash': trace_hash})
                self.assertEqual(trace['artifact_hash'], trace_hash)
                self.assertTrue(trace['excerpt'])
                self.assertEqual(trace['reference']['sha256'], trace_hash)
            self.assertEqual(game.store.get(row['request_id'])['charged_battles'], charged)
            self.assertEqual(game.store.receipts(row['request_id'])[0], expected)
            self.assertEqual(files, {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (root / 'artifacts').glob('*.json')})
            logs = [json.loads(line) for line in (root / 'tool-calls.jsonl').read_text(encoding='utf-8').splitlines()]
            self.assertEqual([line['tool'] for line in logs], ['run_simulation', 'read_trace'])
            self.assertEqual(logs[0]['arguments'], {'request_id': row['request_id'], **expected['args']})
            self.assertNotIn('not JSON serializable', (root / 'mcp-stderr.log').read_text(encoding='utf-8'))

    async def test_invalid_rows_or_trace_binding_never_become_completed_receipts(self):
        mutations = {
            'foreign_row': lambda r: r['rows'][0].update(seed=11),
            'duplicate_row': lambda r: r['rows'].append(deepcopy(r['rows'][0])),
            'foreign_summary': lambda r: r['rows'][0]['candidate'].update(seed=11),
            'duplicate_trace': lambda r: r['trace_refs'].__setitem__(1, deepcopy(r['trace_refs'][0])),
            'wrong_variant': lambda r: r['trace_refs'][1].update(variant='baseline'),
            'wrong_trace_hash': lambda r: r['rows'][0]['candidate'].update(trace_sha256='d'*64),
            'wrong_ref_hash': lambda r: r['trace_refs'][1].update(artifact_id='d'*64),
            'wrong_execution': lambda r: r['identity'].update(execution_hash='d'*64),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as folder:
                game = GameTools(folder)
                game.store.confirm('a'*64)
                game.store.admit('fixture', 'a'*64, 'fixture', 2)
                value = result_fixture()
                mutate(value)
                game.repo.verify = lambda *args: value
                with self.assertRaises(ValueError):
                    game.run_simulation('fixture', [7], ['balanced'])
                self.assertEqual(game.store.receipts('fixture'), [])

    async def test_complete_fixture_result_reuses_same_receipt_without_execution(self):
        with tempfile.TemporaryDirectory() as folder:
            game = GameTools(folder)
            game.store.confirm('a'*64)
            game.store.admit('fixture', 'a'*64, 'fixture', 2)
            game.repo.verify = lambda *args: result_fixture()
            first = game.run_simulation('fixture', [7], ['balanced'])
            game.repo.verify = lambda *args: self.fail('receipt reuse must not execute')
            self.assertEqual(game.run_simulation('fixture', [7], ['balanced']), first)
            self.assertEqual(game.store.get('fixture')['charged_battles'], 2)

    async def test_real_mcp_candidate_read_and_denied_unapproved_simulation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            tools = GameTools(root)
            candidate = tools.repo.create('击破手战技倍率改为1.7', [{'path': 'skills.breaker_skill.multiplier', 'value': 1.7}])
            async with connect_tools(root) as client:
                inspected = await client.call('inspect_candidate', {'manifest_hash': candidate['manifest_hash']})
                self.assertEqual(inspected['manifest_hash'], candidate['manifest_hash'])
                self.assertEqual(inspected['diff'], candidate['diff'])
                with self.assertRaises(ValueError):
                    await client.call('run_simulation', {'request_id': 'unapproved', 'seeds': [7], 'policies': ['balanced']})
                with self.assertRaises(ValueError):
                    await client.call('read_trace', {'request_id': 'unapproved', 'artifact_hash': 'b'*64})

    async def test_mcp_rejects_boolean_and_string_seed_before_claiming_job(self):
        with tempfile.TemporaryDirectory() as folder:
            game = GameTools(folder)
            game.store.confirm('a'*64)
            game.store.admit('strict-seed', 'a'*64, 'fixture', 2)
            async with connect_tools(folder) as client:
                for seed in (True, '7'):
                    with self.subTest(seed=seed), self.assertRaises(ValueError):
                        await client.call('run_simulation', {'request_id': 'strict-seed', 'seeds': [seed], 'policies': ['balanced']})
            self.assertEqual(game.store.get('strict-seed')['charged_battles'], 0)


if __name__ == '__main__':
    unittest.main()
