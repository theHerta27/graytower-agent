"""Deterministic oracle checks. No model invocation, source mutation or Unity.

Every behavioral check executes frozen baseline/candidate source. C# display is
explicitly source-verified with a numeric witness, not claimed as compiled Unity.
"""
from __future__ import annotations

import ast
import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PROJECT = ROOT.parents[2]
COMBAT = Path('D:/Desktop/combat-foundation')
sys.dont_write_bytecode = True
sys.path[:0] = [str(PROJECT/'src'), str(COMBAT/'game-core')]
V = 'mihoyo-agent-project/src/agent_workbench/verification/'
G = 'combat-foundation/game-core/combat_core/v2/'
U = 'combat-foundation/game-unity/Assets/Runtime/'
H = 'herta-agent-coding/backend/herta_agent/service/'
CHECKS = []


def sha(value):
    return hashlib.sha256(value).hexdigest()


def source(task, branch, path):
    return (HERE/task/branch/path.replace('/','__')).read_text(encoding='utf-8')


def module(task, branch, path, package):
    file = HERE/task/branch/path.replace('/','__')
    name = package + '._bench_' + task + '_' + branch + '_' + file.stem
    spec = importlib.util.spec_from_file_location(name,file)
    obj = importlib.util.module_from_spec(spec)
    sys.modules[name] = obj
    spec.loader.exec_module(obj)
    return obj


def function(task, branch, path, name, namespace):
    tree = ast.parse(source(task,branch,path))
    nodes=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name]
    assert len(nodes)==1
    exec(compile(ast.Module(body=nodes,type_ignores=[]),path,'exec'),namespace)
    return namespace[name]


def checked(issue_id, baseline, candidate, detail, kind='executed_frozen_python'):
    CHECKS.append(dict(verification_id=issue_id,passed=True,kind=kind,
                       baseline=baseline,candidate=candidate,detail=detail))


def rejects(fn, *args):
    try:
        fn(*args)
    except (ValueError,RuntimeError) as exc:
        return type(exc).__name__+': '+str(exc)
    return False


def plan():
    from agent_workbench.verification.contracts import ExperimentPlan
    return ExperimentPlan.model_validate(dict(request_id='oracle',request='numeric candidate',game_fingerprint='0'*64,
        changes=[dict(path='skills.striker_skill.multiplier',value=1.7)],
        bounds={'skills.striker_skill.multiplier':dict(minimum=1.4,maximum=1.8)},
        seeds=[11,12],policies=['balanced'],max_battles=4))


def receipt(p):
    from agent_workbench.verification.contracts import fingerprint
    return dict(plan_hash=fingerprint(p),game_fingerprint=p.game_fingerprint,
        rows=[dict(policy=policy,seed=seed,baseline=dict(outcome='win',elapsed_av='100'),
                   candidate=dict(outcome='win',elapsed_av='80')) for policy in p.policies for seed in p.seeds])


def game():
    from combat_core.v2.config import load_bundle,load_scenario
    from combat_core.v2.state import initial_state
    b=load_bundle(COMBAT/'configs/combat/v2/baseline.json')
    s=load_scenario(COMBAT/'configs/combat/v2/scenario.json')
    return b,initial_state(b,s)


def verify_hashes():
    manifest=json.loads((HERE/'manifest.json').read_text(encoding='utf-8'))
    for task in manifest['tasks']:
        assert sha((ROOT/task['packet_path']).read_bytes())==task['packet_sha256']
        oracle=json.loads((ROOT/task['oracle_path']).read_text(encoding='utf-8'))
        assert sha((ROOT/task['oracle_path']).read_bytes())==task['oracle_sha256']
        packet=(ROOT/task['packet_path']).read_text(encoding='utf-8')
        assert len(packet)==task['packet_characters']
        for path,value in oracle['candidate_hashes'].items():
            assert sha(source(task['task_id'],'candidate',path).encode())==value
        for path,value in oracle['source_hashes'].items():
            repo,rel=path.split('/',1)
            checkout={'mihoyo-agent-project':PROJECT,'combat-foundation':COMBAT,
                      'herta-agent-coding':Path('D:/Desktop/herta-agent-coding')}[repo]
            assert sha((checkout/rel).read_bytes())==value, f'Live helper source changed: {path}'
        for issue in oracle['issues']:
            loc=issue['allowed_locations'][0]
            assert loc['path'] in packet
            assert any(f'{n:04d} | ' in packet for n in range(loc['start_line'],loc['end_line']+1))
    return manifest


