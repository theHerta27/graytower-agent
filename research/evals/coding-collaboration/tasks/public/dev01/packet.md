# dev01 — 护盾与战斗快照跨层评审

我们想减少战斗Trace的快照分配，并简化Unity护盾展示和回合末维护。请审查冻结候选，判断是否仍满足护盾持续期、事件历史不可变和回放显示要求。只报候选新增的可行动问题，不把建议重构当缺陷。

这是评测专用候选：从真实只读源码构造，可能含benchmark注入修改，也可能无缺陷。它不是对原仓库已有缺陷的断言。各条件获得完全相同的有限资料包。请仅用此包完成评审，不查找隐藏真值或包外文件。

## 业务规则与范围

1. Python是唯一结算权威；每个事件的state_after必须保存发出时的完整独立状态，后续伤害和状态到期不能改写历史事件。
2. 护盾由不同来源叠加，显示值是当前全部有效护盾的value之和；空护盾显示0。
3. remaining按持有者普通回合结束结算；当护盾在持有者当前普通回合中创建时，该回合结束不消耗持续期。终结技本身不额外推进普通回合。
4. 此题不要求设计战前支援新功能；只判断现有护盾/快照链路。Unity仅从权威快照加载和显示。

## 输出
只返回JSON对象：{"findings":[{"path":"仓库名/相对路径","line":候选行号,"title":"简短标题","why":"根因与业务后果","evidence":"源码链路及具体触发例子","fix":"最小修正建议"}]}。没有问题时findings为空数组。按独立根因合并重复现象，引用下文候选文件行号。证据要能从包内核对；不要填自信度、issue_id或猜测评分规则。

## 冻结候选diff
```diff
--- a/combat-foundation/game-core/combat_core/v2/effects.py
+++ b/combat-foundation/game-core/combat_core/v2/effects.py
@@ -119,7 +119,6 @@
         if inst.remaining==1:remove_status(bundle,state,actor_id,bid,'expired',recorder)
         else:inst.remaining-=1
     for sh in list(u.shields):
-        if sh.fresh_turn==state.normal_turn_count:continue
         if sh.remaining==1:
             u.shields.remove(sh)
             recorder.emit('shield_expired',state,dict(shield_seq=sh.created_seq,reason='expired'),target_id=actor_id)
--- a/combat-foundation/game-core/combat_core/v2/trace.py
+++ b/combat-foundation/game-core/combat_core/v2/trace.py
@@ -113,7 +113,7 @@
         if kind not in EVENT_MODELS: raise ValueError('unknown event kind')
         cause=cause_event_id if cause_event_id is not None else self.cause
         if cause is not None and not any(e.event_id==cause for e in self.events): raise ValueError('unknown cause')
-        event=EVENT_MODELS[kind](kind=kind,event_id=f'event_{len(self.events)+1:06d}',turn_id=state.normal_turn_count,action_id=state.action_id,actor_id=actor_id,target_id=target_id,av=state.elapsed_av,cause_event_id=cause,payload=payload,state_after=state.model_copy(deep=True))
+        event=EVENT_MODELS[kind](kind=kind,event_id=f'event_{len(self.events)+1:06d}',turn_id=state.normal_turn_count,action_id=state.action_id,actor_id=actor_id,target_id=target_id,av=state.elapsed_av,cause_event_id=cause,payload=payload,state_after=state.model_copy(deep=False))
         self.events.append(event)
         return event.event_id
 
--- a/combat-foundation/game-unity/Assets/Runtime/CombatUnitView.cs
+++ b/combat-foundation/game-unity/Assets/Runtime/CombatUnitView.cs
@@ -11,7 +11,7 @@
     public int Hp { get { return V2State==null?hp:V2State.hp; } set { if(V2State==null) hp=value; else V2State.hp=value; } }
     public int Toughness { get { return V2State==null?toughness:V2State.toughness; } set { if(V2State==null) toughness=value; else V2State.toughness=value; } }
     public int Energy { get { return V2State==null?energy:V2State.energy; } set { if(V2State==null) energy=value; else V2State.energy=value; } }
-    public int Shield { get { return V2State==null?shield:V2State.shields.Sum(x=>x.value); } }
+    public int Shield { get { return V2State==null?shield:V2State.shields.Select(x=>x.value).DefaultIfEmpty(0).Max(); } }
     public int EnergyMax { get { return V2State==null?100:V2State.energy_max; } }
     public bool Broken { get { return V2State!=null && V2State.broken; } }
     public string Id { get; private set; }
```


