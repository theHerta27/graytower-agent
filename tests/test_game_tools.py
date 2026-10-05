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


class TraceExcerptTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.game = GameTools(self.root)

    def save_trace(self, oversized_final_action=False):
        """Real content-addressed storage/receipt; only battle data is synthetic."""
        snapshot = {'units': {'fixture_unit': {'history': 'large-snapshot-' * 800}}}
        events = []

        def event(kind, action=None, actor=None, payload=None, cause=None):
            event_id = 'event_' + str(len(events) + 1).zfill(6)
            events.append({'event_id': event_id, 'kind': kind, 'actor_id': actor,
                'target_id': 'boss_fixture' if kind == 'direct_damage' else None,
                'action_id': action, 'cause_event_id': cause, 'turn_id': len(events),
                'av': str(len(events) * 10), 'payload': payload or {}, 'state_after': snapshot})
            return event_id

        event('battle_started')
        for number in range(1, 36):
            action = f'action_{number:06d}'
            reason = 'large-reason-' * 1000 if oversized_final_action and number == 35 else 'sp_available'
            decision_id = event('decision', action, 'breaker_fixture',
                {'skill_id': 'breaker_skill', 'reason_code': reason, 'target_ids': ['boss_fixture']})
            event('direct_damage', action, 'breaker_fixture',
                {'skill_id': 'breaker_skill', 'amount': 210, 'hp_loss': 210, 'absorbed': 0,
                 'overkill': 0, 'critical': False, 'damage_type': 'lightning',
                 'debug_state': snapshot}, decision_id)
            event('action_finished', action, 'breaker_fixture', {'skill_id': 'breaker_skill'}, decision_id)
        event('battle_finished', 'action_000035', payload={'outcome': 'win', 'reason': 'boss_dead'})
        trace = {'trace_version': '2.0', 'seed': 47, 'policy_id': 'balanced',
                 'events': events, 'initial_state': snapshot,
                 'result': {'outcome': 'win', 'reason': 'boss_dead', 'final_state': snapshot}}
        ref = self.game.repo.artifacts.put(trace, 'combat-trace-v2')
        ref.update(seed=47, policy='balanced', variant='candidate')
        self.game.store.confirm('a' * 64)
        self.game.store.admit('trace-view', 'a' * 64, 'read saved fixture only', 2)
        self.game.store.run('trace-view', {'seeds': [47], 'policies': ['balanced']}, 2,
                            lambda: {'trace_refs': [ref]})
        return trace, ref

    def test_large_snapshots_do_not_hide_actual_decision_damage_and_finish(self):
        trace, ref = self.save_trace()
        output = self.game.read_trace('trace-view', ref['sha256'])
        self.assertNotIn('state_after', output['excerpt'])
        self.assertNotIn('large-snapshot', output['excerpt'])
        excerpt = json.loads(output['excerpt'])
        selected = {event['event_id']: event for event in excerpt['events']}
        self.assertIn('event_000002', selected, 'the first real decision must survive snapshot compaction')
        self.assertIn('event_000003', selected, 'the damage belonging to that action must survive')
        self.assertIn('event_000107', selected, 'the closing event must not be lost to prefix sampling')
        damage = selected['event_000003']
        self.assertEqual(damage['actor_id'], 'breaker_fixture')
        self.assertEqual(damage['skill_id'], 'breaker_skill')
        self.assertEqual(damage['av'], '20')
        self.assertEqual(damage['action_id'], 'action_000001')
        self.assertEqual(damage['cause_event_id'], 'event_000002')
        self.assertEqual(damage['payload']['amount'], 210)
        self.assertNotIn('debug_state', damage['payload'])
        self.assertEqual(selected['event_000107']['payload']['outcome'], 'win')
        self.assertEqual((excerpt['seed'], excerpt['policy'], excerpt['variant']), (47, 'balanced', 'candidate'))

    def test_selection_is_bounded_complete_json_with_action_groups_and_explicit_limits(self):
        trace, ref = self.save_trace()
        before = self.game.repo.artifacts.path(ref['sha256']).read_bytes()
        output = self.game.read_trace('trace-view', ref['sha256'])
        self.assertIsInstance(output.get('selection'), dict, 'partial trace coverage must be explicit')
        selected = json.loads(output['excerpt'])['events']
        self.assertLessEqual(len(output['excerpt']), 6000)
        self.assertEqual(output['selection']['total_events'], 107)
        self.assertEqual(output['selection']['selected_events'], len(selected))
        self.assertEqual(output['selection']['omitted_events'], 107 - len(selected))
        self.assertTrue(output['selection']['single_variant'])
        self.assertFalse(output['selection']['causal_comparison'])
        self.assertTrue(output['selection']['partial_trace'])
        self.assertTrue(output['truncated'])
        by_action = {}
        for event in selected:
            if event['kind'] in ('decision', 'direct_damage'):
                by_action.setdefault(event['action_id'], set()).add(event['kind'])
        self.assertTrue(by_action)
        self.assertTrue(all(kinds == {'decision', 'direct_damage'} for kinds in by_action.values()))
        self.assertEqual(output['reference'], ref)
        self.assertEqual(output['artifact_hash'], ref['sha256'])
        self.assertEqual(self.game.read_trace('trace-view', ref['sha256']), output)
        self.assertEqual(self.game.repo.artifacts.path(ref['sha256']).read_bytes(), before)
        self.assertEqual(self.game.store.get('trace-view')['charged_battles'], 2)

    def test_compaction_does_not_allow_a_trace_outside_the_request(self):
        trace, ref = self.save_trace()
        foreign = self.game.repo.artifacts.put({**trace, 'seed': 99}, 'combat-trace-v2')
        with self.assertRaisesRegex(ValueError, 'outside this request'):
            self.game.read_trace('trace-view', foreign['sha256'])

    def test_oversized_final_action_does_not_remove_the_battle_outcome(self):
        trace, ref = self.save_trace(oversized_final_action=True)
        output = self.game.read_trace('trace-view', ref['sha256'])
        selected = {event['event_id'] for event in json.loads(output['excerpt'])['events']}
        self.assertIn('event_000107', selected)
        self.assertIn('event_000002', selected)
        self.assertNotIn('event_000104', selected)
        self.assertNotIn('event_000105', selected)
        self.assertLessEqual(len(output['excerpt']), 6000)

    @unittest.skipUnless((DEMO_ROOT.parent / 'config-development-v1/dev-c01/jobs.sqlite').is_file(),
                         'requires saved development evidence; never starts battles')
    async def test_saved_development_trace_compacts_over_mcp_without_mutating_evidence(self):
        source_root = DEMO_ROOT.parent / 'config-development-v1/dev-c01'
        shutil.copytree(source_root / 'artifacts', self.root / 'artifacts', dirs_exist_ok=True)
        with closing(sqlite3.connect((source_root / 'jobs.sqlite').as_uri() + '?mode=ro', uri=True)) as source:
            with closing(sqlite3.connect(self.root / 'jobs.sqlite')) as target:
                source.backup(target)
        original = self.game.store.receipts('dev-c01-qa')
        ref = next(ref for job in original for ref in job['result']['trace_refs']
                   if ref['seed'] == 7 and ref['variant'] == 'candidate')
        before = self.game.repo.artifacts.path(ref['sha256']).read_bytes()
        charged = self.game.store.get('dev-c01-qa')['charged_battles']
        async with connect_tools(self.root) as client:
            output = await client.call('read_trace', {'request_id': 'dev-c01-qa', 'artifact_hash': ref['sha256']})
        self.assertNotIn('state_after', output['excerpt'])
        excerpt = json.loads(output['excerpt'])
        selected = {event['event_id']: event for event in excerpt['events']}
        self.assertEqual(selected['event_000003']['payload']['skill_id'], 'breaker_skill')
        self.assertEqual(selected['event_000006']['payload']['amount'], 210)
        self.assertEqual(selected['event_000974']['payload']['outcome'], 'win')
        self.assertEqual(output['selection']['total_events'], 974)
        self.assertEqual(excerpt['variant'], 'candidate')
        self.assertLessEqual(len(output['excerpt']), 6000)
        self.assertEqual(self.game.repo.artifacts.path(ref['sha256']).read_bytes(), before)
        self.assertEqual(self.game.store.receipts('dev-c01-qa'), original)
        self.assertEqual(self.game.store.get('dev-c01-qa')['charged_battles'], charged)


if __name__ == '__main__':
    unittest.main()
