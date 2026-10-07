"""Atomic skill effects. Scheduler and policy never mutate resources here."""
import random
from fractions import Fraction
from .contracts import CombatBundle
from .state import BattleState, ActionRequest, BuffInstance, ShieldInstance, fraction
from .trace import EventRecorder
from .scheduler import unit_order


def base_stats(bundle, uid, unit):
    if uid in bundle.characters: return bundle.characters[uid].stats
    if uid==bundle.boss_id:return bundle.boss_stats
    return bundle.enemy_templates[unit.template_id].stats


def refresh_passives(bundle, state, recorder):
    for uid,u in state.units.items():
        st=base_stats(bundle,uid,u); mods={k:Fraction(0) for k in ['ATK','DEF','SPD','CRIT_RATE','CRIT_DAMAGE','DAMAGE']}
        for bid,inst in u.buffs.items():
            definition=bundle.buffs[bid]
            if definition.effect_type=='modifier':mods[definition.stat]+=fraction(definition.modifier_ratio)*inst.stacks
        active=False
        if uid in bundle.characters:
            passive=bundle.characters[uid].passive
            if passive.kind=='ally_low_hp_speed' and not u.dead:
                active=any(not other.dead and other_id!=uid and other.side=='player' and Fraction(other.hp,other.max_hp)<fraction(passive.threshold) for other_id,other in state.units.items())
                if active:mods['SPD']+=fraction(passive.value)
        if uid==bundle.boss_id:mods['ATK']+=fraction(bundle.phases[state.phase_index].enrage.atk_bonus_per_stack)*state.enrage_stacks
        u.atk=max(Fraction(0),st.atk*(1+mods['ATK']))
        u.defense=max(Fraction(0),st.defense*(1+mods['DEF']))
        u.spd=max(Fraction(1),st.spd*(1+mods['SPD']))
        u.crit_rate=max(Fraction(0),min(Fraction(1),fraction(st.crit_rate)+mods['CRIT_RATE']))
        u.crit_damage_bonus=max(Fraction(0),fraction(st.crit_damage_bonus)+mods['CRIT_DAMAGE'])
        u.damage_bonus=max(Fraction(0),fraction(st.damage_bonus)+mods['DAMAGE'])
        if active!=u.speed_passive:
            u.speed_passive=active
            recorder.emit('passive_changed',state,{'active':active,'spd':u.spd},actor_id=uid)


def roll(state, rng, recorder, probability, purpose, actor, target):
    p=max(Fraction(0),min(Fraction(1),fraction(probability)))
    if p in (0,1):return bool(p)
    value=rng.random();state.rng_count+=1
    recorder.emit('rng_draw',state,dict(index=state.rng_count,purpose=purpose,value=value,threshold=p),actor_id=actor,target_id=target)
    return fraction(value)<p


def energy(bundle,state,uid,base,recorder,reason,spend=False):
    if uid not in bundle.characters:return
    u=state.units[uid];before=u.energy
    gained=0 if spend else int(base*(1+fraction(bundle.characters[uid].energy_regen_rate)))
    spent=base if spend else 0
    overflow=max(0,before+gained-spent-u.energy_max)
    u.energy=min(u.energy_max,before+gained-spent)
    recorder.emit('resource_changed',state,dict(resource='energy',before=before,after=u.energy,gained=gained,spent=spent,overflow=overflow,reason=reason),actor_id=uid)


def skill_points(state,gained,spent,recorder,uid,reason):
    before=state.skill_points;overflow=max(0,before+gained-spent-5)
    state.skill_points=min(5,before+gained-spent)
    recorder.emit('resource_changed',state,dict(resource='skill_points',before=before,after=state.skill_points,gained=gained,spent=spent,overflow=overflow,reason=reason),actor_id=uid)


