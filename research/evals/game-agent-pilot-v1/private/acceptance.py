"""Post-run checks. This file is NEVER part of the model tool catalog or preview."""
import json
from pathlib import Path
from combat_core.v2.config import read_json
from combat_core.v2.contracts import CombatBundle,Scenario
from combat_core.v2.state import initial_state,ShieldInstance,ActionRequest
from combat_core.v2.trace import EventRecorder
from combat_core.v2.effects import skill_points,resolve_action
from combat_core.v2.scheduler import assert_invariants

checks=[]
def check(name,fn):
    try:fn();checks.append({'name':name,'status':'PASS'})
    except Exception as exc:checks.append({'name':name,'status':'FAIL','error_type':type(exc).__name__,'message':str(exc)[:500]})

def world(cap=None,points=3,supply=False):
    root=Path('/project/configs/combat/v2');data=read_json(root/'baseline.json')
    if cap is not None:data.setdefault('rules',{})['skill_points_max']=cap
    bundle=CombatBundle.model_validate(data);scenario=read_json(root/'scenario.json');scenario['initial_skill_points']=points
    if supply:scenario['opening_support']={'content_version':'lan-support-v1','choice':'sp_supply'}
    return bundle,initial_state(bundle,Scenario.model_validate(scenario)),EventRecorder()

def rejected(fn):
    try:fn()
    except ValueError:return
    raise AssertionError('expected ValueError')

def negative(gained,spent):
    b,s,r=world();before=s.model_copy(deep=True)
    rejected(lambda:skill_points(s,gained,spent,r,b.party[0],'independent-check'))
    assert s==before,'rejected input changed state'
    assert not r.events,'rejected input recorded an event'

def resource(before,gained,spent,after,overflow):
    b,s,r=world(points=before)
    skill_points(s,gained,spent,r,b.party[0],'independent-check')
    assert s.skill_points==after
    e=r.events[-1]
    assert e.kind=='resource_changed' and e.payload.resource=='skill_points'
    assert (e.payload.before,e.payload.after,e.payload.overflow)==(before,after,overflow)

def cap_flow(cap):
    b,s,r=world(cap,cap-1)
    assert s.skill_points_max==cap
    skill_points(s,2,0,r,b.party[0],'independent-check')
    assert s.skill_points==cap and r.events[-1].payload.overflow==1
    assert_invariants(s)
    s.skill_points=cap+1;rejected(lambda:assert_invariants(s))
    rejected(lambda:world(cap,cap+1))
    _,supplied,_=world(cap,cap-1,True)
    assert supplied.skill_points==cap
    rejected(lambda:world(cap,cap,True))

def invalid_cap(value):rejected(lambda:world(value,0))

def default_cap():
    b,s,r=world();assert b.rules.skill_points_max==5
    skill_points(s,4,0,r,b.party[0],'independent-check');assert s.skill_points==5

def shield_behavior():
    import random
    from fractions import Fraction
    b,s,r=world();target=s.units[b.boss_id];hp=target.hp
    target.shields=[ShieldInstance(source_id='support_01',skill_id='support_ultimate',value=10000,remaining=2,created_seq=1)]
    target.toughness=30;s.units['breaker_01'].crit_rate=Fraction(0)
    s.current_actor='breaker_01'
    resolve_action(b,s,ActionRequest(actor_id='breaker_01',skill_id='breaker_basic',target_ids=[b.boss_id],reason_code='independent-check'),random.Random(11),r)
    assert target.hp==hp and target.broken and target.toughness==0
    assert any(e.kind=='shield_absorbed' for e in r.events)
    assert any(e.kind=='toughness_changed' and e.payload.reduction==30 for e in r.events)
    assert sum(e.kind=='break_triggered' for e in r.events)==1

if TASK=='resource-atomicity':
    for gained,spent in [(-2,0),(0,-3),(-2,-3)]:check('negative_atomic_'+str((gained,spent)),lambda g=gained,p=spent:negative(g,p))
    for values in [(3,1,0,4,0),(5,2,0,5,2),(3,0,2,1,0),(5,2,1,5,1)]:check('legal_'+str(values),lambda v=values:resource(*v))
elif TASK=='configurable-cap':
    for cap in [1,3,7,9]:check('configured_cap_'+str(cap),lambda c=cap:cap_flow(c))
    for value in [0,10,True,'7']:check('invalid_cap_'+str(value),lambda v=value:invalid_cap(v))
    check('default_compatible',default_cap)
elif TASK=='shield-toughness-review':check('shield_toughness_existing_rule',shield_behavior)
else:raise ValueError('unknown independent task')
print(json.dumps({'schema':'game-agent-independent-v1','task':TASK,'checks':checks},ensure_ascii=False))
