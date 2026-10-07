# confirm01 — 行动窗口和Boss蓄力轮转评审

候选清理了行动入口和蓄力取消逻辑。请针对玩家动作准入以及Boss被击破后的技能轮转审查。调用方既可能是内置bot，也可能是未来的受控玩家输入；不能用bot当前不发送某类请求代替入口校验。

这是评测专用候选：从真实只读源码构造，可能含benchmark注入修改，也可能无缺陷。它不是对原仓库已有缺陷的断言。各条件获得完全相同的有限资料包。请仅用此包完成评审，不查找隐藏真值或包外文件。

## 业务规则与范围

1. 每个普通回合可先释放至多一个满能终结技，再普通行动；普通行动已用后不能补放终结技。
2. Boss蓄力技能启动时不推进skill_index；正常释放或被击破取消后都消费当前技能槽，下一次从后续槽继续。
3. 进入新阶段的重置由apply_phase_transition处理；本题只审查同一阶段内的准入和蓄力取消。
4. 只报告冻结diff新增的问题；不要求更改bot策略、技能池或新增手动客户端。

## 输出
只返回JSON对象：{"findings":[{"path":"仓库名/相对路径","line":候选行号,"title":"简短标题","why":"根因与业务后果","evidence":"源码链路及具体触发例子","fix":"最小修正建议"}]}。没有问题时findings为空数组。按独立根因合并重复现象，引用下文候选文件行号。证据要能从包内核对；不要填自信度、issue_id或猜测评分规则。

## 冻结候选diff
```diff
--- a/combat-foundation/game-core/combat_core/v2/effects.py
+++ b/combat-foundation/game-core/combat_core/v2/effects.py
@@ -136,7 +136,7 @@
         c=bundle.characters[uid]
         if action.skill_id not in c.skill_slots.model_dump().values():raise ValueError('skill not owned')
         if skill.skill_type=='ultimate':
-            if state.ultimate_used or state.normal_used or u.energy!=u.energy_max:raise ValueError('ultimate window/energy invalid')
+            if state.ultimate_used or u.energy!=u.energy_max:raise ValueError('ultimate window/energy invalid')
         elif state.normal_used:raise ValueError('normal action already used')
     else:
         if state.normal_used:raise ValueError('enemy action already used')
--- a/combat-foundation/game-core/combat_core/v2/state.py
+++ b/combat-foundation/game-core/combat_core/v2/state.py
@@ -92,5 +92,4 @@
     unit=state.units[actor_id]
     if unit.charging is None:return False
     unit.charging=None
-    unit.skill_index+=1
     return True
```


## 相关源码
以下均为应用上述diff后的候选版本；没有出现在diff的文件/行与真实基线相同。行号对应候选完整文件，不是片段内编号。

