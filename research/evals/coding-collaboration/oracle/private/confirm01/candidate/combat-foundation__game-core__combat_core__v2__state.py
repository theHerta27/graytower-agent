from fractions import Fraction
from typing import Annotated
from pydantic import Field, BeforeValidator, PlainSerializer
from .contracts import Model, Nat, Positive, Identifier, Element, CombatBundle, Scenario

def fraction(value):
    try: return Fraction(str(value))
    except (ValueError, ZeroDivisionError): raise ValueError('invalid rational') from None

Rational = Annotated[Fraction, BeforeValidator(fraction), PlainSerializer(lambda v:str(v),return_type=str)]

class BuffInstance(Model):
    buff_id: Identifier
    source_id: Identifier
    remaining: Positive
    stacks: Positive = 1
    attack_snapshot: Rational
    fresh_turn: int | None = None

class ShieldInstance(Model):
    source_id: Identifier
    skill_id: Identifier
    value: Positive
    remaining: Positive
    created_seq: Positive
    fresh_turn: int | None = None

class UnitState(Model):
    hp: Nat
    max_hp: Positive
    energy: Nat = 0
    energy_max: Nat = 0
    toughness: Nat = 0
    toughness_max: Nat = 0
    weaknesses: list[Element] = Field(default_factory=list)
    broken: bool = False
    dead: bool = False
    side: str
    slot: Nat
    template_id: str | None = None
    remaining_distance: Rational = Fraction(10000)
    spd: Rational
    atk: Rational
    defense: Rational
    crit_rate: Rational
    crit_damage_bonus: Rational
    damage_bonus: Rational = Fraction(0)
    buffs: dict[str,BuffInstance] = Field(default_factory=dict)
    shields: list[ShieldInstance] = Field(default_factory=list)
    charging: str | None = None
    skill_index: Nat = 0
    speed_passive: bool = False

class ActionRequest(Model):
    actor_id: Identifier
    skill_id: Identifier
    target_ids: list[Identifier]
    reason_code: str

class BattleState(Model):
    units: dict[str,UnitState]
    skill_points: Nat
    elapsed_av: Rational = Fraction(0)
    phase_index: Nat = 0
    phase_action_count: Nat = 0
    enrage_stacks: Nat = 0
    normal_turn_count: Nat = 0
    action_count: Nat = 0
    current_actor: str | None = None
    action_id: str | None = None
    ultimate_used: bool = False
    normal_used: bool = False
    shield_seq: Nat = 0
    summon_seq: Nat = 0
    rng_count: Nat = 0

def make_unit(stats, side, slot, **kwargs):
    return UnitState(hp=stats.hp,max_hp=stats.hp,side=side,slot=slot,spd=stats.spd,atk=stats.atk,defense=stats.defense,crit_rate=stats.crit_rate,crit_damage_bonus=stats.crit_damage_bonus,damage_bonus=stats.damage_bonus,**kwargs)

def initial_state(bundle: CombatBundle, scenario: Scenario) -> BattleState:
    if set(scenario.initial_energy)-set(bundle.party): raise ValueError('unknown initial energy owner')
    units={}
    for slot,uid in enumerate(bundle.party):
        c=bundle.characters[uid]; energy=scenario.initial_energy.get(uid,0)
        if energy>c.energy_max: raise ValueError('initial energy exceeds maximum')
        units[uid]=make_unit(c.stats,'player',slot,energy_max=c.energy_max,energy=energy)
    phase=bundle.phases[0]
    units[bundle.boss_id]=make_unit(bundle.boss_stats,'enemy',0,toughness=phase.toughness_max,toughness_max=phase.toughness_max,weaknesses=phase.weaknesses)
    return BattleState(units=units,skill_points=scenario.initial_skill_points)

def cancel_charge(state: BattleState, actor_id: str) -> bool:
    unit=state.units[actor_id]
    if unit.charging is None:return False
    unit.charging=None
    return True