## 相关源码
以下均为应用上述diff后的候选版本；没有出现在diff的文件/行与真实基线相同。行号对应候选完整文件，不是片段内编号。

### combat-foundation/game-core/combat_core/v2/effects.py:110-127
```python
0110 |     recorder.emit('status_removed',state,dict(buff_id=bid,reason=reason),target_id=target)
0111 |     refresh_passives(bundle,state,recorder)
0112 | 
0113 | 
0114 | def end_statuses(bundle,state,actor_id,recorder):
0115 |     u=state.units[actor_id]
0116 |     for bid in sorted(list(u.buffs)):
0117 |         inst=u.buffs[bid]
0118 |         if inst.fresh_turn==state.normal_turn_count:continue
0119 |         if inst.remaining==1:remove_status(bundle,state,actor_id,bid,'expired',recorder)
0120 |         else:inst.remaining-=1
0121 |     for sh in list(u.shields):
0122 |         if sh.remaining==1:
0123 |             u.shields.remove(sh)
0124 |             recorder.emit('shield_expired',state,dict(shield_seq=sh.created_seq,reason='expired'),target_id=actor_id)
0125 |         else:sh.remaining-=1
0126 | 
0127 | 
```

### combat-foundation/game-core/combat_core/v2/effects.py:222-231
```python
0222 |         for application in skill.applies_buff:
0223 |             apply_status(bundle,state,uid,tid,application.buff_id,application.duration,application.base_chance,rng,recorder)
0224 | 
0225 | 
0226 | def resolve_action(bundle:CombatBundle,state:BattleState,action:ActionRequest,rng:random.Random,recorder:EventRecorder)->None:
0227 |     validate_action(bundle,state,action)
0228 |     if bundle.skills[action.skill_id].effect_type=='summon' or bundle.skills[action.skill_id].interruptible:raise ValueError('enemy special action requires boss dispatcher')
0229 |     begin_action(bundle,state,action,recorder)
0230 |     apply_skill_effects(bundle,state,action,rng,recorder)
0231 |     finish_action(bundle,state,action,recorder)
```

### combat-foundation/game-core/combat_core/v2/state.py:1-82
```python
0001 | from fractions import Fraction
0002 | from typing import Annotated
0003 | from pydantic import Field, BeforeValidator, PlainSerializer
0004 | from .contracts import Model, Nat, Positive, Identifier, Element, CombatBundle, Scenario
0005 | 
0006 | def fraction(value):
0007 |     try: return Fraction(str(value))
0008 |     except (ValueError, ZeroDivisionError): raise ValueError('invalid rational') from None
0009 | 
0010 | Rational = Annotated[Fraction, BeforeValidator(fraction), PlainSerializer(lambda v:str(v),return_type=str)]
0011 | 
0012 | class BuffInstance(Model):
0013 |     buff_id: Identifier
0014 |     source_id: Identifier
0015 |     remaining: Positive
0016 |     stacks: Positive = 1
0017 |     attack_snapshot: Rational
0018 |     fresh_turn: int | None = None
0019 | 
0020 | class ShieldInstance(Model):
0021 |     source_id: Identifier
0022 |     skill_id: Identifier
0023 |     value: Positive
0024 |     remaining: Positive
0025 |     created_seq: Positive
0026 |     fresh_turn: int | None = None
0027 | 
0028 | class UnitState(Model):
0029 |     hp: Nat
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
```

