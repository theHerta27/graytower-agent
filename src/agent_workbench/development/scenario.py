"""A bounded observation program; game rules remain in the frozen candidate."""
import json
import re


def identifier(value):
    if not isinstance(value,str) or not re.fullmatch('[a-zA-Z][a-zA-Z0-9_]{0,79}',value):
        raise ValueError('invalid game identifier')


def number(value,lower,upper):
    if type(value) is not int or not lower<=value<=upper:raise ValueError('invalid scenario number')


def scenario_script(scenario_json):
    if not isinstance(scenario_json,str) or len(scenario_json)>6000:raise ValueError('require bounded JSON scenario')
    try:spec=json.loads(scenario_json,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('nonfinite JSON')))
    except (ValueError,TypeError):raise ValueError('scenario must be finite JSON') from None
    if not isinstance(spec,dict) or set(spec)-{'initial_skill_points','skill_points_max','shields','actions'}:
        raise ValueError('unsupported scenario fields')
    if 'initial_skill_points' in spec:number(spec['initial_skill_points'],0,9)
    if 'skill_points_max' in spec:number(spec['skill_points_max'],1,9)
    shields=spec.get('shields',[]);actions=spec.get('actions',[])
    if not isinstance(shields,list) or len(shields)>4 or not isinstance(actions,list) or len(actions)>8:
        raise ValueError('scenario exceeds shield or action limit')
    for shield in shields:
        if not isinstance(shield,dict) or set(shield)!={'target_id','value','duration'}:raise ValueError('invalid shield')
        identifier(shield['target_id']);number(shield['value'],1,100000);number(shield['duration'],1,10)
    for action in actions:
        if not isinstance(action,dict):raise ValueError('invalid scenario action')
        kind=action.get('kind')
        if kind=='resource':
            if set(action)!={'kind','gained','spent'}:raise ValueError('invalid resource action')
            number(action['gained'],-20,20);number(action['spent'],-20,20)
        elif kind=='skill':
            if set(action)!={'kind','actor_id','skill_id','target_ids'}:raise ValueError('invalid skill action')
            identifier(action['actor_id']);identifier(action['skill_id'])
            targets=action['target_ids']
            if not isinstance(targets,list) or not 1<=len(targets)<=4:raise ValueError('invalid targets')
            for target in targets:identifier(target)
        elif kind=='tick_status':
            if set(action)!={'kind','actor_id'}:raise ValueError('invalid status tick')
            identifier(action['actor_id'])
        else:raise ValueError('unsupported action kind')
    return 'import json\nspec=json.loads('+repr(json.dumps(spec,ensure_ascii=False,sort_keys=True))+')\n'+PROGRAM


PROGRAM='''from pathlib import Path
import random
from combat_core.v2.config import read_json
from combat_core.v2.contracts import CombatBundle,Scenario
from combat_core.v2.state import initial_state,ShieldInstance,ActionRequest
from combat_core.v2.effects import skill_points,resolve_action,end_statuses
from combat_core.v2.trace import EventRecorder
from combat_core.v2.scheduler import assert_invariants

def view(state):
    return {'skill_points':state.skill_points,'units':{uid:{'hp':u.hp,'energy':u.energy,'toughness':u.toughness,
        'broken':u.broken,'dead':u.dead,'shields':[{'value':s.value,'remaining':s.remaining,'sequence':s.created_seq} for s in u.shields]}
        for uid,u in state.units.items()}}

root=Path('/project/configs/combat/v2')
result={'schema':'graytower-observation-v1','verdict':'OBSERVATION','steps':[],
        'limits':'规则函数诊断，不代表完整战斗调度，也不是可信验收。'}
try:
    config=read_json(root/'baseline.json')
    if 'skill_points_max' in spec:config.setdefault('rules',{})['skill_points_max']=spec['skill_points_max']
    bundle=CombatBundle.model_validate(config)
    setting=read_json(root/'scenario.json')
    if 'initial_skill_points' in spec:setting['initial_skill_points']=spec['initial_skill_points']
    state=initial_state(bundle,Scenario.model_validate(setting));recorder=EventRecorder();rng=random.Random(7)
    for shield in spec.get('shields',[]):
        state.shield_seq+=1
        state.units[shield['target_id']].shields.append(ShieldInstance(source_id='support_01',skill_id='support_ultimate',
            value=shield['value'],remaining=shield['duration'],created_seq=state.shield_seq))
    result['initial_state']=view(state);result['rules']={'skill_points_max':bundle.rules.skill_points_max}
    for action in spec.get('actions',[]):
        item={'action':action,'state_before':view(state)};offset=len(recorder.events)
        try:
            if action['kind']=='resource':skill_points(state,action['gained'],action['spent'],recorder,bundle.party[0],'scenario_observation')
            elif action['kind']=='skill':
                state.current_actor=action['actor_id'];state.normal_used=False;state.ultimate_used=False
                resolve_action(bundle,state,ActionRequest(actor_id=action['actor_id'],skill_id=action['skill_id'],
                    target_ids=action['target_ids'],reason_code='scenario_observation'),rng,recorder)
            else:
                state.current_actor=action['actor_id'];state.normal_turn_count+=1
                end_statuses(bundle,state,action['actor_id'],recorder)
        except Exception as exc:item['exception']={'type':type(exc).__name__,'message':str(exc)[:500]}
        try:assert_invariants(state)
        except Exception as exc:item['invariant_error']={'type':type(exc).__name__,'message':str(exc)[:200]}
        events=recorder.events[offset:]
        item['events']=[{'kind':e.kind,'actor_id':e.actor_id,'target_id':e.target_id,'payload':e.payload.model_dump(mode='json')} for e in events[:12]]
        item['events_total']=len(events);item['events_truncated']=len(events)>12;item['state_after']=view(state)
        result['steps'].append(item)
    result['final_state']=view(state)
except Exception as exc:result['setup_error']={'type':type(exc).__name__,'message':str(exc)[:800]}
print(json.dumps(result,ensure_ascii=False,default=str))
'''