### combat-foundation/game-core/combat_core/v2/effects.py:127-214
```python
0127 | 
0128 | 
0129 | def validate_action(bundle:CombatBundle,state:BattleState,action:ActionRequest)->None:
0130 |     uid=action.actor_id
0131 |     if uid not in state.units or state.units[uid].dead or state.current_actor!=uid:raise ValueError('actor is not active')
0132 |     if action.skill_id not in bundle.skills:raise ValueError('unknown skill')
0133 |     u=state.units[uid];skill=bundle.skills[action.skill_id]
0134 |     if any(bundle.buffs[bid].effect_type=='control' for bid in u.buffs):raise ValueError('actor controlled')
0135 |     if uid in bundle.characters:
0136 |         c=bundle.characters[uid]
0137 |         if action.skill_id not in c.skill_slots.model_dump().values():raise ValueError('skill not owned')
0138 |         if skill.skill_type=='ultimate':
0139 |             if state.ultimate_used or u.energy!=u.energy_max:raise ValueError('ultimate window/energy invalid')
0140 |         elif state.normal_used:raise ValueError('normal action already used')
0141 |     else:
0142 |         if state.normal_used:raise ValueError('enemy action already used')
0143 |         if u.charging is not None and action.skill_id != u.charging:raise ValueError('locked charge cannot be replaced')
0144 |         allowed=bundle.phases[state.phase_index].skill_pool if uid==bundle.boss_id else [bundle.enemy_templates[u.template_id].skill_id]
0145 |         if action.skill_id not in allowed:raise ValueError('enemy skill not owned')
0146 |     if skill.sp_cost>state.skill_points:raise ValueError('not enough skill points')
0147 |     if len(action.target_ids)!=len(set(action.target_ids)):raise ValueError('duplicate target')
0148 |     side=u.side if skill.effect_type in ('heal','shield','summon') else ('enemy' if u.side=='player' else 'player')
0149 |     eligible=[tid for tid,t in sorted(state.units.items(),key=unit_order) if not t.dead and t.side==side]
0150 |     targets=action.target_ids
0151 |     if skill.target=='self':valid=targets==[uid]
0152 |     elif skill.target=='all':valid=targets==eligible and bool(eligible)
0153 |     else:valid=len(targets)==1 and targets[0] in eligible
0154 |     if not valid:raise ValueError('illegal targets')
0155 | 
0156 | 
0157 | def begin_action(bundle,state,action,recorder):
0158 |     skill=bundle.skills[action.skill_id];uid=action.actor_id
0159 |     state.action_count+=1;state.action_id=f'action_{state.action_count:06d}'
0160 |     if skill.skill_type=='ultimate':state.ultimate_used=True
0161 |     else:state.normal_used=True
0162 |     recorder.cause=recorder.emit('decision',state,dict(skill_id=action.skill_id,target_ids=action.target_ids,reason_code=action.reason_code),actor_id=uid)
0163 |     if skill.skill_type=='ultimate':energy(bundle,state,uid,state.units[uid].energy_max,recorder,'ultimate',True)
0164 |     if skill.sp_cost:skill_points(state,0,skill.sp_cost,recorder,uid,'skill_cost')
0165 | 
0166 | 
0167 | def finish_action(bundle,state,action,recorder):
0168 |     skill=bundle.skills[action.skill_id]
0169 |     if skill.energy_gain:energy(bundle,state,action.actor_id,skill.energy_gain,recorder,'skill_gain')
0170 |     if skill.sp_gain:skill_points(state,skill.sp_gain,0,recorder,action.actor_id,'basic_gain')
0171 |     recorder.emit('action_finished',state,dict(skill_id=action.skill_id),actor_id=action.actor_id)
0172 |     recorder.cause=None
0173 | 
0174 | 
0175 | def apply_skill_effects(bundle,state,action,rng,recorder):
0176 |     uid=action.actor_id;skill=bundle.skills[action.skill_id];a=state.units[uid]
0177 |     for tid in action.target_ids:
0178 |         u=state.units[tid]
0179 |         if u.dead:continue
0180 |         scale={'ATK':a.atk,'HP':a.max_hp,'DEF':a.defense}[skill.scaling_stat]
0181 |         if skill.effect_type=='damage':
0182 |             crit=roll(state,rng,recorder,a.crit_rate,'critical',uid,tid)
0183 |             bonus=a.damage_bonus
0184 |             passive=bundle.characters[uid].passive if uid in bundle.characters else None
0185 |             if passive and passive.kind=='low_toughness_bonus' and u.toughness_max and Fraction(u.toughness,u.toughness_max)<=fraction(passive.threshold):bonus+=fraction(passive.value)
0186 |             amount=int(scale*fraction(skill.multiplier)*(1+bonus)*(1+a.crit_damage_bonus if crit else 1)*200/(u.defense+200))
0187 |             damage(bundle,state,uid,tid,amount,'direct_damage',dict(critical=crit,skill_id=action.skill_id,damage_type=skill.damage_type),recorder)
0188 |             if not u.dead and amount>0:energy(bundle,state,tid,bundle.characters[tid].energy_gain_on_hit if tid in bundle.characters else 0,recorder,'hit')
0189 |             if not u.dead and u.side=='enemy':
0190 |                 before=u.toughness;matched=skill.damage_type in u.weaknesses
0191 |                 reduction=min(before,skill.toughness_reduction) if matched and not u.broken else 0
0192 |                 u.toughness-=reduction
0193 |                 recorder.emit('toughness_changed',state,dict(before=before,after=u.toughness,reduction=reduction,damage_type=skill.damage_type,matched=matched),actor_id=uid,target_id=tid)
0194 |                 if before>0 and u.toughness==0:
0195 |                     u.broken=True
0196 |                     recorder.emit('break_triggered',state,dict(skill_id=action.skill_id,damage_type=skill.damage_type,before=before,after=0),actor_id=uid,target_id=tid)
0197 |                     effect=fraction(base_stats(bundle,uid,a).break_effect)
0198 |                     damage(bundle,state,uid,tid,int(200*(1+effect)*200/(u.defense+200)),'break_damage',{},recorder)
0199 |                     distance=u.remaining_distance;u.remaining_distance+=2500
0200 |                     recorder.emit('action_delayed',state,dict(before=distance,after=u.remaining_distance,distance=2500),actor_id=uid,target_id=tid)
0201 |                     if u.charging:
0202 |                         from .state import cancel_charge
0203 |                         sid=u.charging;cancel_charge(state,tid)
0204 |                         recorder.emit('charge_cancelled',state,dict(skill_id=sid,reason='break'),target_id=tid)
0205 |                     if passive and passive.kind=='break_energy':energy(bundle,state,uid,int(passive.value),recorder,'break_passive')
0206 |         elif skill.effect_type=='heal':
0207 |             amount=int(scale*fraction(skill.multiplier));restored=min(amount,u.max_hp-u.hp);u.hp+=restored
0208 |             recorder.emit('heal',state,dict(amount=amount,restored=restored,overflow=amount-restored,skill_id=action.skill_id),actor_id=uid,target_id=tid)
0209 |             if skill.cleanse:
0210 |                 for bid in sorted(list(u.buffs)):
0211 |                     d=bundle.buffs[bid]
0212 |                     if d.harmful and d.dispelable:remove_status(bundle,state,tid,bid,'cleanse',recorder)
0213 |             refresh_passives(bundle,state,recorder)
0214 |         elif skill.effect_type=='shield':
```

