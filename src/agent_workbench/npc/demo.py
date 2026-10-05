"""Local, explicitly offline camp demo using the real NPC graph and Game Host."""
from contextlib import asynccontextmanager
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import threading
import uuid

import httpx
from starlette.concurrency import run_in_threadpool
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .contracts import NPCError, Scope, TurnInput
from .service import NPCService
from .world_client import WorldClient, PlayerWorldClient


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


class CampDemo:
    def __init__(self, data, game):
        self.root, self.game = Path(data).resolve(), Path(game).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.http = httpx.Client(base_url='http://127.0.0.1:8780', timeout=20, trust_env=False)
        self.player_process = self.player_job = self.player_log = None
        path = self.root / 'camp.json'
        if not path.exists():
            save(path, {'save_id': 'camp_' + uuid.uuid4().hex[:16], 'turns': {}})
        self.record = json.loads(path.read_text(encoding='utf-8'))

    def write(self):
        save(self.root / 'camp.json', self.record)

    def call(self, method, path, payload=None, token=None):
        result = self.http.request(method, path, headers={'X-World-Session': token or self.record.get('player', '')},
                                   **({'json': payload} if payload is not None else {}))
        body = result.json()
        if result.status_code >= 400:
            error = body.get('error', {})
            raise NPCError(error.get('code', 'world_error'), error.get('message', '世界暂时不可用。'))
        return body

    def bootstrap(self):
        if 'player' not in self.record:
            value = self.call('POST', '/world/saves', {'request_id': 'create', 'save_id': self.record['save_id']})
            self.record['player'] = value['player_session']
            self.record['npcs'] = {npc: self.call('POST', '/world/npc-session', {'npc_id': npc})['npc_session']
                                   for npc in ('lan', 'li')}
            self.write()

    def service(self, npc):
        if npc not in ('lan', 'li'):
            raise NPCError('invalid_npc', '角色不存在。')
        world = WorldClient(Scope(save_id=self.record['save_id'], branch_id='main', npc_id=npc),
                            self.record['npcs'][npc], client=self.http)
        return NPCService(self.root / 'npc', world)

    def operation(self, key, path, payload):
        TurnInput(request_id=key, text='operation')
        target = self.root / 'operations' / (key + '.json')
        if target.exists():
            frozen = json.loads(target.read_text(encoding='utf-8'))
            if frozen['path'] != path or any(frozen['payload'].get(k) != v for k, v in payload.items() if k != 'expected_revision'):
                raise NPCError('input_conflict', '这次操作已绑定其他内容。')
            payload = frozen['payload']
        else:
            save(target, {'path': path, 'payload': payload})
        return self.call('POST', path, payload)

    def state(self):
        self.bootstrap()
        context = self.call('GET', '/world/context')
        turns, memories = {}, {}
        for npc in ('lan', 'li'):
            service = self.service(npc)
            service.store.project(service.world.scope, service.world.context())
            memories[npc] = service.memories()
            request_id = self.record['turns'].get(npc)
            if request_id:
                turns[npc] = service.get(request_id)
        current = [e for e in context['events'] if e['payload'].get('expedition_id') == context['expedition_id']]
        starts = [e for e in current if e['kind'] == 'battle_started']
        battle = self.call('GET', '/sessions/' + starts[-1]['payload']['session_id']) if starts else None
        return {'offline': True, 'save_id': self.record['save_id'], 'expedition': context['expedition_id'],
                'turns': turns, 'memories': memories, 'battle': battle,
                'support_ready': any(e['kind'] == 'support_prepared' for e in current),
                'report_shared': any(e['kind'] == 'battle_report_shared' for e in current),
                'player_open': self.player_process is not None and self.player_process.poll() is None}

    def talk(self, value):
        self.bootstrap()
        request = TurnInput(request_id=value['request_id'], text=value['text'])
        npc = value.get('npc', 'lan'); service = self.service(npc)
        previous = self.record['turns'].get(npc)
        if previous and previous != request.request_id and service.get(previous)['status'] in ('awaiting_choice', 'reconciling'):
            raise NPCError('choice_pending', '请先完成当前支援选择。')
        context = self.call('GET', '/world/context')
        self.operation('tell_' + request.request_id, '/world/tell', {'action_id': 'tell_' + request.request_id,
            'expected_revision': context['revision'], 'npc_id': npc, 'text': request.text})
        self.record['turns'][npc] = request.request_id; self.write()
        service.turn(request.request_id, request.text)
        return self.state()

    def choose(self, value):
        service = self.service('lan')
        player = PlayerWorldClient(self.record['save_id'], 'main', self.record['player'], client=self.http)
        service.choose(value['request_id'], value['choice'], value['offer_hash'], player)
        return self.state()

    def start(self, value):
        current = self.state()
        if current['battle'] is None:
            context = self.call('GET', '/world/context')
            suffix = hashlib.sha256((context['save_id'] + context['expedition_id']).encode()).hexdigest()[:24]
            self.operation('start_' + suffix, '/world/start', {'action_id': 'start_' + suffix,
                'expected_revision': context['revision'], 'session_id': 'battle_' + suffix, 'seed': 7, 'strategy': 'balanced'})
            current = self.state()
        if value.get('open_player', True):
            self.open_player(current['battle'])
        return self.state()

    def open_player(self, battle):
        if self.player_process is not None and self.player_process.poll() is None:
            return
        self.close_player()
        from play_live import select_player, verify_selection
        from unity_process import start_owned, safe_environment
        executable, selection = select_player()
        verify_selection(executable, selection, selection['sha256'])
        directory = self.root / 'players' / battle['session_id']; directory.mkdir(parents=True, exist_ok=True)
        journal = directory / 'client-session.json'
        if not journal.exists():
            body = {'schema_version': 'combat-live-v1', 'session_id': battle['session_id'], 'created': True,
                'create_payload': '{}', 'pending_payload': None, 'last_revision': battle['revision'],
                'world_session': self.record['player']}
            raw = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
            body['content_sha256'] = hashlib.sha256(raw.encode()).hexdigest()
            save(journal, body)
        log = directory / ('player-' + uuid.uuid4().hex[:8] + '.log')
        self.player_log = log.with_suffix('.process.log').open('x', encoding='utf-8')
        command = [str(executable), '-combat-live', '-force-d3d11', '-combat-live-state', str(journal),
                   '-combat-live-evidence', str(directory / 'evidence'), '-logFile', str(log)]
        self.player_process, self.player_job = start_owned(command, cwd=executable.parent, env=safe_environment(),
                stdout=self.player_log, stderr=subprocess.STDOUT)
        save(directory / 'last-launch.json', {'pid': self.player_process.pid, 'selection': selection,
                                             'journal': str(journal), 'model_calls': 0})

    def finish_demo(self, value):
        current = self.state()
        if current['player_open']:
            raise NPCError('player_open', '请先关闭游戏窗口，再使用快速战斗演示，避免两处同时操作。')
        view = current['battle']
        if view is None:
            raise NPCError('no_battle', '请先进入战斗。')
        from combat_core.v2.bots import choose_normal_action, choose_ultimate
        from combat_core.v2.config import load_bundle
        from combat_core.v2.state import BattleState
        bundle = load_bundle(self.game / 'configs/combat/v2/baseline.json')
        for _ in range(200):
            obs = view['observation']
            if obs['phase'] == 'finished':
                return self.state()
            state = BattleState.model_validate(obs['state'])
            selected = (choose_ultimate if obs['phase'] == 'ultimate' else choose_normal_action)(bundle, state, obs['actor_id'], 'balanced')
            command = {'kind': 'action', **selected.model_dump(mode='json'), 'reason_code': 'player'} if selected else {'kind': 'skip_ultimate'}
            view = self.call('POST', '/sessions/' + view['session_id'] + '/commands',
                {'command_id': 'demo_' + str(view['revision']), 'expected_revision': view['revision'], 'command': command})
        raise NPCError('demo_limit', '快速演示达到行动上限，进度已保存。')

    def share(self, value):
        current = self.state()
        if current['battle'] is None:
            raise NPCError('no_battle', '还没有战斗。')
        context = self.call('GET', '/world/context'); session = current['battle']['session_id']
        self.operation('share_' + session, '/world/share-report', {'action_id': 'share_' + session,
            'expected_revision': context['revision'], 'session_id': session, 'npc_id': 'lan'})
        request_id = 'report_' + session
        self.record['turns']['lan'] = request_id; self.write()
        self.service('lan').turn(request_id, '我回来了，请看看这次战报。')
        return self.state()

    def next(self, value):
        current = self.state()
        if current['player_open']:
            raise NPCError('player_open', '请先关闭上一场的游戏窗口。')
        context = self.call('GET', '/world/context')
        key = 'next_' + hashlib.sha256(context['expedition_id'].encode()).hexdigest()[:24]
        self.operation(key, '/world/next-expedition', {'action_id': key, 'expected_revision': context['revision'], 'expedition_id': key})
        self.record['turns'] = {}; self.write()
        return self.state()

    def close_player(self):
        if self.player_job is not None:
            self.player_job.close()
            self.player_process.wait(timeout=10)
            self.player_job = None
        if self.player_log is not None:
            self.player_log.close(); self.player_log = None

    def close(self):
        self.close_player(); self.http.close()