def dev01():
    result=[]
    for branch in ('baseline','candidate'):
        _,state=game(); uid='striker_01'; initial_hp=state.units[uid].hp
        trace=module('dev01',branch,G+'trace.py','combat_core.v2')
        rec=trace.EventRecorder();rec.emit('battle_started',state,{})
        state.units[uid].hp-=7
        result.append(dict(original_hp=initial_hp, recorded_hp=rec.events[0].state_after.units[uid].hp,
                           live_hp=state.units[uid].hp))
    assert result[0]['recorded_hp']==result[0]['original_hp']
    assert result[1]['recorded_hp']==result[1]['live_hp']!=result[1]['original_hp']
    checked('D01-HISTORY',*result,'Same recorded event is read after later live-state mutation.')
    result=[]
    from combat_core.v2.state import ShieldInstance
    from combat_core.v2.trace import EventRecorder
    for branch in ('baseline','candidate'):
        bundle,state=game(); uid='support_01';state.current_actor=uid;state.normal_turn_count=5
        state.units[uid].shields=[ShieldInstance(source_id=uid,skill_id='support_ultimate',value=120,remaining=1,created_seq=1,fresh_turn=5)]
        effects=module('dev01',branch,G+'effects.py','combat_core.v2')
        effects.end_statuses(bundle,state,uid,EventRecorder())
        result.append([s.remaining for s in state.units[uid].shields])
    assert result==[[1],[]]
    checked('D01-DURATION',*result,'A shield granted during its owner turn must survive that same turn end.')
    old=source('dev01','baseline',U+'CombatUnitView.cs')
    new=source('dev01','candidate',U+'CombatUnitView.cs')
    assert 'V2State.shields.Sum(x=>x.value)' in old
    assert 'V2State.shields.Select(x=>x.value).DefaultIfEmpty(0).Max()' in new
    values=[120,80]
    assert sum(values)==200 and max(values)==120
    checked('D01-DISPLAY',200,120,'Exact C# source expression inspected; input shield values [120,80]. Empty list remains 0.',
            kind='source_verified_csharp_numeric_witness_not_unity_execution')


def dev02():
    from agent_workbench.verification.contracts import fingerprint
    p=plan()
    for case,issue_id in [('approval','D02-APPROVAL'),('retry','D02-RETRY'),('receipt','D02-RECEIPT')]:
        result=[]
        for branch in ('baseline','candidate'):
            store_mod=module('dev02',branch,V+'store.py','agent_workbench.verification')
            with tempfile.TemporaryDirectory(dir=HERE/'work') as folder:
                store=store_mod.Store(Path(folder));store.create(p)
                if case=='approval':
                    rejected=rejects(store.decide,p.request_id,'f'*64,True)
                    result.append(dict(rejected=rejected,approved=store.get(p.request_id)['approved']))
                else:
                    store.decide(p.request_id,fingerprint(p),True);store.claim(p)
                    if case=='retry':
                        # Reopen with a new Store instance to model process-independent ledger recovery.
                        store=store_mod.Store(Path(folder));rejected=rejects(store.claim,p)
                        result.append(dict(rejected=rejected,charged=store.get(p.request_id)['charged_battles']))
                    else:
                        bad=receipt(p);bad['plan_hash']='f'*64
                        rejected=rejects(store.complete,p,bad)
                        result.append(dict(rejected=rejected,status=store.get(p.request_id)['job_status']))
        assert result[0]['rejected'] and not result[1]['rejected']
        if case=='approval': assert result[0]['approved'] is None and result[1]['approved']==1
        if case=='retry': assert result[0]['charged']==result[1]['charged']==4
        if case=='receipt': assert result[0]['status']=='running' and result[1]['status']=='completed'
        checked(issue_id,*result,'Executed frozen Store with real SQLite, distinct temporary database for every branch/case.')


