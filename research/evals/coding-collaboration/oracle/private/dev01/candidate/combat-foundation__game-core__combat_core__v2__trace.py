"""Typed event evidence. Every kind has a closed payload schema."""
from typing import Annotated, Literal, Union
from pydantic import Field, create_model, model_validator
from .contracts import Model, Nat
from .state import BattleState, Rational

PAYLOADS = {
'battle_started': {},
' turn_started': {},
'decision': {'skill_id':str,'target_ids':list[str],'reason_code':str},
'resource_changed': {'resource':Literal['energy','skill_points'],'before':Nat,'after':Nat,'gained':Nat,'spent':Nat,'overflow':Nat,'reason':str},
'direct_damage': {'amount':Nat,'absorbed':Nat,'hp_loss':Nat,'overkill':Nat,'critical':bool,'skill_id':str,'damage_type':str},
'heal': {'amount':Nat,'restored':Nat,'overflow':Nat,'skill_id':str},
'shield_applied': {'value':Nat,'duration':Nat,'skill_id':str,'refreshed':bool},
'shield_absorbed': {'amount':Nat,'remaining':Nat,'shield_seq':Nat},
'shield_expired': {'shield_seq':Nat,'reason':str},
'status_applied': {'buff_id':str,'duration':Nat,'stacks':Nat,'source_id':str,'attack_snapshot':Rational},
'status_removed': {'buff_id':str,'reason':str},
'dot_damage': {'amount':Nat,'absorbed':Nat,'hp_loss':Nat,'overkill':Nat,'buff_id':str},
' toughness_changed': {'before':Nat,'after':Nat,'reduction':Nat,'damage_type':str,'matched':bool},
'break_triggered': {'skill_id':str,'damage_type':str,'before':Nat,'after':Literal[0]},
'break_damage': {'amount':Nat,'absorbed':Nat,'hp_loss':Nat,'overkill':Nat},
'action_delayed': {'before':Rational,'after':Rational,'distance':Nat},
'toughness_restored': {'value':Nat,'reason':str},
'charge_started': {'skill_id':str},
'charge_cancelled': {'skill_id':str,'reason':str},
'charge_released': {'skill_id':str},
'summoned': {'template_id':str,'unit_id':str},
'summon_fallback': {'skill_id':str,'fallback_skill':str,'reason':str},
'unit_died': {},
'passive_changed': {'active':bool,'spd':Rational},
'rng_draw': {'index':Nat,'purpose':str,'value':float,'threshold':Rational},
'phase_changed': {'from_phase':str,'to_phase':str,'entered':bool,'reason':str,'weaknesses':list[str]},
'enrage_changed': {'stacks':Nat},
'control_skipped': {},
'action_finished': {'skill_id':str},
'turn_finished': {},
'battle_finished': {'outcome':Literal['win','loss','timeout'],'reason':str},
}
PAYLOADS={k.strip():v for k,v in PAYLOADS.items()}

class EventBase(Model):
    event_id: str
    turn_id: Nat
    action_id: str | None
    actor_id: str | None
    target_id: str | None
    av: Rational
    cause_event_id: str | None
    state_after: BattleState

EVENT_MODELS={}
for kind,fields in PAYLOADS.items():
    payload=create_model(kind.title().replace('_','')+'Payload',__base__=Model,**{k:(v,...) for k,v in fields.items()})
    EVENT_MODELS[kind]=create_model(kind.title().replace('_','')+'Event',__base__=EventBase,kind=(Literal[kind],...),payload=(payload,...))
Event = Annotated[Union[tuple(EVENT_MODELS.values())], Field(discriminator='kind')]

class Result(Model):
    outcome: Literal['win','loss','timeout']
    reason: str
    final_state: BattleState