### combat-foundation/game-core/combat_core/v2/state.py:30-95
```python
0030 |     max_hp: Positive
0031 |     energy: Nat = 0
0032 |     energy_max: Nat = 0
0033 |     toughness: Nat = 0
0034 |     toughness_max: Nat = 0
0035 |     weaknesses: list[Element] = Field(default_factory=list)
0036 |     broken: bool = False
0037 |     dead: bool = False
0038 |     side: str
0039 |     slot: Nat
0040 |     template_id: str | None = None
0041 |     remaining_distance: Rational = Fraction(10000)
0042 |     spd: Rational
0043 |     atk: Rational
0044 |     defense: Rational
0045 |     crit_rate: Rational
0046 |     crit_damage_bonus: Rational
0047 |     damage_bonus: Rational = Fraction(0)
0048 |     buffs: dict[str,BuffInstance] = Field(default_factory=dict)
0049 |     shields: list[ShieldInstance] = Field(default_factory=list)
0050 |     charging: str | None = None
0051 |     skill_index: Nat = 0
0052 |     speed_passive: bool = False
0053 | 
0054 | class ActionRequest(Model):
0055 |     actor_id: Identifier
0056 |     skill_id: Identifier
0057 |     target_ids: list[Identifier]
0058 |     reason_code: str
0059 | 
0060 | class BattleState(Model):
0061 |     units: dict[str,UnitState]
0062 |     skill_points: Nat
0063 |     elapsed_av: Rational = Fraction(0)
0064 |     phase_index: Nat = 0
0065 |     phase_action_count: Nat = 0
0066 |     enrage_stacks: Nat = 0
0067 |     normal_turn_count: Nat = 0
0068 |     action_count: Nat = 0
0069 |     current_actor: str | None = None
0070 |     action_id: str | None = None
0071 |     ultimate_used: bool = False
0072 |     normal_used: bool = False
0073 |     shield_seq: Nat = 0
0074 |     summon_seq: Nat = 0
0075 |     rng_count: Nat = 0
0076 | 
0077 | def make_unit(stats, side, slot, **kwargs):
0078 |     return UnitState(hp=stats.hp,max_hp=stats.hp,side=side,slot=slot,spd=stats.spd,atk=stats.atk,defense=stats.defense,crit_rate=stats.crit_rate,crit_damage_bonus=stats.crit_damage_bonus,damage_bonus=stats.damage_bonus,**kwargs)
0079 | 
0080 | def initial_state(bundle: CombatBundle, scenario: Scenario) -> BattleState:
0081 |     if set(scenario.initial_energy)-set(bundle.party): raise ValueError('unknown initial energy owner')
0082 |     units={}
0083 |     for slot,uid in enumerate(bundle.party):
0084 |         c=bundle.characters[uid]; energy=scenario.initial_energy.get(uid,0)
0085 |         if energy>c.energy_max: raise ValueError('initial energy exceeds maximum')
0086 |         units[uid]=make_unit(c.stats,'player',slot,energy_max=c.energy_max,energy=energy)
0087 |     phase=bundle.phases[0]
0088 |     units[bundle.boss_id]=make_unit(bundle.boss_stats,'enemy',0,toughness=phase.toughness_max,toughness_max=phase.toughness_max,weaknesses=phase.weaknesses)
0089 |     return BattleState(units=units,skill_points=scenario.initial_skill_points)
0090 | 
0091 | def cancel_charge(state: BattleState, actor_id: str) -> bool:
0092 |     unit=state.units[actor_id]
0093 |     if unit.charging is None:return False
0094 |     unit.charging=None
0095 |     return True
```