def confirm01():
    from combat_core.v2.state import ActionRequest
    from combat_core.v2.bots import targets
    from combat_core.v2.boss import choose_enemy_action
    result=[]
    for branch in ('baseline','candidate'):
        b,s=game();uid='striker_01';s.current_actor=uid;s.normal_used=True;s.units[uid].energy=s.units[uid].energy_max
        sid=b.characters[uid].skill_slots.ultimate
        action=ActionRequest(actor_id=uid,skill_id=sid,target_ids=targets(b,s,uid,sid),reason_code='external_request')
        mod=module('confirm01',branch,G+'effects.py','combat_core.v2')
        result.append(rejects(mod.validate_action,b,s,action))
    assert result[0] and result[1] is False
    checked('C01-WINDOW',*result,'Same owned ultimate submitted directly after a normal action, with full energy.')
    result=[]
    for branch in ('baseline','candidate'):
        b,s=game();s.phase_index=2;boss=s.units[b.boss_id];boss.charging='boss_charge';boss.skill_index=0
        mod=module('confirm01',branch,G+'state.py','combat_core.v2')
        assert mod.cancel_charge(s,b.boss_id)
        result.append(dict(skill_index=boss.skill_index,next_skill=choose_enemy_action(b,s,b.boss_id).skill_id))
    assert result[0]==dict(skill_index=1,next_skill='boss_sweep')
    assert result[1]==dict(skill_index=0,next_skill='boss_charge')
    checked('C01-CHARGE',*result,'Actual baseline phase_3 skill pool; next action chosen by unchanged real boss selector.')


def confirm02():
    p=plan();result=[]
    for branch in ('baseline','candidate'):
        mod=module('confirm02',branch,V+'report.py','agent_workbench.verification')
        r=receipt(p);r['rows'].append(dict(r['rows'][0]))
        rejected=rejects(mod.build_report,p,r)
        result.append(dict(rejected=rejected,rows=len(r['rows'])))
    assert result[0]['rejected'] and not result[1]['rejected']
    checked('C02-DUPLICATE',*result,'All expected pairs plus one duplicate; duplicate cannot create another observation.')
    result=[]
    for branch in ('baseline','candidate'):
        mod=module('confirm02',branch,V+'report.py','agent_workbench.verification')
        result.append(mod.build_report(p,receipt(p))['policies']['balanced']['paired_av_ratio_median'])
    assert result==[0.8,1.25]
    checked('C02-RATIO',*result,'Both pairs win, baseline AV 100 and candidate AV 80.')
    result=[]
    for branch in ('baseline','candidate'):
        fn=function('confirm02',branch,V+'combat_worker.py','source_fingerprint',{'Path':Path,'hashlib':hashlib})
        with tempfile.TemporaryDirectory(dir=HERE/'work') as folder:
            root=Path(folder)
            for rel,data in [('game-core/combat_core/__init__.py','VALUE=1\n'),('game-core/combat_core/rules.py','RULE=1\n'),
                             ('services/verification-agent/verification_agent/__init__.py','VALUE=1\n'),
                             ('configs/combat/v2/baseline.json','{}'),('configs/combat/v2/scenario.json','{}')]:
                f=root/rel;f.parent.mkdir(parents=True,exist_ok=True);f.write_text(data,encoding='utf-8')
            before=fn(root);(root/'game-core/combat_core/__init__.py').write_text('VALUE=2\n',encoding='utf-8');after=fn(root)
            result.append(dict(fingerprint_changed=before!=after))
    assert result==[dict(fingerprint_changed=True),dict(fingerprint_changed=False)]
    checked('C02-FINGERPRINT',*result,'Actual frozen source_fingerprint function on a minimal valid source tree; only package entry changed.')