def damage(bundle,state,actor,target,amount,kind,payload,recorder):
    u=state.units[target];left=amount;absorbed=0
    for shield in list(u.shields):
        taken=min(left,shield.value)
        if not taken:continue
        shield.value-=taken;left-=taken;absorbed+=taken
        seq=shield.created_seq
        if shield.value==0:u.shields.remove(shield)
        recorder.emit('shield_absorbed',state,dict(amount=taken,remaining=shield.value,shield_seq=seq),actor_id=actor,target_id=target)
        if shield.value==0:recorder.emit('shield_expired',state,dict(shield_seq=seq,reason='depleted'),target_id=target)
    hp_loss=min(u.hp,left);overkill=max(0,left-u.hp);u.hp-=hp_loss
    u.dead=u.hp==0
    recorder.emit(kind,state,dict(amount=amount,absorbed=absorbed,hp_loss=hp_loss,overkill=overkill,**payload),actor_id=actor,target_id=target)
    if u.dead:recorder.emit('unit_died',state,{},actor_id=actor,target_id=target)
    refresh_passives(bundle,state,recorder)


def apply_status(bundle,state,source,target,buff_id,duration,base_chance,rng,recorder):
    u=state.units[target];definition=bundle.buffs[buff_id]
    if u.dead:return
    if definition.effect_type=='control' and target==bundle.boss_id and bundle.phases[state.phase_index].control_immune:return
    probability=fraction(base_chance)
    if definition.harmful:
        a=base_stats(bundle,source,state.units[source]);b=base_stats(bundle,target,u)
        probability*= (1+fraction(a.effect_hit_rate))*(1-fraction(b.effect_res))
    if not roll(state,rng,recorder,probability,'status:'+buff_id,source,target):return
    old=u.buffs.get(buff_id)
    stacks=min(definition.max_stacks,(old.stacks if old else 0)+1) if definition.stack_behavior=='stack' else 1
    inst=BuffInstance(buff_id=buff_id,source_id=source,remaining=duration,stacks=stacks,attack_snapshot=state.units[source].atk,fresh_turn=state.normal_turn_count if state.current_actor==target else None)
    u.buffs[buff_id]=inst
    recorder.emit('status_applied',state,dict(buff_id=buff_id,duration=duration,stacks=stacks,source_id=source,attack_snapshot=inst.attack_snapshot),actor_id=source,target_id=target)
    refresh_passives(bundle,state,recorder)


def start_statuses(bundle,state,actor_id,rng,recorder):
    u=state.units[actor_id]
    for bid in sorted(u.buffs):
        inst=u.buffs[bid];definition=bundle.buffs[bid]
        if u.dead:break
        if definition.effect_type=='dot':
            amount=int(inst.attack_snapshot*fraction(definition.dot_multiplier)*inst.stacks*200/(u.defense+200))
            damage(bundle,state,inst.source_id,actor_id,amount,'dot_damage',dict(buff_id=bid),recorder)


def remove_status(bundle,state,target,bid,reason,recorder):
    del state.units[target].buffs[bid]
    recorder.emit('status_removed',state,dict(buff_id=bid,reason=reason),target_id=target)
    refresh_passives(bundle,state,recorder)


def end_statuses(bundle,state,actor_id,recorder):
    u=state.units[actor_id]
    for bid in sorted(list(u.buffs)):
        inst=u.buffs[bid]
        if inst.fresh_turn==state.normal_turn_count:continue
        if inst.remaining==1:remove_status(bundle,state,actor_id,bid,'expired',recorder)
        else:inst.remaining-=1
    for sh in list(u.shields):
        if sh.fresh_turn==state.normal_turn_count:continue
        if sh.remaining==1:
            u.shields.remove(sh)
            recorder.emit('shield_expired',state,dict(shield_seq=sh.created_seq,reason='expired'),target_id=actor_id)
        else:sh.remaining-=1