### combat-foundation/game-core/combat_core/v2/boss.py:1-86
```python
0001 | """Enemy turn/phase state machine; generic effects live in effects.py."""
0002 | from fractions import Fraction
0003 | from .state import ActionRequest,make_unit,fraction
0004 | from .scheduler import unit_order
0005 | from .effects import refresh_passives,remove_status,validate_action,begin_action,finish_action,apply_skill_effects
0006 | 
0007 | 
0008 | def apply_phase_transition(bundle,state,recorder):
0009 |     boss=state.units[bundle.boss_id]
0010 |     if boss.dead:return
0011 |     final=state.phase_index
0012 |     for i in range(final+1,len(bundle.phases)):
0013 |         if Fraction(boss.hp,boss.max_hp)<=fraction(bundle.phases[i].hp_threshold):final=i
0014 |     if final==state.phase_index:return
0015 |     previous=state.phase_index
0016 |     for i in range(previous+1,final+1):
0017 |         entered=i==final
0018 |         if entered:
0019 |             state.phase_index=final;phase=bundle.phases[final]
0020 |             boss.toughness_max=phase.toughness_max;boss.toughness=phase.toughness_max
0021 |             boss.weaknesses=list(phase.weaknesses);boss.broken=False
0022 |             boss.charging=None;boss.skill_index=0
0023 |             state.phase_action_count=0;state.enrage_stacks=0
0024 |             if phase.control_immune:
0025 |                 for bid in sorted(list(boss.buffs)):
0026 |                     if bundle.buffs[bid].effect_type=='control':remove_status(bundle,state,bundle.boss_id,bid,'phase_immunity',recorder)
0027 |             refresh_passives(bundle,state,recorder)
0028 |         recorder.emit('phase_changed',state,dict(from_phase=bundle.phases[i-1].phase_id,to_phase=bundle.phases[i].phase_id,entered=entered,reason='hp_threshold',weaknesses=bundle.phases[i].weaknesses),target_id=bundle.boss_id)
0029 | 
0030 | 
0031 | def begin_enemy_turn(bundle,state,actor_id,recorder):
0032 |     u=state.units[actor_id]
0033 |     if u.broken:
0034 |         u.broken=False;u.toughness=u.toughness_max
0035 |         recorder.emit('toughness_restored',state,dict(value=u.toughness,reason='turn_start'),target_id=actor_id)
0036 |     if actor_id==bundle.boss_id:
0037 |         state.phase_action_count+=1
0038 |         if state.phase_action_count>bundle.phases[state.phase_index].enrage.trigger_actions:
0039 |             state.enrage_stacks+=1
0040 |             refresh_passives(bundle,state,recorder)
0041 |             recorder.emit('enrage_changed',state,dict(stacks=state.enrage_stacks),actor_id=actor_id)
0042 | 
0043 | 
0044 | def enemy_targets(bundle,state,actor_id,skill_id):
0045 |     skill=bundle.skills[skill_id]
0046 |     if skill.target=='self':return [actor_id]
0047 |     live=[(uid,u) for uid,u in state.units.items() if not u.dead and u.side=='player']
0048 |     if skill.target=='all':return [uid for uid,u in sorted(live,key=unit_order)]
0049 |     return [min(live,key=lambda item:(Fraction(item[1].hp,item[1].max_hp),unit_order(item)))[0]] if live else []
0050 | 
0051 | 
0052 | def choose_enemy_action(bundle,state,actor_id):
0053 |     u=state.units[actor_id]
0054 |     if actor_id==bundle.boss_id:
0055 |         pool=bundle.phases[state.phase_index].skill_pool
0056 |         skill_id=u.charging or pool[u.skill_index%len(pool)]
0057 |     else:skill_id=bundle.enemy_templates[u.template_id].skill_id
0058 |     return ActionRequest(actor_id=actor_id,skill_id=skill_id,target_ids=enemy_targets(bundle,state,actor_id,skill_id),reason_code='enemy_cycle')
0059 | 
0060 | 
0061 | def resolve_enemy_action(bundle,state,action,rng,recorder):
0062 |     validate_action(bundle,state,action)
0063 |     uid=action.actor_id;u=state.units[uid];skill=bundle.skills[action.skill_id]
0064 |     begin_action(bundle,state,action,recorder)
0065 |     advance=True
0066 |     if skill.effect_type=='summon':
0067 |         count=sum(not other.dead and other.template_id is not None for other in state.units.values())
0068 |         if count>=bundle.rules.max_adds:
0069 |             recorder.emit('summon_fallback',state,dict(skill_id=action.skill_id,fallback_skill=skill.fallback_skill,reason='max_adds'),actor_id=uid)
0070 |             fallback=ActionRequest(actor_id=uid,skill_id=skill.fallback_skill,target_ids=enemy_targets(bundle,state,uid,skill.fallback_skill),reason_code='summon_cap')
0071 |             apply_skill_effects(bundle,state,fallback,rng,recorder)
0072 |         else:
0073 |             state.summon_seq+=1;new_id=f'{skill.summon_template}_01_{state.summon_seq:04d}'
0074 |             template=bundle.enemy_templates[skill.summon_template]
0075 |             state.units[new_id]=make_unit(template.stats,'enemy',state.summon_seq,template_id=skill.summon_template,toughness=template.toughness_max,toughness_max=template.toughness_max,weaknesses=list(template.weaknesses))
0076 |             recorder.emit('summoned',state,dict(template_id=skill.summon_template,unit_id=new_id),actor_id=uid,target_id=new_id)
0077 |     elif skill.interruptible and u.charging is None:
0078 |         u.charging=action.skill_id;advance=False
0079 |         recorder.emit('charge_started',state,dict(skill_id=action.skill_id),actor_id=uid)
0080 |     else:
0081 |         if u.charging:
0082 |             u.charging=None
0083 |             recorder.emit('charge_released',state,dict(skill_id=action.skill_id),actor_id=uid)
0084 |         apply_skill_effects(bundle,state,action,rng,recorder)
0085 |     if advance:u.skill_index+=1
0086 |     finish_action(bundle,state,action,recorder)
```

