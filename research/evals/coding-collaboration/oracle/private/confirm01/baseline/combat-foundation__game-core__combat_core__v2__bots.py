"""Policies inspect current public state only. No RNG or future simulation."""
from fractions import Fraction
from .state import ActionRequest,fraction
from .scheduler import unit_order

THRESHOLDS={'balanced':Fraction(7,10),'survival':Fraction(85,100),'basic_only':Fraction(0)}

def lowest_health(state):
    return min((Fraction(u.hp,u.max_hp) for u in state.units.values() if u.side=='player' and not u.dead),default=Fraction(1))

def targets(bundle,state,actor_id,skill_id):
    skill=bundle.skills[skill_id]
    if skill.target=='self':return [actor_id]
    side='player' if skill.effect_type in ('heal','shield') else 'enemy'
    live=[item for item in state.units.items() if item[1].side==side and not item[1].dead]
    if skill.target=='all':return [uid for uid,u in sorted(live,key=unit_order)]
    character=bundle.characters[actor_id]
    if character.passive.kind!='low_toughness_bonus':
        matching=[item for item in live if not item[1].broken and skill.damage_type in item[1].weaknesses]
        if matching:return [min(matching,key=lambda item:(item[1].toughness,item[0]!=bundle.boss_id,unit_order(item)))[0]]
    return [min(live,key=lambda item:(item[0]!=bundle.boss_id,unit_order(item)))[0]] if live else []

def choose_ultimate(bundle,state,actor_id,policy_id):
    if policy_id not in THRESHOLDS:raise ValueError('unknown policy')
    c=bundle.characters[actor_id];u=state.units[actor_id]
    if policy_id=='basic_only' or u.dead or u.energy!=u.energy_max or state.ultimate_used or state.normal_used:return None
    if any(bundle.buffs[bid].effect_type=='control' for bid in u.buffs):return None
    sid=c.skill_slots.ultimate;skill=bundle.skills[sid]
    if skill.effect_type=='shield':
        scale={'ATK':u.atk,'HP':u.max_hp,'DEF':u.defense}[skill.scaling_stat]
        value=int(scale*fraction(skill.multiplier))
        if not any(sum(sh.value for sh in t.shields)<Fraction(value,2) for t in state.units.values() if t.side=='player' and not t.dead):return None
    return ActionRequest(actor_id=actor_id,skill_id=sid,target_ids=targets(bundle,state,actor_id,sid),reason_code='shield_needed' if skill.effect_type=='shield' else 'full_energy')

def choose_normal_action(bundle,state,actor_id,policy_id):
    if policy_id not in THRESHOLDS:raise ValueError('unknown policy')
    c=bundle.characters[actor_id];skill=bundle.skills[c.skill_slots.skill]
    sid=c.skill_slots.basic_attack;reason='basic_only' if policy_id=='basic_only' else 'save_resources'
    if policy_id!='basic_only':
        if skill.effect_type=='heal':
            if lowest_health(state)<THRESHOLDS[policy_id] and state.skill_points>=1:sid=c.skill_slots.skill;reason='heal_threshold'
        else:
            support_alive=any(not state.units[uid].dead and bundle.skills[ch.skill_slots.skill].effect_type=='heal' for uid,ch in bundle.characters.items())
            reserve=int(support_alive and (policy_id=='survival' or lowest_health(state)<THRESHOLDS[policy_id]))
            if state.skill_points-1>=reserve:sid=c.skill_slots.skill;reason='sp_available'
    return ActionRequest(actor_id=actor_id,skill_id=sid,target_ids=targets(bundle,state,actor_id,sid),reason_code=reason)