### combat-foundation/game-core/combat_core/v2/trace.py:1-60
```python
0001 | """Typed event evidence. Every kind has a closed payload schema."""
0002 | from typing import Annotated, Literal, Union
0003 | from pydantic import Field, create_model, model_validator
0004 | from .contracts import Model, Nat
0005 | from .state import BattleState, Rational
0006 | 
0007 | PAYLOADS = {
0008 | 'battle_started': {},
0009 | ' turn_started': {},
0010 | 'decision': {'skill_id':str,'target_ids':list[str],'reason_code':str},
0011 | 'resource_changed': {'resource':Literal['energy','skill_points'],'before':Nat,'after':Nat,'gained':Nat,'spent':Nat,'overflow':Nat,'reason':str},
0012 | 'direct_damage': {'amount':Nat,'absorbed':Nat,'hp_loss':Nat,'overkill':Nat,'critical':bool,'skill_id':str,'damage_type':str},
0013 | 'heal': {'amount':Nat,'restored':Nat,'overflow':Nat,'skill_id':str},
0014 | 'shield_applied': {'value':Nat,'duration':Nat,'skill_id':str,'refreshed':bool},
0015 | 'shield_absorbed': {'amount':Nat,'remaining':Nat,'shield_seq':Nat},
0016 | 'shield_expired': {'shield_seq':Nat,'reason':str},
0017 | 'status_applied': {'buff_id':str,'duration':Nat,'stacks':Nat,'source_id':str,'attack_snapshot':Rational},
0018 | 'status_removed': {'buff_id':str,'reason':str},
0019 | 'dot_damage': {'amount':Nat,'absorbed':Nat,'hp_loss':Nat,'overkill':Nat,'buff_id':str},
0020 | ' toughness_changed': {'before':Nat,'after':Nat,'reduction':Nat,'damage_type':str,'matched':bool},
0021 | 'break_triggered': {'skill_id':str,'damage_type':str,'before':Nat,'after':Literal[0]},
0022 | 'break_damage': {'amount':Nat,'absorbed':Nat,'hp_loss':Nat,'overkill':Nat},
0023 | 'action_delayed': {'before':Rational,'after':Rational,'distance':Nat},
0024 | 'toughness_restored': {'value':Nat,'reason':str},
0025 | 'charge_started': {'skill_id':str},
0026 | 'charge_cancelled': {'skill_id':str,'reason':str},
0027 | 'charge_released': {'skill_id':str},
0028 | 'summoned': {'template_id':str,'unit_id':str},
0029 | 'summon_fallback': {'skill_id':str,'fallback_skill':str,'reason':str},
0030 | 'unit_died': {},
0031 | 'passive_changed': {'active':bool,'spd':Rational},
0032 | 'rng_draw': {'index':Nat,'purpose':str,'value':float,'threshold':Rational},
0033 | 'phase_changed': {'from_phase':str,'to_phase':str,'entered':bool,'reason':str,'weaknesses':list[str]},
0034 | 'enrage_changed': {'stacks':Nat},
0035 | 'control_skipped': {},
0036 | 'action_finished': {'skill_id':str},
0037 | 'turn_finished': {},
0038 | 'battle_finished': {'outcome':Literal['win','loss','timeout'],'reason':str},
0039 | }
0040 | PAYLOADS={k.strip():v for k,v in PAYLOADS.items()}
0041 | 
0042 | class EventBase(Model):
0043 |     event_id: str
0044 |     turn_id: Nat
0045 |     action_id: str | None
0046 |     actor_id: str | None
0047 |     target_id: str | None
0048 |     av: Rational
0049 |     cause_event_id: str | None
0050 |     state_after: BattleState
0051 | 
0052 | EVENT_MODELS={}
0053 | for kind,fields in PAYLOADS.items():
0054 |     payload=create_model(kind.title().replace('_','')+'Payload',__base__=Model,**{k:(v,...) for k,v in fields.items()})
0055 |     EVENT_MODELS[kind]=create_model(kind.title().replace('_','')+'Event',__base__=EventBase,kind=(Literal[kind],...),payload=(payload,...))
0056 | Event = Annotated[Union[tuple(EVENT_MODELS.values())], Field(discriminator='kind')]
0057 | 
0058 | class Result(Model):
0059 |     outcome: Literal['win','loss','timeout']
0060 |     reason: str
```