class CombatTrace(Model):
    trace_version: Literal['2.0'] = '2.0'
    contract_version: Literal['2.0'] = '2.0'
    simulator_version: Literal['2.0.0'] = '2.0.0'
    policy_version: Literal['1.0'] = '1.0'
    phase_ids: list[str]
    policy_id: Literal['balanced','survival','basic_only']
    python_version: str
    rng: Literal['python-random-MT19937-v3'] = 'python-random-MT19937-v3'
    config_hash: str
    scenario_hash: str
    seed: Nat
    initial_state: BattleState
    events: list[Event] = Field(min_length=1)
    result: Result

    @model_validator(mode='after')
    def integrity(self):
        seen=set()
        for i,e in enumerate(self.events,1):
            if e.event_id != f'event_{i:06d}': raise ValueError('event sequence mismatch')
            if e.cause_event_id is not None and e.cause_event_id not in seen: raise ValueError('invalid event cause')
            if e.actor_id is not None and e.actor_id not in e.state_after.units: raise ValueError('unknown actor')
            if e.target_id is not None and e.target_id not in e.state_after.units: raise ValueError('unknown target')
            seen.add(e.event_id)
        if self.events[0].kind != 'battle_started' or self.events[-1].kind != 'battle_finished': raise ValueError('incomplete trace')
        if self.events[-1].state_after != self.result.final_state: raise ValueError('final state mismatch')
        terminal=self.events[-1].payload
        if (terminal.outcome,terminal.reason)!=(self.result.outcome,self.result.reason):raise ValueError('terminal outcome/reason mismatch')
        if self.events[0].state_after!=self.initial_state:raise ValueError('initial state mismatch')
        from .scheduler import assert_invariants
        assert_invariants(self.result.final_state)
        bosses=[uid for uid,u in self.initial_state.units.items() if u.side=='enemy' and u.slot==0]
        if len(bosses)!=1:raise ValueError('missing/ambiguous boss')
        boss=self.result.final_state.units.get(bosses[0])
        if boss is None:raise ValueError('missing final boss')
        players=[uid for uid,u in self.initial_state.units.items() if u.side=='player']
        if not players or any(uid not in self.result.final_state.units for uid in players):raise ValueError('missing final party')
        party_dead=all(self.result.final_state.units[uid].dead for uid in players)
        actual='win' if boss.dead else 'loss' if party_dead else 'timeout'
        if self.result.outcome!=actual:raise ValueError('outcome inconsistent with final combat state')
        reasons={'win':{'boss_dead'},'loss':{'party_dead'},'timeout':{'normal_turn_limit','action_limit','av_limit'}}
        if self.result.reason not in reasons[actual]:raise ValueError('invalid terminal reason')
        return self

class EventRecorder:
    def __init__(self):
        self.events=[]
        self.cause=None
    def emit(self, kind: str, state: BattleState, payload: dict, *, actor_id=None, target_id=None, cause_event_id=None) -> str:
        if kind not in EVENT_MODELS: raise ValueError('unknown event kind')
        cause=cause_event_id if cause_event_id is not None else self.cause
        if cause is not None and not any(e.event_id==cause for e in self.events): raise ValueError('unknown cause')
        event=EVENT_MODELS[kind](kind=kind,event_id=f'event_{len(self.events)+1:06d}',turn_id=state.normal_turn_count,action_id=state.action_id,actor_id=actor_id,target_id=target_id,av=state.elapsed_av,cause_event_id=cause,payload=payload,state_after=state.model_copy(deep=False))
        self.events.append(event)
        return event.event_id

class ComparisonResult(Model):
    passed: bool
    first_difference_path: str | None = None
    expected: object = None
    actual: object = None


def compare_traces(expected,actual) -> ComparisonResult:
    from .config import canonical
    def value(v):return v.model_dump(mode='json') if isinstance(v,CombatTrace) else v
    left,right=value(expected),value(actual)
    def difference(a,b,path):
        if type(a)!=type(b):return path,a,b
        if isinstance(a,dict):
            if a.keys()!=b.keys():return path+'.keys',sorted(a),sorted(b)
            for k in sorted(a):
                d=difference(a[k],b[k],path+'.'+k)
                if d:return d
        elif isinstance(a,list):
            if len(a)!=len(b):return path+'.length',len(a),len(b)
            for i,(x,y) in enumerate(zip(a,b)):
                d=difference(x,y,f'{path}[{i}]')
                if d:return d
        elif a!=b:return path,a,b
        return None
    d=difference(left,right,'$')
    if d:return ComparisonResult(passed=False,first_difference_path=d[0],expected=d[1],actual=d[2])
    # Two equally malformed traces must never pass verification.
    try:
        CombatTrace.model_validate(left);canonical(left)
    except (ValueError,TypeError) as exc:
        return ComparisonResult(passed=False,first_difference_path='$schema',actual=str(exc))
    return ComparisonResult(passed=True)