def validate_action(bundle:CombatBundle,state:BattleState,action:ActionRequest)->None:
    uid=action.actor_id
    if uid not in state.units or state.units[uid].dead or state.current_actor!=uid:raise ValueError('actor is not active')
    if action.skill_id not in bundle.skills:raise ValueError('unknown skill')
    u=state.units[uid];skill=bundle.skills[action.skill_id]
    if any(bundle.buffs[bid].effect_type=='control' for bid in u.buffs):raise ValueError('actor controlled')
    if uid in bundle.characters:
        c=bundle.characters[uid]
        if action.skill_id not in c.skill_slots.model_dump().values():raise ValueError('skill not owned')
        if skill.skill_type=='ultimate':
            if state.ultimate_used or state.normal_used or u.energy!=u.energy_max:raise ValueError('ultimate window/energy invalid')
        elif state.normal_used:raise ValueError('normal action already used')
    else:
        if state.normal_used:raise ValueError('enemy action already used')
        if u.charging is not None and action.skill_id != u.charging:raise ValueError('locked charge cannot be replaced')
        allowed=bundle.phases[state.phase_index].skill_pool if uid==bundle.boss_id else [bundle.enemy_templates[u.template_id].skill_id]
        if action.skill_id not in allowed:raise ValueError('enemy skill not owned')
    if skill.sp_cost>state.skill_points:raise ValueError('not enough skill points')
    if len(action.target_ids)!=len(set(action.target_ids)):raise ValueError('duplicate target')
    side=u.side if skill.effect_type in ('heal','shield','summon') else ('enemy' if u.side=='player' else 'player')
    eligible=[tid for tid,t in sorted(state.units.items(),key=unit_order) if not t.dead and t.side==side]
    targets=action.target_ids
    if skill.target=='self':valid=targets==[uid]
    elif skill.target=='all':valid=targets==eligible and bool(eligible)
    else:valid=len(targets)==1 and targets[0] in eligible
    if not valid:raise ValueError('illegal targets')


def begin_action(bundle,state,action,recorder):
    skill=bundle.skills[action.skill_id];uid=action.actor_id
    state.action_count+=1;state.action_id=f'action_{state.action_count:06d}'
    if skill.skill_type=='ultimate':state.ultimate_used=True
    else:state.normal_used=True
    recorder.cause=recorder.emit('decision',state,dict(skill_id=action.skill_id,target_ids=action.target_ids,reason_code=action.reason_code),actor_id=uid)
    if skill.skill_type=='ultimate':energy(bundle,state,uid,state.units[uid].energy_max,recorder,'ultimate',True)
    if skill.sp_cost:skill_points(state,0,skill.sp_cost,recorder,uid,'skill_cost')


def finish_action(bundle,state,action,recorder):
    skill=bundle.skills[action.skill_id]
    if skill.energy_gain:energy(bundle,state,action.actor_id,skill.energy_gain,recorder,'skill_gain')
    if skill.sp_gain:skill_points(state,skill.sp_gain,0,recorder,action.actor_id,'basic_gain')
    recorder.emit('action_finished',state,dict(skill_id=action.skill_id),actor_id=action.actor_id)
    recorder.cause=None