### combat-foundation/game-core/combat_core/v2/bots.py:1-46
```python
0001 | """Policies inspect current public state only. No RNG or future simulation."""
0002 | from fractions import Fraction
0003 | from .state import ActionRequest,fraction
0004 | from .scheduler import unit_order
0005 | 
0006 | THRESHOLDS={'balanced':Fraction(7,10),'survival':Fraction(85,100),'basic_only':Fraction(0)}
0007 | 
0008 | def lowest_health(state):
0009 |     return min((Fraction(u.hp,u.max_hp) for u in state.units.values() if u.side=='player' and not u.dead),default=Fraction(1))
0010 | 
0011 | def targets(bundle,state,actor_id,skill_id):
0012 |     skill=bundle.skills[skill_id]
0013 |     if skill.target=='self':return [actor_id]
0014 |     side='player' if skill.effect_type in ('heal','shield') else 'enemy'
0015 |     live=[item for item in state.units.items() if item[1].side==side and not item[1].dead]
0016 |     if skill.target=='all':return [uid for uid,u in sorted(live,key=unit_order)]
0017 |     character=bundle.characters[actor_id]
0018 |     if character.passive.kind!='low_toughness_bonus':
0019 |         matching=[item for item in live if not item[1].broken and skill.damage_type in item[1].weaknesses]
0020 |         if matching:return [min(matching,key=lambda item:(item[1].toughness,item[0]!=bundle.boss_id,unit_order(item)))[0]]
0021 |     return [min(live,key=lambda item:(item[0]!=bundle.boss_id,unit_order(item)))[0]] if live else []
0022 | 
0023 | def choose_ultimate(bundle,state,actor_id,policy_id):
0024 |     if policy_id not in THRESHOLDS:raise ValueError('unknown policy')
0025 |     c=bundle.characters[actor_id];u=state.units[actor_id]
0026 |     if policy_id=='basic_only' or u.dead or u.energy!=u.energy_max or state.ultimate_used or state.normal_used:return None
0027 |     if any(bundle.buffs[bid].effect_type=='control' for bid in u.buffs):return None
0028 |     sid=c.skill_slots.ultimate;skill=bundle.skills[sid]
0029 |     if skill.effect_type=='shield':
0030 |         scale={'ATK':u.atk,'HP':u.max_hp,'DEF':u.defense}[skill.scaling_stat]
0031 |         value=int(scale*fraction(skill.multiplier))
0032 |         if not any(sum(sh.value for sh in t.shields)<Fraction(value,2) for t in state.units.values() if t.side=='player' and not t.dead):return None
0033 |     return ActionRequest(actor_id=actor_id,skill_id=sid,target_ids=targets(bundle,state,actor_id,sid),reason_code='shield_needed' if skill.effect_type=='shield' else 'full_energy')
0034 | 
0035 | def choose_normal_action(bundle,state,actor_id,policy_id):
0036 |     if policy_id not in THRESHOLDS:raise ValueError('unknown policy')
0037 |     c=bundle.characters[actor_id];skill=bundle.skills[c.skill_slots.skill]
0038 |     sid=c.skill_slots.basic_attack;reason='basic_only' if policy_id=='basic_only' else 'save_resources'
0039 |     if policy_id!='basic_only':
0040 |         if skill.effect_type=='heal':
0041 |             if lowest_health(state)<THRESHOLDS[policy_id] and state.skill_points>=1:sid=c.skill_slots.skill;reason='heal_threshold'
0042 |         else:
0043 |             support_alive=any(not state.units[uid].dead and bundle.skills[ch.skill_slots.skill].effect_type=='heal' for uid,ch in bundle.characters.items())
0044 |             reserve=int(support_alive and (policy_id=='survival' or lowest_health(state)<THRESHOLDS[policy_id]))
0045 |             if state.skill_points-1>=reserve:sid=c.skill_slots.skill;reason='sp_available'
0046 |     return ActionRequest(actor_id=actor_id,skill_id=sid,target_ids=targets(bundle,state,actor_id,sid),reason_code=reason)
```

