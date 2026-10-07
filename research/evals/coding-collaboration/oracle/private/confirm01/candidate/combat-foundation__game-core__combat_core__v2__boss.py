"""Enemy turn/phase state machine; generic effects live in effects.py."""
from fractions import Fraction
from .state import ActionRequest,make_unit,fraction
from .scheduler import unit_order
from .effects import refresh_passives,remove_status,validate_action,begin_action,finish_action,apply_skill_effects


def apply_phase_transition(bundle,state,recorder):
    boss=state.units[bundle.boss_id]
    if boss.dead:return
    final=state.phase_index
    for i in range(final+1,len(bundle.phases)):
        if Fraction(boss.hp,boss.max_hp)<=fraction(bundle.phases[i].hp_threshold):final=i
    if final==state.phase_index:return
    previous=state.phase_index
    for i in range(previous+1,final+1):
        entered=i==final
        if entered:
            state.phase_index=final;phase=bundle.phases[final]
            boss.toughness_max=phase.toughness_max;boss.toughness=phase.toughness_max
            boss.weaknesses=list(phase.weaknesses);boss.broken=False
            boss.charging=None;boss.skill_index=0
            state.phase_action_count=0;state.enrage_stacks=0
            if phase.control_immune:
                for bid in sorted(list(boss.buffs)):
                    if bundle.buffs[bid].effect_type=='control':remove_status(bundle,state,bundle.boss_id,bid,'phase_immunity',recorder)
            refresh_passives(bundle,state,recorder)
        recorder.emit('phase_changed',state,dict(from_phase=bundle.phases[i-1].phase_id,to_phase=bundle.phases[i].phase_id,entered=entered,reason='hp_threshold',weaknesses=bundle.phases[i].weaknesses),target_id=bundle.boss_id)


def begin_enemy_turn(bundle,state,actor_id,recorder):
    u=state.units[actor_id]
    if u.broken:
        u.broken=False;u.toughness=u.toughness_max
        recorder.emit('toughness_restored',state,dict(value=u.toughness,reason='turn_start'),target_id=actor_id)
    if actor_id==bundle.boss_id:
        state.phase_action_count+=1
        if state.phase_action_count>bundle.phases[state.phase_index].enrage.trigger_actions:
            state.enrage_stacks+=1
            refresh_passives(bundle,state,recorder)
            recorder.emit('enrage_changed',state,dict(stacks=state.enrage_stacks),actor_id=actor_id)


def enemy_targets(bundle,state,actor_id,skill_id):
    skill=bundle.skills[skill_id]
    if skill.target=='self':return [actor_id]
    live=[(uid,u) for uid,u in state.units.items() if not u.dead and u.side=='player']
    if skill.target=='all':return [uid for uid,u in sorted(live,key=unit_order)]
    return [min(live,key=lambda item:(Fraction(item[1].hp,item[1].max_hp),unit_order(item)))[0]] if live else []


def choose_enemy_action(bundle,state,actor_id):
    u=state.units[actor_id]
    if actor_id==bundle.boss_id:
        pool=bundle.phases[state.phase_index].skill_pool
        skill_id=u.charging or pool[u.skill_index%len(pool)]
    else:skill_id=bundle.enemy_templates[u.template_id].skill_id
    return ActionRequest(actor_id=actor_id,skill_id=skill_id,target_ids=enemy_targets(bundle,state,actor_id,skill_id),reason_code='enemy_cycle')


def resolve_enemy_action(bundle,state,action,rng,recorder):
    validate_action(bundle,state,action)
    uid=action.actor_id;u=state.units[uid];skill=bundle.skills[action.skill_id]
    begin_action(bundle,state,action,recorder)
    advance=True
    if skill.effect_type=='summon':
        count=sum(not other.dead and other.template_id is not None for other in state.units.values())
        if count>=bundle.rules.max_adds:
            recorder.emit('summon_fallback',state,dict(skill_id=action.skill_id,fallback_skill=skill.fallback_skill,reason='max_adds'),actor_id=uid)
            fallback=ActionRequest(actor_id=uid,skill_id=skill.fallback_skill,target_ids=enemy_targets(bundle,state,uid,skill.fallback_skill),reason_code='summon_cap')
            apply_skill_effects(bundle,state,fallback,rng,recorder)
        else:
            state.summon_seq+=1;new_id=f'{skill.summon_template}_01_{state.summon_seq:04d}'
            template=bundle.enemy_templates[skill.summon_template]
            state.units[new_id]=make_unit(template.stats,'enemy',state.summon_seq,template_id=skill.summon_template,toughness=template.toughness_max,toughness_max=template.toughness_max,weaknesses=list(template.weaknesses))
            recorder.emit('summoned',state,dict(template_id=skill.summon_template,unit_id=new_id),actor_id=uid,target_id=new_id)
    elif skill.interruptible and u.charging is None:
        u.charging=action.skill_id;advance=False
        recorder.emit('charge_started',state,dict(skill_id=action.skill_id),actor_id=uid)
    else:
        if u.charging:
            u.charging=None
            recorder.emit('charge_released',state,dict(skill_id=action.skill_id),actor_id=uid)
        apply_skill_effects(bundle,state,action,rng,recorder)
    if advance:u.skill_index+=1
    finish_action(bundle,state,action,recorder)
