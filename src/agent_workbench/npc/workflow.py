"""NPC LangGraph: decisions never substitute for world receipts or player consent."""
from pathlib import Path
import json
from typing import TypedDict

from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt

from agent_workbench.models import ModelGateway, _one_json_object
from .contracts import NPCDecision, NPCError, PERSONAS, POLICY, canonical, fingerprint


class State(TypedDict, total=False):
    turn_id: str
    route: str


class NPCWorkflow:
    def __init__(self, store, world, model=None):
        self.store, self.world, self.model = store, world, model

    def _node(self, state, name):
        row = self.store.get(state['turn_id'])
        self.store.update(row['turn_id'], nodes=row['nodes'] + [name])
        return row

    def _failure(self, row, code):
        self.store.update(row['turn_id'], status='reconciling', error=code)
        return {'route': 'end'}

    def _receipt(self, row, receipt):
        request = row['approval_request']
        payload = {'action_id': row['action_id'], 'approval_id': request['approval_id'],
                   'expected_revision': request['expected_revision'], 'kind': 'support'}
        scope = self.world.scope
        event = receipt.get('event', {})
        if (receipt.get('action_id') != row['action_id'] or receipt.get('input_hash') != fingerprint(payload)
                or receipt.get('save_id') != scope.save_id or receipt.get('branch_id') != scope.branch_id
                or receipt.get('event_hash') != fingerprint(event)
                or event.get('kind') != 'support_prepared' or scope.npc_id not in event.get('visible_to', [])
                or event.get('payload', {}).get('approval_id') != request['approval_id']
                or receipt.get('support', {}).get('choice') != request['choice']):
            raise NPCError('receipt_mismatch', '世界回执未绑定本轮选择。')
        self.store.update(row['turn_id'], receipt=receipt, status='projecting', error=None)

    def reconcile(self, state):
        row = self._node(state, 'reconcile')
        if row['reply'] is not None:
            return {'route': 'end'}
        if row['receipt'] is not None:
            return {'route': 'project'}
        if row['approval'] is not None:
            try:
                receipt = self.world.receipt(row['action_id'])
                if receipt is not None:
                    self._receipt(row, receipt)
                    return {'route': 'project'}
            except NPCError as exc:
                return self._failure(row, exc.code)
            return {'route': 'commit'}
        if row['intent'] is not None:
            return {'route': 'validate'}
        return {'route': 'context'}

    def context(self, state):
        row = self._node(state, 'context')
        try:
            context = self.world.context()
            self.store.project(self.world.scope, context)
            # Freeze this turn's knowledge before any paid call. Later world events
            # cannot retroactively justify citations in an earlier model response.
            if row['context'] is None:
                self.store.update(row['turn_id'], context={
                    'revision': context['revision'], 'memories': self.store.memories(self.world.scope)})
        except NPCError as exc:
            return self._failure(row, exc.code)
        return {'route': 'decide'}

    def _recover_decision(self, attempt):
        # Validate the existing shared ledger without keys or a provider request.
        audit = Path(attempt['audit_path'])
        ModelGateway(audit_path=audit, max_calls=1).remaining_calls()
        if not audit.exists():
            return None
        records = [json.loads(line) for line in audit.read_text(encoding='utf-8').splitlines() if line.strip()]
        candidates = {r['call_id'] for r in records if r['call_id'] not in attempt['before_ids']
                      and r.get('payload_hash') == attempt['payload_hash']}
        if len(candidates) != 1:
            return None
        final = [r for r in records if r['call_id'] in candidates][-1]
        if final['status'] != 'completed' or final.get('output_method') != 'json_mode':
            return None
        raw = final.get('raw') or {}
        if (raw.get('finish_reason') != 'stop' or raw.get('tool_calls') or raw.get('invalid_tool_calls')
                or 'raw_choices' in final):
            return None
        return NPCDecision.model_validate(_one_json_object(raw.get('content')), strict=True).model_dump(mode='json')

    def decide(self, state):
        row = self._node(state, 'budgeted_decide')
        attempts = row['attempts']
        if attempts and attempts[-1]['status'] == 'calling':
            try:
                answer = self._recover_decision(attempts[-1])
            except (ValueError, RuntimeError, OSError):
                answer = None
            if answer is None:
                self.store.reply(row['turn_id'], '这次回应还无法核实，我不会重复执行。你可以重新发起对话。',
                                 status='model_unknown', error='model_outcome_unknown')
                return {'route': 'end'}
            attempts[-1].update(status='completed', decision=answer, recovered=True)
            self.store.update(row['turn_id'], attempts=attempts, intent=answer)
            return {'route': 'validate'}
        if self.model is None:
            reports = [m for m in row['context']['memories'] if m['kind'] == 'battle_report_shared']
            discuss_report = reports and any(word in row['request']['text'] for word in ('战报', '结果', '回来了'))
            answer = {'intent': 'offer_support' if self.world.scope.npc_id == 'lan' and not discuss_report else 'reply',
                      'text': '我在这里。暂时没有可核实的新消息。', 'citations': [], 'query': None}
            self.store.update(row['turn_id'], intent=answer, model_mode='offline')
            return {'route': 'validate'}
        if len(attempts) >= 2:
            self.store.reply(row['turn_id'], '这轮查询已到上限，我不会据此猜测。', status='rejected', error='read_limit')
            return {'route': 'end'}
        scope = self.world.scope
        messages = [{'role': 'system', 'content': PERSONAS[scope.npc_id] + '\n' + POLICY},
                    {'role': 'user', 'content': canonical({'turn_id': row['turn_id'],
                     'request': row['request']['text'], 'context': row['context'],
                     'read_result': row.get('read_result'), 'decisions_remaining': 2-len(attempts)})}]
        try:
            if self.model.remaining_calls() <= 0:
                raise NPCError('model_budget_exhausted', '模型授权额度已用尽。')
            preview = self.model.preview(messages, NPCDecision)
            audit = self.model.audit_path.resolve()
            records = [json.loads(s) for s in audit.read_text(encoding='utf-8').splitlines() if s.strip()] if audit.exists() else []
            attempt = {'status': 'calling', 'audit_path': str(audit), 'before_ids': sorted({r['call_id'] for r in records}),
                       'payload_hash': fingerprint(preview['payload'])}
            # ModelGateway uses sorted JSON with default spaces for its payload hash.
            import hashlib
            attempt['payload_hash'] = hashlib.sha256(json.dumps(preview['payload'], ensure_ascii=False,
                sort_keys=True, allow_nan=False).encode()).hexdigest()
            attempts.append(attempt)
            self.store.update(row['turn_id'], attempts=attempts, model_mode='deepseek', status='deciding')
            answer = self.model.complete(messages, NPCDecision)
            attempts[-1].update(status='completed', decision=answer)
            self.store.update(row['turn_id'], attempts=attempts, intent=answer)
        except Exception as exc:
            # No error strings/provider headers are delivered to player or memory.
            self.store.reply(row['turn_id'], '暂时无法继续交谈；没有替你提交任何支援。',
                status='rejected', error=exc.code if isinstance(exc, NPCError) else 'model_unavailable')
            return {'route': 'end'}
        return {'route': 'validate'}

    def validate(self, state):
        row = self._node(state, 'validate_intent')
        try:
            intent = NPCDecision.model_validate(row['intent'], strict=True)
            known = {m['event_id'] for m in row['context']['memories']}
            known.update(m['event_id'] for m in row.get('read_result', []))
            if (len(intent.citations) != len(set(intent.citations)) or not set(intent.citations) <= known
                    or (intent.intent == 'read_memory') != bool(intent.query)
                    or (intent.intent == 'offer_support' and self.world.scope.npc_id != 'lan')):
                raise ValueError('illegal intent or source citation')
        except ValueError:
            self.store.reply(row['turn_id'], '这项请求超出了我能确认的范围；我没有改变世界。',
                             status='rejected', error='invalid_intent')
            return {'route': 'end'}
        if intent.intent == 'read_memory':
            if len(row['attempts']) >= 2:
                self.store.reply(row['turn_id'], '这轮查询已到上限，我不会据此猜测。', status='rejected', error='read_limit')
                return {'route': 'end'}
            return {'route': 'read_memory'}
        if intent.intent == 'reply':
            return {'route': 'reply'}
        try:
            if row['offer'] is None:
                offer = self.world.offer()
                if not offer['choices']:
                    self.store.reply(row['turn_id'], '这次出战的支援已经安排好了。先完成这趟行动吧。')
                    return {'route': 'end'}
                self.store.update(row['turn_id'], offer=offer, status='awaiting_choice')
        except NPCError as exc:
            return self._failure(row, exc.code)
        return {'route': 'await_choice'}

    def read_memory(self, state):
        row = self._node(state, 'read_memory')
        # Query only the already-frozen visible memories: no token/scope in model args.
        query = row['intent']['query'].casefold()
        result = [m for m in row['context']['memories'] if query in canonical(m).casefold()]
        self.store.update(row['turn_id'], read_result=result, intent=None)
        return {'route': 'decide'}

    def await_choice(self, state):
        row = self._node(state, 'await_choice')
        if row['approval'] is None:
            interrupt({'turn_id': row['turn_id'], 'offer_hash': row['offer']['offer_hash'],
                       'choices': row['offer']['choices']})
        row = self.store.get(row['turn_id'])
        # Resume values are notifications, never authorization.
        return {'route': 'commit' if row['approval'] is not None else 'end'}

    def commit(self, state):
        row = self._node(state, 'commit_or_lookup')
        if row['approval'] is None:
            raise NPCError('approval_required', '需要玩家选择。')
        request = row['approval_request']
        payload = {k: request[k] for k in ('action_id', 'approval_id', 'expected_revision')}
        self.store.update(row['turn_id'], status='reconciling')
        try:
            receipt = self.world.receipt(row['action_id'])
            if receipt is None:
                receipt = self.world.commit(payload)
            self._receipt(row, receipt)
        except NPCError as exc:
            if exc.code in ('revision_conflict', 'invalid_approval', 'support_unavailable', 'idempotency_conflict'):
                self.store.reply(row['turn_id'], '这次选择已经过期，请重新与我商量支援。', status='rejected', error=exc.code)
                return {'route': 'end'}
            return self._failure(row, exc.code)
        return {'route': 'project'}

    def project(self, state):
        row = self._node(state, 'project_visible_events')
        try:
            self.store.project(self.world.scope, self.world.context())
        except NPCError as exc:
            return self._failure(row, exc.code)
        return {'route': 'reply'}

    def reply(self, state):
        row = self._node(state, 'persist_reply')
        if row['receipt']:
            choice = row['receipt']['support']['choice']
            text = ('护盾已经为你备好：下一场每人获得120点护盾，到各自第3个普通回合末到期，耗尽会提前消失。'
                    if choice == 'shield_start' else '战技补给已经备好：下一场开局增加1点战技点，上限5点。')
            citations = [row['receipt']['event']['event_id']]
        elif row['model_mode'] == 'offline':
            reports = [m for m in row['context']['memories'] if m['kind'] == 'battle_report_shared']
            if reports:
                report = reports[-1]
                outcome = {'win': '你们击败了守卫', 'loss': '这次没能守住', 'timeout': '这场战斗到了行动上限'}.get(report['payload']['result']['outcome'], '这次行动结束了')
                text, citations = '我看过你带回的战报了，'+outcome+'。这一趟辛苦了，稍作休整再出发吧。', [report['event_id']]
            else:
                text, citations = '这趟的事我还不清楚。我会记下你告诉我的话，等有了战报再一起看看。', []
        else:
            text, citations = row['intent']['text'], row['intent']['citations']
        self.store.reply(row['turn_id'], text, citations=citations)
        return {'route': 'end'}

    def compile(self, saver):
        graph = StateGraph(State)
        names = ['reconcile', 'context', 'decide', 'validate', 'read_memory', 'await_choice', 'commit', 'project', 'reply']
        routes = {name: name for name in names} | {'end': END}
        for name in names:
            graph.add_node(name, getattr(self, name))
            graph.add_conditional_edges(name, lambda state: state['route'], routes)
        graph.add_edge(START, 'reconcile')
        return graph.compile(checkpointer=saver)