### combat-foundation/game-core/combat_core/v2/simulation.py:35-67
```python
0035 |         delta=min(u.remaining_distance/u.spd for u in state.units.values() if not u.dead)
0036 |         if state.elapsed_av+delta>scenario.limits.elapsed_av:
0037 |             advance_time(state,Fraction(scenario.limits.elapsed_av)-state.elapsed_av)
0038 |             result='timeout';reason='av_limit';break
0039 |         actor=next_actor(state);state.current_actor=actor;state.normal_turn_count+=1
0040 |         state.ultimate_used=False;state.normal_used=False;state.action_id=None
0041 |         rec.emit('turn_started',state,{},actor_id=actor)
0042 |         u=state.units[actor]
0043 |         if u.side=='enemy':begin_enemy_turn(bundle,state,actor,rec)
0044 |         start_statuses(bundle,state,actor,rng,rec)
0045 |         result=outcome(bundle,state)
0046 |         if result:reason='boss_dead' if result=='win' else 'party_dead';break
0047 |         apply_phase_transition(bundle,state,rec)
0048 |         if not u.dead:
0049 |             controlled=any(bundle.buffs[bid].effect_type=='control' for bid in u.buffs)
0050 |             if controlled:rec.emit('control_skipped',state,{},actor_id=actor)
0051 |             else:
0052 |                 if u.side=='player':
0053 |                     ultimate=choose_ultimate(bundle,state,actor,scenario.strategy)
0054 |                     if ultimate:
0055 |                         resolve_action(bundle,state,ultimate,rng,rec)
0056 |                         result=outcome(bundle,state)
0057 |                         if result:reason='boss_dead' if result=='win' else 'party_dead';break
0058 |                         apply_phase_transition(bundle,state,rec)
0059 |                         if state.action_count>=scenario.limits.actions:result='timeout';reason='action_limit';break
0060 |                     resolve_action(bundle,state,choose_normal_action(bundle,state,actor,scenario.strategy),rng,rec)
0061 |                 else:resolve_enemy_action(bundle,state,choose_enemy_action(bundle,state,actor),rng,rec)
0062 |                 result=outcome(bundle,state)
0063 |                 if result:reason='boss_dead' if result=='win' else 'party_dead';break
0064 |                 apply_phase_transition(bundle,state,rec)
0065 |         end_statuses(bundle,state,actor,rec)
0066 |         finish_turn(state,actor)
0067 |         rec.emit('turn_finished',state,{},actor_id=actor)
```