def apply_skill_effects(bundle,state,action,rng,recorder):
    uid=action.actor_id;skill=bundle.skills[action.skill_id];a=state.units[uid]
    for tid in action.target_ids:
        u=state.units[tid]
        if u.dead:continue
        scale={'ATK':a.atk,'HP':a.max_hp,'DEF':a.defense}[skill.scaling_stat]
        if skill.effect_type=='damage':
            crit=roll(state,rng,recorder,a.crit_rate,'critical',uid,tid)
            bonus=a.damage_bonus
            passive=bundle.characters[uid].passive if uid in bundle.characters else None
            if passive and passive.kind=='low_toughness_bonus' and u.toughness_max and Fraction(u.toughness,u.toughness_max)<=fraction(passive.threshold):bonus+=fraction(passive.value)
            amount=int(scale*fraction(skill.multiplier)*(1+bonus)*(1+a.crit_damage_bonus if crit else 1)*200/(u.defense+200))
            damage(bundle,state,uid,tid,amount,'direct_damage',dict(critical=crit,skill_id=action.skill_id,damage_type=skill.damage_type),recorder)
            if not u.dead and amount>0:energy(bundle,state,tid,bundle.characters[tid].energy_gain_on_hit if tid in bundle.characters else 0,recorder,'hit')
            if not u.dead and u.side=='enemy':
                before=u.toughness;matched=skill.damage_type in u.weaknesses
                reduction=min(before,skill.toughness_reduction) if matched and not u.broken else 0
                u.toughness-=reduction
                recorder.emit('toughness_changed',state,dict(before=before,after=u.toughness,reduction=reduction,damage_type=skill.damage_type,matched=matched),actor_id=uid,target_id=tid)
                if before>0 and u.toughness==0:
                    u.broken=True
                    recorder.emit('break_triggered',state,dict(skill_id=action.skill_id,damage_type=skill.damage_type,before=before,after=0),actor_id=uid,target_id=tid)
                    effect=fraction(base_stats(bundle,uid,a).break_effect)
                    damage(bundle,state,uid,tid,int(200*(1+effect)*200/(u.defense+200)),'break_damage',{},recorder)
                    distance=u.remaining_distance;u.remaining_distance+=2500
                    recorder.emit('action_delayed',state,dict(before=distance,after=u.remaining_distance,distance=2500),actor_id=uid,target_id=tid)
                    if u.charging:
                        from .state import cancel_charge
                        sid=u.charging;cancel_charge(state,tid)
                        recorder.emit('charge_cancelled',state,dict(skill_id=sid,reason='break'),target_id=tid)
                    if passive and passive.kind=='break_energy':energy(bundle,state,uid,int(passive.value),recorder,'break_passive')
        elif skill.effect_type=='heal':
            amount=int(scale*fraction(skill.multiplier));restored=min(amount,u.max_hp-u.hp);u.hp+=restored
            recorder.emit('heal',state,dict(amount=amount,restored=restored,overflow=amount-restored,skill_id=action.skill_id),actor_id=uid,target_id=tid)
            if skill.cleanse:
                for bid in sorted(list(u.buffs)):
                    d=bundle.buffs[bid]
                    if d.harmful and d.dispelable:remove_status(bundle,state,tid,bid,'cleanse',recorder)
            refresh_passives(bundle,state,recorder)
        elif skill.effect_type=='shield':
            amount=int(scale*fraction(skill.multiplier));old=next((sh for sh in u.shields if sh.source_id==uid and sh.skill_id==action.skill_id),None)
            seq=old.created_seq if old else state.shield_seq+1
            if old:u.shields.remove(old)
            else:state.shield_seq=seq
            if amount:
                u.shields.append(ShieldInstance(source_id=uid,skill_id=action.skill_id,value=amount,remaining=skill.shield_duration,created_seq=seq,fresh_turn=state.normal_turn_count if state.current_actor==tid else None))
                u.shields.sort(key=lambda sh:sh.created_seq)
            recorder.emit('shield_applied',state,dict(value=amount,duration=skill.shield_duration,skill_id=action.skill_id,refreshed=old is not None),actor_id=uid,target_id=tid)
        for application in skill.applies_buff:
            apply_status(bundle,state,uid,tid,application.buff_id,application.duration,application.base_chance,rng,recorder)


def resolve_action(bundle:CombatBundle,state:BattleState,action:ActionRequest,rng:random.Random,recorder:EventRecorder)->None:
    validate_action(bundle,state,action)
    if bundle.skills[action.skill_id].effect_type=='summon' or bundle.skills[action.skill_id].interruptible:raise ValueError('enemy special action requires boss dispatcher')
    begin_action(bundle,state,action,recorder)
    apply_skill_effects(bundle,state,action,rng,recorder)
    finish_action(bundle,state,action,recorder)