### combat-foundation/game-core/combat_core/v2/trace.py:108-123
```python
0108 | class EventRecorder:
0109 |     def __init__(self):
0110 |         self.events=[]
0111 |         self.cause=None
0112 |     def emit(self, kind: str, state: BattleState, payload: dict, *, actor_id=None, target_id=None, cause_event_id=None) -> str:
0113 |         if kind not in EVENT_MODELS: raise ValueError('unknown event kind')
0114 |         cause=cause_event_id if cause_event_id is not None else self.cause
0115 |         if cause is not None and not any(e.event_id==cause for e in self.events): raise ValueError('unknown cause')
0116 |         event=EVENT_MODELS[kind](kind=kind,event_id=f'event_{len(self.events)+1:06d}',turn_id=state.normal_turn_count,action_id=state.action_id,actor_id=actor_id,target_id=target_id,av=state.elapsed_av,cause_event_id=cause,payload=payload,state_after=state.model_copy(deep=False))
0117 |         self.events.append(event)
0118 |         return event.event_id
0119 | 
0120 | class ComparisonResult(Model):
0121 |     passed: bool
0122 |     first_difference_path: str | None = None
0123 |     expected: object = None
```

### combat-foundation/game-core/combat_core/v2/simulation.py:21-69
```python
0021 | def simulate(bundle:CombatBundle,scenario:Scenario)->CombatTrace:
0022 |     # Revalidate even caller-constructed models; model_copy updates can bypass validation.
0023 |     bundle=CombatBundle.model_validate(bundle.model_dump())
0024 |     scenario=Scenario.model_validate(scenario.model_dump())
0025 |     state=initial_state(bundle,scenario);initial=state.model_copy(deep=True)
0026 |     rec=EventRecorder();rng=random.Random(scenario.seed)
0027 |     rec.emit('battle_started',state,{})
0028 |     result=None;reason=''
0029 |     while result is None:
0030 |         assert_invariants(state)
0031 |         result=outcome(bundle,state)
0032 |         if result:reason='boss_dead' if result=='win' else 'party_dead';break
0033 |         if state.normal_turn_count>=scenario.limits.normal_turns:result='timeout';reason='normal_turn_limit';break
0034 |         if state.action_count>=scenario.limits.actions:result='timeout';reason='action_limit';break
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
0068 |     assert_invariants(state)
0069 |     rec.cause=None
```

### combat-foundation/game-unity/Assets/Runtime/CombatUnitView.cs:1-20
```csharp
0001 | using Newtonsoft.Json.Linq;
0002 | using System.Linq;
0003 | using UnityEngine;
0004 | 
0005 | // Authoritative fields are independent of visual animation transforms.
0006 | public sealed class CombatUnitView : MonoBehaviour
0007 | {
0008 |     JObject metadata;
0009 |     int hp,toughness,shield,energy;
0010 |     public UnitSnapshotV2 V2State { get; private set; }
0011 |     public int Hp { get { return V2State==null?hp:V2State.hp; } set { if(V2State==null) hp=value; else V2State.hp=value; } }
0012 |     public int Toughness { get { return V2State==null?toughness:V2State.toughness; } set { if(V2State==null) toughness=value; else V2State.toughness=value; } }
0013 |     public int Energy { get { return V2State==null?energy:V2State.energy; } set { if(V2State==null) energy=value; else V2State.energy=value; } }
0014 |     public int Shield { get { return V2State==null?shield:V2State.shields.Select(x=>x.value).DefaultIfEmpty(0).Max(); } }
0015 |     public int EnergyMax { get { return V2State==null?100:V2State.energy_max; } }
0016 |     public bool Broken { get { return V2State!=null && V2State.broken; } }
0017 |     public string Id { get; private set; }
0018 |     public string Side { get { return (string)metadata["side"]; } }
0019 |     public int Slot { get { return (int)metadata["slot"]; } }
0020 |     public int MaxHp { get { return (int)metadata["max_hp"]; } }
```

