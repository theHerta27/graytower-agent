"""NPC graph integration with the real local world domain; no paid model."""
import importlib.util
import json
from pathlib import Path
import sys

import unittest
from tempfile import TemporaryDirectory
from contextlib import contextmanager

GAME = Path(__file__).resolve().parents[2] / 'graytower-game'
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
sys.path.insert(0, str(GAME / 'game-core'))


@contextmanager
def setup(tmp_path):
    from starlette.testclient import TestClient
    from combat_core.host import create_app
    from agent_workbench.npc.contracts import Scope
    from agent_workbench.npc.world_client import WorldClient, PlayerWorldClient
    from agent_workbench.npc.service import NPCService
    with TestClient(create_app(tmp_path / 'world'), base_url='http://127.0.0.1:8780') as http:
        player = http.post('/world/saves', json={'request_id': 'create', 'save_id': 's'}).json()['player_session']
        ph = {'X-World-Session': player}
        tokens = {npc: http.post('/world/npc-session', headers=ph, json={'npc_id': npc}).json()['npc_session'] for npc in ('lan', 'li')}
        def make(npc='lan', model=None, **kw):
            world = WorldClient(Scope(save_id='s', branch_id='main', npc_id=npc), tokens[npc], client=http)
            return NPCService(tmp_path / 'npc', world, model=model, **kw)
        yield make, PlayerWorldClient('s', 'main', player, client=http), http, ph


def raises(kind, match):
    return unittest.TestCase().assertRaisesRegex(kind, match)


class NPCWorkflowTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory(prefix="npc-test-")
        self.addCleanup(temp.cleanup)
        context = setup(Path(temp.name))
        self.fixture = context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)

    def test_offline_choice_is_not_approval_and_completed_reply_retries_are_stable(self):
        setup = self.fixture
        make, player, http, ph = setup
        service = make()
        result = service.turn('one', '我想准备支援')
        assert result['status'] == 'awaiting_choice' and result['model_mode'] == 'offline'
        assert len(result['offer']['choices']) == 2
        assert http.get('/world/context', headers=ph).json()['revision'] == 0
        done = service.choose('one', 'shield_start', result['offer']['offer_hash'], player)
        assert done['status'] == 'completed' and '120' in done['reply']['text']
        assert done['receipt']['support']['choice'] == 'shield_start'
        assert make().turn('one', '我想准备支援') == done
        assert make().choose('one', 'shield_start', result['offer']['offer_hash'], player) == done
        assert http.get('/world/context', headers=ph).json()['revision'] == 1


    def test_turn_conflict_busy_scope_and_memory_visibility(self):
        setup = self.fixture
        from agent_workbench.npc.contracts import NPCError
        make, player, http, ph = setup
        http.post('/world/tell', headers=ph, json={'action_id': 'tell', 'expected_revision': 0, 'npc_id': 'lan', 'text': '我赢了，这是自述'})
        lan, li = make(), make('li')
        first = lan.turn('one', '支援')
        with raises(NPCError, match='input_conflict'):
            lan.turn('one', 'different')
        with raises(NPCError, match='scope_busy'):
            lan.turn('two', 'another')
        other = li.turn('one', '听说我赢了吗')
        assert other['status'] == 'completed'
        assert len(lan.memories()) == 1 and lan.memories()[0]['is_world_fact'] is False
        assert li.memories() == []
        assert '120' not in other['reply']['text']
        assert other['turn_id'] != first['turn_id']


    def test_stale_choice_and_cross_player_scope_cannot_commit(self):
        setup = self.fixture
        from agent_workbench.npc.contracts import NPCError
        from agent_workbench.npc.world_client import PlayerWorldClient
        make, player, http, ph = setup
        service = make(); first = service.turn('one', '支援')
        other = http.post('/world/saves', json={'request_id':'create','save_id':'other'}).json()
        wrong = PlayerWorldClient('other', 'main', other['player_session'], client=http)
        with raises(NPCError, match='scope_mismatch'):
            service.choose('one','shield_start',first['offer']['offer_hash'],wrong)
        http.post('/world/tell', headers=ph, json={'action_id':'talk','expected_revision':0,'npc_id':'lan','text':'等一下'})
        result = service.choose('one','shield_start',first['offer']['offer_hash'],player)
        assert result['status'] == 'rejected'
        assert http.get('/world/context', headers=ph).json()['revision'] == 1


    def test_world_committed_lost_response_reconciles_without_duplicate_reward(self):
        setup = self.fixture
        from agent_workbench.npc.contracts import NPCError
        make, player, http, ph = setup
        service = make(); first = service.turn('one', '支援')
        original = service.world.commit
        def drop(payload):
            original(payload)
            raise NPCError('world_unavailable', 'fixture lost response')
        service.world.commit = drop
        pending = service.choose('one','sp_supply',first['offer']['offer_hash'],player)
        assert pending['status'] == 'reconciling'
        done = make().turn('one', '支援')
        assert done['status'] == 'completed'
        assert done['receipt']['support']['choice'] == 'sp_supply'
        assert http.get('/world/context', headers=ph).json()['revision'] == 1
        assert len(make().memories()) == 1

