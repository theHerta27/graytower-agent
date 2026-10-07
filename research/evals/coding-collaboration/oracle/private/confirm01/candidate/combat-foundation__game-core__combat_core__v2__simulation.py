"""Single-authority deterministic battle loop, isolated from legacy simulation."""
import platform
import random
from fractions import Fraction
from .contracts import CombatBundle,Scenario
from .state import initial_state
from .scheduler import next_actor,advance_time,finish_turn,assert_invariants
from .effects import start_statuses,end_statuses,resolve_action
from .boss import begin_enemy_turn,apply_phase_transition,choose_enemy_action,resolve_enemy_action
from .bots import choose_ultimate,choose_normal_action
from .trace import CombatTrace,Result,EventRecorder
from .config import config_hash,scenario_hash


def outcome(bundle,state):
    if state.units[bundle.boss_id].dead:return 'win'
    if all(state.units[uid].dead for uid in bundle.party):return 'loss'
    return None


def simulate(bundle:CombatBundle,scenario:Scenario)->CombatTrace:
    # Revalidate even caller-constructed models; model_copy updates can bypass validation.
    bundle=CombatBundle.model_validate(bundle.model_dump())
    scenario=Scenario.model_validate(scenario.model_dump())
    state=initial_state(bundle,scenario);initial=state.model_copy(deep=True)
    rec=EventRecorder();rng=random.Random(scenario.seed)
    rec.emit('battle_started',state,{})
    result=None;reason=''
    while result is None:
        assert_invariants(state)
        result=outcome(bundle,state)
        if result:reason='boss_dead' if result=='win' else 'party_dead';break
        if state.normal_turn_count>=scenario.limits.normal_turns:result='timeout';reason='normal_turn_limit';break
        if state.action_count>=scenario.limits.actions:result='timeout';reason='action_limit';break
        delta=min(u.remaining_distance/u.spd for u in state.units.values() if not u.dead)
        if state.elapsed_av+delta>scenario.limits.elapsed_av:
            advance_time(state,Fraction(scenario.limits.elapsed_av)-state.elapsed_av)
            result='timeout';reason='av_limit';break
        actor=next_actor(state);state.current_actor=actor;state.normal_turn_count+=1
        state.ultimate_used=False;state.normal_used=False;state.action_id=None
        rec.emit('turn_started',state,{},actor_id=actor)
        u=state.units[actor]
        if u.side=='enemy':begin_enemy_turn(bundle,state,actor,rec)
        start_statuses(bundle,state,actor,rng,rec)
        result=outcome(bundle,state)
        if result:reason='boss_dead' if result=='win' else 'party_dead';break
        apply_phase_transition(bundle,state,rec)
        if not u.dead:
            controlled=any(bundle.buffs[bid].effect_type=='control' for bid in u.buffs)
            if controlled:rec.emit('control_skipped',state,{},actor_id=actor)
            else:
                if u.side=='player':
                    ultimate=choose_ultimate(bundle,state,actor,scenario.strategy)
                    if ultimate:
                        resolve_action(bundle,state,ultimate,rng,rec)
                        result=outcome(bundle,state)
                        if result:reason='boss_dead' if result=='win' else 'party_dead';break
                        apply_phase_transition(bundle,state,rec)
                        if state.action_count>=scenario.limits.actions:result='timeout';reason='action_limit';break
                    resolve_action(bundle,state,choose_normal_action(bundle,state,actor,scenario.strategy),rng,rec)
                else:resolve_enemy_action(bundle,state,choose_enemy_action(bundle,state,actor),rng,rec)
                result=outcome(bundle,state)
                if result:reason='boss_dead' if result=='win' else 'party_dead';break
                apply_phase_transition(bundle,state,rec)
        end_statuses(bundle,state,actor,rec)
        finish_turn(state,actor)
        rec.emit('turn_finished',state,{},actor_id=actor)
    assert_invariants(state)
    rec.cause=None
    rec.emit('battle_finished',state,dict(outcome=result,reason=reason))
    return CombatTrace(phase_ids=[p.phase_id for p in bundle.phases],policy_id=scenario.strategy,python_version=platform.python_version(),config_hash=config_hash(bundle),scenario_hash=scenario_hash(scenario),seed=scenario.seed,initial_state=initial,events=rec.events,result=Result(outcome=result,reason=reason,final_state=state.model_copy(deep=True)))