def create_demo_app(data, game):
    from combat_core.host import create_app
    demo = CampDemo(data, game)
    app = create_app(Path(data) / 'world')
    original_lifespan = app.router.lifespan_context
    @asynccontextmanager
    async def lifespan(application):
        async with original_lifespan(application):
            try:
                yield
            finally:
                await run_in_threadpool(demo.close)
    app.router.lifespan_context = lifespan
    async def api(request):
        try:
            action = request.path_params['action']
            if action not in ('state', 'talk', 'choose', 'start', 'finish_demo', 'share', 'next'):
                return JSONResponse({'error': '接口不存在'}, status_code=404)
            if (action == 'state') != (request.method == 'GET'):
                return JSONResponse({'error': '方法不匹配'}, status_code=405)
            if int(request.headers.get('content-length', '0')) > 8192:
                return JSONResponse({'error': '请求过长'}, status_code=413)
            value = await request.json() if request.method == 'POST' else None
            def invoke():
                with demo.lock:
                    return demo.state() if action == 'state' else getattr(demo, action)(value)
            return JSONResponse(await run_in_threadpool(invoke))
        except (NPCError, ValueError, KeyError) as exc:
            return JSONResponse({'error': str(exc)}, status_code=409)
        except (httpx.HTTPError, OSError):
            return JSONResponse({'error': '本机服务暂时不可用，已有进度保留，请重试。'}, status_code=503)
    frontend = Path(__file__).resolve().parents[3] / 'frontend/dist'
    async def page(request):
        return FileResponse(frontend / 'index.html')
    app.router.routes.extend([Route('/camp', page), Route('/camp/api/{action}', api, methods=['GET', 'POST']),
                              Mount('/assets', StaticFiles(directory=frontend / 'assets'), name='camp-assets')])
    return app
