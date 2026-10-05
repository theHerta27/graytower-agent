"""Fixed loopback world protocol. NPC and player capabilities stay separate."""
from urllib.parse import urlsplit

import httpx

from .contracts import NPCError, Scope, fingerprint


class _Transport:
    def __init__(self, token, *, base_url='http://127.0.0.1:8780', client=None):
        parsed = urlsplit(base_url)
        if (parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or parsed.username
                or parsed.password or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
            raise ValueError('world endpoint must be an explicit loopback HTTP origin')
        if not isinstance(token, str) or not token:
            raise ValueError('a trusted world session is required')
        self._token, self.base_url = token, base_url.rstrip('/')
        self._owned = client is None
        self._client = client or httpx.Client(timeout=10, trust_env=False, follow_redirects=False)

    def close(self):
        if self._owned:
            self._client.close()

    def _request(self, method, path, payload=None):
        try:
            response = self._client.request(method, self.base_url + path,
                headers={'X-World-Session': self._token}, **({'json': payload} if payload is not None else {}))
        except (httpx.HTTPError, OSError):
            raise NPCError('world_unavailable', '本机世界暂时不可用；原行动仍保留。') from None
        try:
            result = response.json()
        except (ValueError, TypeError):
            raise NPCError('world_unavailable', '世界响应不完整；先对账。') from None
        if response.status_code >= 400:
            error = result.get('error', {}) if isinstance(result, dict) else {}
            code = error.get('code', 'world_rejected')
            raise NPCError(code, '世界拒绝此请求。')
        if not 200 <= response.status_code < 300 or not isinstance(result, dict):
            raise NPCError('world_unavailable', '世界未返回可信响应。')
        return result


class WorldClient(_Transport):
    def __init__(self, scope: Scope, token, **kwargs):
        super().__init__(token, **kwargs)
        self.scope = Scope.model_validate(scope)

    def _bound(self, value):
        if any(value.get(k) != getattr(self.scope, k) for k in ('save_id', 'branch_id')):
            raise NPCError('scope_mismatch', '世界响应不属于当前存档分支。')
        return value

    def context(self):
        value = self._bound(self._request('GET', '/world/context'))
        if value.get('npc_id') != self.scope.npc_id:
            raise NPCError('scope_mismatch', '世界响应不属于当前角色。')
        for event in value.get('events', []):
            self._bound(event)
            if self.scope.npc_id not in event['visible_to']:
                raise NPCError('visibility_violation', '角色不可读取这段经历。')
        return value

    def offer(self):
        value = self._bound(self._request('GET', '/world/support/offer'))
        body = {k: v for k, v in value.items() if k != 'offer_hash'}
        if value.get('npc_id') != self.scope.npc_id or value.get('offer_hash') != fingerprint(body):
            raise NPCError('integrity_error', '支援选项来源不一致。')
        return value

    def receipt(self, action_id):
        from .contracts import TurnInput
        TurnInput(request_id=action_id, text='receipt')
        try:
            return self._bound(self._request('GET', '/world/receipts/' + action_id))
        except NPCError as exc:
            if exc.code == 'not_found':
                return None
            raise

    def commit(self, payload):
        return self._bound(self._request('POST', '/world/support/commit', payload))


class PlayerWorldClient(_Transport):
    """Only caller holding the player's session can confirm; never passed to graph/model."""
    def __init__(self, save_id, branch_id, token, **kwargs):
        super().__init__(token, **kwargs)
        self.save_id, self.branch_id = save_id, branch_id

    def confirm(self, payload):
        value = self._request('POST', '/world/support/confirm', payload)
        if (value.get('save_id') != self.save_id or value.get('branch_id') != self.branch_id
                or value.get('decision') != payload or value.get('approved_by') != 'local_player'):
            raise NPCError('invalid_approval', '玩家选择回执不匹配。')
        return value
