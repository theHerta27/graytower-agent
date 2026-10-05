"""Trusted local API. Startup supplies credentials/scope; turn input cannot."""
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from agent_workbench.models import ModelGateway, no_external_tracing
from agent_workbench.verification.store import driver_lock
from .contracts import NPCError, TurnInput, fingerprint
from .store import NPCStore
from .workflow import NPCWorkflow


class NPCService:
    def __init__(self, data, world, *, model=None):
        self.root, self.world, self.model = Path(data), world, model
        if model is not None and (not isinstance(model, ModelGateway) or model.audit_path is None
                                  or model.output_method != 'json_mode'):
            raise ValueError('NPC needs the audited JSON ModelGateway and explicit persistent budget')
        self.store = NPCStore(self.root)

    def _id(self, request_id):
        TurnInput(request_id=request_id, text='lookup')
        return 'turn_' + fingerprint({'scope': self.world.scope.model_dump(), 'request_id': request_id})[:48]

    def _public(self, row):
        return {k: row[k] for k in ('turn_id', 'scope', 'request', 'status', 'action_id', 'reply_id',
                'model_mode', 'offer', 'receipt', 'reply', 'error')}

    def get(self, request_id):
        return self._public(self.store.get(self._id(request_id)))

    def memories(self, query=None):
        return self.store.memories(self.world.scope, query)

    def _drive(self, row):
        if row['reply'] is not None or (row['status'] == 'awaiting_choice' and row['approval'] is None):
            return self._public(row)
        with no_external_tracing(), SqliteSaver.from_conn_string(str(self.root / 'npc-checkpoints.sqlite')) as saver:
            graph = NPCWorkflow(self.store, self.world, self.model).compile(saver)
            config = {'configurable': {'thread_id': row['turn_id']}, 'recursion_limit': 24, 'callbacks': []}
            snapshot = graph.get_state(config)
            if snapshot.interrupts and row['approval'] is not None:
                graph.invoke(Command(resume={item.id: 'read-persisted-player-decision' for item in snapshot.interrupts}), config)
            else:
                # Always enter reconcile; persisted side-effect records are stronger
                # than a checkpoint left before/after the actual world transaction.
                graph.invoke({'turn_id': row['turn_id']}, config)
        return self.get(row['request']['request_id'])

    def turn(self, request_id, text):
        request = TurnInput(request_id=request_id, text=text)
        with driver_lock(self.root):
            # The service-bound world session is validated before accepting scope.
            self.world.context()
            row = self.store.admit(self.world.scope, request)
            return self._drive(row)

    def choose(self, request_id, choice, offer_hash, player):
        with driver_lock(self.root):
            row = self.store.get(self._id(request_id))
            scope = self.world.scope
            if (player.save_id, player.branch_id) != (scope.save_id, scope.branch_id):
                raise NPCError('scope_mismatch', '玩家不属于这份存档分支。')
            offer = row['offer']
            if (offer is None or offer['offer_hash'] != offer_hash
                    or choice not in [item['choice'] for item in offer['choices']]):
                raise NPCError('invalid_choice', '请使用当前对话中展示的选择。')
            payload = {'approval_id': 'approval_' + row['turn_id'][5:], 'action_id': row['action_id'],
                       'offer_hash': offer_hash, 'choice': choice, 'expected_revision': offer['revision']}
            if row['approval_request'] is not None and row['approval_request'] != payload:
                raise NPCError('choice_conflict', '这轮对话已经绑定另一项选择。')
            if row['reply'] is not None:
                return self._public(row)
            row = self.store.update(row['turn_id'], approval_request=payload)
            if row['approval'] is None:
                try:
                    approval = player.confirm(payload)
                except NPCError as exc:
                    if exc.code in ('revision_conflict', 'invalid_approval', 'already_approved', 'idempotency_conflict'):
                        return self._public(self.store.reply(row['turn_id'], '这次选择已经过期，请重新与我商量支援。',
                                                            status='rejected', error=exc.code))
                    self.store.update(row['turn_id'], error=exc.code)
                    raise
                row = self.store.update(row['turn_id'], approval=approval, error=None)
            return self._drive(row)
