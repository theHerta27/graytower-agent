"""Local post-run program checks; never available to the model."""
import json
from pathlib import Path
from fractions import Fraction
from combat_core.v2.config import load_bundle,load_scenario
from combat_core.v2.state import initial_state
from combat_core.v2.scheduler import next_actor
from combat_core.v2.report import RunMetrics,report_pairs,nearest_rank

checks=[]
def check(name,fn):
    try:fn();checks.append({'name':name,'status':'PASS'})
    except Exception as exc:checks.append({'name':name,'status':'FAIL','error_type':type(exc).__name__,'message':str(exc)[:400]})

def speed():
    base=Path('/project/configs/combat/v2')
    s=initial_state(load_bundle(base/'baseline.json'),load_scenario(base/'scenario.json'))
    for unit in s.units.values():unit.remaining_distance=10000
    s.elapsed_av=Fraction(90);s.units['striker_01'].remaining_distance=1000;s.units['striker_01'].spd=Fraction(110)
    assert next_actor(s)=='striker_01'
    assert s.elapsed_av==Fraction(1090,11)
    assert s.elapsed_av-90==Fraction(100,11)

def zero():
    m=RunMetrics(seed=11,strategy='balanced',outcome='loss',elapsed_av='100',normal_turn_count=1,action_count=1,
        survivors=0,phases={},damage={},breaks=[],ultimates={},resources={},shield_absorbed=0,control_skips=0)
    report=report_pairs('a'*64,'b'*64,[(m,m)]).model_dump()
    for side in ('baseline','candidate'):
        item=report['by_strategy']['balanced'][side]
        assert item['wins']==0 and item['win_rate']==0
        assert item['p50_av'] is None and item['p90_av'] is None
    assert nearest_rank([],0.5) is None
    assert nearest_rank([1,2,3,4],0.5)==2 and nearest_rank([1,2,3,4],0.9)==4

if TASK=='speed-review':check('speed_distance_and_exact_av',speed)
elif TASK=='zero-win-review':check('zero_wins_and_nearest_rank',zero)
else:raise ValueError('unsupported rule review')
print(json.dumps({'checks':checks},ensure_ascii=False))