### combat-foundation/game-unity/Assets/Runtime/CombatUnitView.cs:41-65
```csharp
0041 |     }
0042 |     public void Load(JObject state)
0043 |     {
0044 |         metadata=(JObject)state.DeepClone();
0045 |         V2State=state["shields"]!=null ? state.ToObject<UnitSnapshotV2>() : null;
0046 |         if(V2State==null) { Hp=(int)state["hp"]; Toughness=(int)state["toughness"]; shield=(int)state["shield"]; Energy=(int)state["energy"]; }
0047 |         Refresh();
0048 |     }
0049 |     public void Refresh() { if(body!=null) body.material.color=Hp<=0 ? color*.2f : color; }
0050 |     public void Pulse(bool damage) { pulse=.25f; hurt=damage; }
0051 |     void Update()
0052 |     {
0053 |         if(figure==null) return;
0054 |         pulse=Mathf.Max(0,pulse-Time.unscaledDeltaTime);
0055 |         figure.localPosition=new Vector3(hurt ? Mathf.Sin(pulse*80)*pulse*.25f : 0,pulse*.25f,0);
0056 |         body.material.color=pulse>0 ? Color.Lerp(color,Color.white,pulse*2) : Hp<=0 ? color*.2f : color;
0057 |     }
0058 |     void OnDestroy() { foreach(var renderer in GetComponentsInChildren<Renderer>()) Destroy(renderer.material); }
0059 |     public JObject Export()
0060 |     {
0061 |         if(V2State!=null) return JObject.FromObject(V2State);
0062 |         var result=(JObject)metadata.DeepClone(); result["hp"]=Hp; result["toughness"]=Toughness;
0063 |         result["shield"]=Shield; result["energy"]=Energy; return result;
0064 |     }
0065 | }
```

### combat-foundation/game-unity/Assets/Runtime/CombatStateV2.cs:9-41
```csharp
0009 | // Typed replay state, deliberately independent of the input JObject and of combat rules.
0010 | [JsonObject(MemberSerialization.Fields)]
0011 | public sealed class BuffSnapshotV2
0012 | {
0013 |     [JsonProperty(Required=Required.Always)] public string buff_id, source_id, attack_snapshot;
0014 |     [JsonProperty(Required=Required.Always)] public int remaining, stacks;
0015 |     [JsonProperty(Required=Required.AllowNull)] public int? fresh_turn;
0016 | }
0017 | [JsonObject(MemberSerialization.Fields)]
0018 | public sealed class ShieldSnapshotV2
0019 | {
0020 |     [JsonProperty(Required=Required.Always)] public string source_id, skill_id;
0021 |     [JsonProperty(Required=Required.Always)] public int value, remaining, created_seq;
0022 |     [JsonProperty(Required=Required.AllowNull)] public int? fresh_turn;
0023 | }
0024 | [JsonObject(MemberSerialization.Fields)]
0025 | public sealed class UnitSnapshotV2
0026 | {
0027 |     [JsonProperty(Required=Required.Always)] public int hp, max_hp, energy, energy_max, toughness, toughness_max, slot, skill_index;
0028 |     [JsonProperty(Required=Required.Always)] public bool broken, dead, speed_passive;
0029 |     [JsonProperty(Required=Required.Always)] public string side, remaining_distance, spd, atk, defense, crit_rate, crit_damage_bonus, damage_bonus;
0030 |     [JsonProperty(Required=Required.AllowNull)] public string template_id, charging;
0031 |     [JsonProperty(Required=Required.Always)] public List<string> weaknesses;
0032 |     [JsonProperty(Required=Required.Always)] public Dictionary<string,BuffSnapshotV2> buffs;
0033 |     [JsonProperty(Required=Required.Always)] public List<ShieldSnapshotV2> shields;
0034 | }
0035 | [JsonObject(MemberSerialization.Fields)]
0036 | public sealed class BattleSnapshotV2
0037 | {
0038 |     [JsonProperty(Required=Required.Always)] public Dictionary<string,UnitSnapshotV2> units;
0039 |     [JsonProperty(Required=Required.Always)] public int skill_points, phase_index, phase_action_count, enrage_stacks, normal_turn_count, action_count, shield_seq, summon_seq, rng_count;
0040 |     [JsonProperty(Required=Required.Always)] public string elapsed_av;
0041 |     [JsonProperty(Required=Required.AllowNull)] public string current_actor, action_id;
```