async def confirm03_async():
    result=[]
    for branch in ('baseline','candidate'):
        mod=module('confirm03',branch,H+'events.py','benchmark')
        q=mod.EventQueue()
        def event(seq):return dict(type='llm.delta',session_id='s',run_id='r',seq=seq,timestamp='fixture',payload={'text':'x'})
        for i in range(128):q.put_nowait(event(i+1))
        waiter=asyncio.create_task(q.put(event(129)));await asyncio.sleep(0)
        assert not waiter.done()
        q.get_nowait()
        for _ in range(3):await asyncio.sleep(0)
        result.append(dict(producer_resumed=waiter.done(),queue_size=q.qsize()))
        if not waiter.done():
            waiter.cancel()
            await asyncio.gather(waiter,return_exceptions=True)
    assert result[0]['producer_resumed'] and not result[1]['producer_resumed']
    checked('C03-WAKEUP',*result,'Real EventQueue filled to 128, put waits, consumer frees one slot; deterministic event-loop yields.')
    result=[]
    for branch in ('baseline','candidate'):
        fn=function('confirm03',branch,H+'runs.py','_wait_owned',{'asyncio':asyncio})
        gate=asyncio.Event();commits=[]
        async def commit():
            await gate.wait();commits.append('persisted');return 'ok'
        owned=asyncio.create_task(commit());caller=asyncio.create_task(fn(owned))
        await asyncio.sleep(0);caller.cancel()
        for _ in range(3):await asyncio.sleep(0)
        gate.set();await asyncio.gather(caller,return_exceptions=True)
        result.append(dict(owned_cancelled=owned.cancelled(),commits=commits,caller_cancelled=caller.cancelled()))
    assert result[0]==dict(owned_cancelled=False,commits=['persisted'],caller_cancelled=False)
    assert result[1]==dict(owned_cancelled=True,commits=[],caller_cancelled=True)
    checked('C03-OWNERSHIP',*result,'Cancellation arrives while an owned commit waits; baseline persists, candidate commit is cancelled.')


def confirm04():
    p=plan();result=[]
    for branch in ('baseline','candidate'):
        mod=module('confirm04',branch,V+'report.py','agent_workbench.verification')
        valid=mod.build_report(p,receipt(p))
        duplicate=receipt(p);duplicate['rows'].append(dict(duplicate['rows'][0]))
        foreign=receipt(p);foreign['plan_hash']='f'*64
        result.append(dict(valid_report=valid,duplicate_rejected=bool(rejects(mod.build_report,p,duplicate)),
                           foreign_rejected=bool(rejects(mod.build_report,p,foreign))))
    assert result[0]==result[1] and result[0]['duplicate_rejected'] and result[0]['foreign_rejected']
    old=ast.parse(source('confirm04','baseline',V+'report.py'))
    new=ast.parse(source('confirm04','candidate',V+'report.py'))
    old_fn=next(n for n in ast.walk(old) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='expected' for t in n.targets))
    new_fn=next(n for n in ast.walk(new) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='expected' for t in n.targets))
    old_fn.value=new_fn.value
    assert ast.dump(old,include_attributes=False)==ast.dump(new,include_attributes=False)
    checked('C04-CLEAN',result[0],result[1],'AST confirms only expected set construction changed; valid and invalid receipt behavior agrees.')


def main():
    (HERE/'work').mkdir(exist_ok=True)
    manifest=verify_hashes()
    dev01();dev02();confirm01();confirm02();asyncio.run(confirm03_async());confirm04()
    expected={i['issue_id'] for t in manifest['tasks'] for i in json.loads((ROOT/t['oracle_path']).read_text(encoding='utf-8'))['issues']}
    actual={c['verification_id'] for c in CHECKS}
    assert actual==expected|{'C04-CLEAN'}
    result=dict(schema_version=1,passed=True,python=sys.version,model_calls=0,unity_started=False,
                checks=CHECKS,check_count=len(CHECKS),issue_count=len(expected),
                manifest_sha256=sha((HERE/'manifest.json').read_bytes()),
                verifier_sha256=sha(Path(__file__).read_bytes()),
                limits=['C# display source verified with arithmetic witness, not compiled/Unity execution.',
                        'Completeness is restricted to explicitly bounded candidate mutations, not whole repositories.',
                        'Recovery logs in public dev02 are labeled diagnostic fixtures, not historical incident logs.'])
    (HERE/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(passed=True,check_count=len(CHECKS),issue_count=len(expected),
                         verification_ids=sorted(actual),manifest_sha256=result['manifest_sha256']),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
