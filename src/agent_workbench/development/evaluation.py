"""Frozen single-Agent pilot. Private grading runs after all model turns."""
from decimal import Decimal
import json
from pathlib import Path
import sys
import time
from .service import DevelopmentTask
from .workspace import digest,encoded,editable
from .sandbox import IMAGE,runner_hash,execute
from ..coding.responses_transport import CallBudget

REPO=Path(__file__).resolve().parents[3]
PACK=REPO/'research/evals/game-agent-pilot-v1'
PUBLIC=PACK/'public/tasks.json'
PRIVATE=PACK/'private/acceptance.py'
GRANT={'max_calls':16,'max_input_bytes':128000,'max_output_tokens':4096,'cost_cap_usd':'0.71',
       'input_usd_per_million':'0.30','cached_input_usd_per_million':'0.006','output_usd_per_million':'1.20',
       'pricing_checked_on':'2026-10-24'}
ALLOCATIONS={'resource-atomicity':(16,'0.71'),'configurable-cap':(24,'1.06'),'shield-toughness-review':(8,'0.36')}


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))


def implementation_identity():
    files=list((REPO/'src/agent_workbench/development').glob('*.py'))
    files += [REPO/'src/agent_workbench/coding'/name for name in ('runtime_adapter.py','responses_transport.py','response_namespaces.py')]
    return digest({p.relative_to(REPO).as_posix():p.read_text(encoding='utf-8-sig') for p in sorted(files)})


def prepare_pilot(project,root):
    root=Path(root).resolve();root.mkdir(parents=True,exist_ok=False)
    tasks=read(PUBLIC);cells=[];preview=[]
    for case in tasks:
        profile='standard';cell_id=case['id']+'-'+profile
        count,cap=ALLOCATIONS[case['id']];grant={**GRANT,'max_calls':count,'cost_cap_usd':cap}
        task=DevelopmentTask.create(project,root/'tasks'/cell_id,case['request'],tool_profile=profile)
        scope=task.prepare('pilot-v1',grant)
        cells.append({'cell_id':cell_id,'task_id':case['id'],'profile':profile,'run_id':'pilot-v1',
                      'baseline_commit':scope['baseline_commit'],'scope_sha256':scope['scope_sha256'],'grant':grant})
        preview.append({'cell_id':cell_id,**read(task._batch('pilot-v1')/'outbound-preview.json')})
    outgoing={'schema':'game-agent-pilot-preview-v1','cells':preview}
    (root/'outbound-preview.json').write_bytes(encoded(outgoing))
    per_call=((Decimal(GRANT['max_input_bytes']+2048)*Decimal(GRANT['input_usd_per_million'])
               +Decimal(GRANT['max_output_tokens'])*Decimal(GRANT['output_usd_per_million']))/1_000_000)
    scope={'schema':'game-agent-pilot-v1','endpoint':'https://api.deepseek.com/responses','model':'deepseek-flash',
           'cells':cells,'max_calls':48,'cost_cap_usd':'2.15',
           'conservative_max_usd':str(per_call*48),'preview_hash':digest(outgoing),
           'implementation_hash':implementation_identity(),'public_tasks_hash':digest(read(PUBLIC)),
           'private_grader_hash':digest(PRIVATE.read_text(encoding='utf-8')),'image':IMAGE,'runner_hash':runner_hash(),
           'actions':'只运行三题standard单Agent，各一次，资源16次/多文件24次/核对8次，总48次；不做对照、不应用，独立验收在模型结束后本地执行，不回流模型。',
           'data':'三题公开需求、允许的49份游戏文本、工具描述、规则诊断/检查反馈、候选Diff与Agent分析；不发独立验收源码、参考修复、凭据或工作台适配源码。',
           'limitation':'三题开发pilot，非独立确认；不预设收益，不以同题重复当新样本。'}
    scope['scope_sha256']=digest(scope)
    (root/'outbound-scope.json').write_bytes(encoded(scope));return scope


def scope_only(root,scope_hash):
    root=Path(root);scope=read(root/'outbound-scope.json');body=dict(scope);body.pop('scope_sha256')
    if (scope_hash!=scope['scope_sha256'] or digest(body)!=scope_hash
            or digest(read(root/'outbound-preview.json'))!=scope['preview_hash']
            or implementation_identity()!=scope['implementation_hash']
            or digest(read(PUBLIC))!=scope['public_tasks_hash']
            or digest(PRIVATE.read_text(encoding='utf-8'))!=scope['private_grader_hash']
            or IMAGE!=scope['image'] or runner_hash()!=scope['runner_hash']):
        raise ValueError('pilot scope, implementation or grading changed; do not execute old authorization')
    return scope


def verify_pilot(root,scope_hash):
    root=Path(root);scope=scope_only(root,scope_hash)
    for cell in scope['cells']:
        task=DevelopmentTask(root/'tasks'/cell['cell_id']);child=read(task._batch(cell['run_id'])/'outbound-scope.json')
        body=dict(child);body.pop('scope_sha256')
        if (child['scope_sha256']!=cell['scope_sha256'] or digest(body)!=cell['scope_sha256']
            or child['candidate_tree_hash']!=task.workspace.inspect()['tree_hash']
            or child['request_hash']!=digest(task.request) or child['tool_profile']!=task.tool_profile
            or child['preview_hash']!=digest(read(task._batch(cell['run_id'])/'outbound-preview.json'))):
            raise ValueError('pilot cell changed before start')
    return scope


def grader_payload(workspace,task_id,tree=None,*,oracle=None):
    if oracle is None and task_id not in {case['id'] for case in read(PUBLIC)}:raise ValueError('unknown pilot task')
    tree=workspace.snapshot() if tree is None else tree
    script='TASK='+repr(task_id)+'\n'+(Path(oracle) if oracle is not None else PRIVATE).read_text(encoding='utf-8')
    return make_payload(tree,'diagnostic',script)


def make_payload(tree,kind,script=None):
    from .sandbox import CHECK_SETS
    return {'identity':{'tree_hash':digest(tree),'check_set':kind,'image':IMAGE,'runner_hash':runner_hash(),
                       'targets':CHECK_SETS.get(kind,[]),'diagnostic_hash':digest(script)},'tree':tree,'diagnostic':script}


def execute_once(folder,payload):
    folder=Path(folder)
    if (folder/'receipt.json').exists():
        receipt=read(folder/'receipt.json')
        if receipt['input_hash']!=digest(payload):raise ValueError('grading receipt belongs to another frozen input')
        return receipt['result']
    if folder.exists():raise ValueError('grading execution unknown; inspect original attempt, never automatically repeat')
    folder.mkdir(parents=True);(folder/'input.json').write_bytes(encoded(payload))
    (folder/'started.json').write_bytes(encoded({'input_hash':digest(payload)}))
    result=execute(payload,lambda value:(folder/'resources.json').write_bytes(encoded(value)))
    (folder/'receipt.json').write_bytes(encoded({'input_hash':digest(payload),'result':result}))
    return result


def grade_cell(task,cell,folder,*,tree=None,oracle=None):
    folder=Path(folder);tree=task.workspace.snapshot() if tree is None else tree
    independent=execute_once(folder/'independent',grader_payload(task.workspace,cell['task_id'],tree,oracle=oracle))
    try:checks=json.loads(independent['log'])['checks'] if independent.get('exit_code')==0 else []
    except (ValueError,KeyError,TypeError):checks=[]
    rule_payload=make_payload(tree,'rules')
    rules=execute_once(folder.parent/'shared-rules'/digest(rule_payload),rule_payload)
    rule_ok=rules.get('exit_code')==0 and bool(rules.get('tests')) and all(t['status']=='PASS' for t in rules['tests'])
    check_ok=bool(checks) and all(c['status']=='PASS' for c in checks)
    baseline=task.workspace.baseline['files'];files=tree['files']
    changed=[name for name in set(baseline)|set(files) if baseline.get(name)!=files.get(name)]
    no_edit_ok=not changed if cell.get('read_only') or cell['task_id']=='shield-toughness-review' else True
    known_fail=any(c.get('status')=='FAIL' for c in checks) or any(t.get('status')=='FAIL' for t in rules.get('tests',[])) or not no_edit_ok
    verdict='FAIL' if known_fail else 'PASS' if check_ok and rule_ok else 'INCONCLUSIVE'
    return {'verdict':verdict,'independent_checks':checks,'rules_passed':sum(t['status']=='PASS' for t in rules.get('tests',[])),
            'rules_total':len(rules.get('tests',[])),'no_unnecessary_edit':no_edit_ok,'tree_hash':digest(tree),
            'note':'程序验收；模型最终解释与引用仍需逐题复核，不等于总体成功率。'}


def run_pilot(root,scope_hash,runtime_python,*,sender):
    root=Path(root);scope=verify_pilot(root,scope_hash)
    try:(root/'claimed').mkdir()
    except FileExistsError:raise ValueError('pilot already started; do not repeat paid trials') from None
    results=[]
    for cell in scope['cells']:
        scope_only(root,scope_hash)
        task=DevelopmentTask(root/'tasks'/cell['cell_id']);started=time.monotonic()
        print('开始 '+cell['cell_id'],flush=True)
        try:
            result=task.execute(cell['run_id'],cell['scope_sha256'],runtime_python,Path(sys.executable),sender=sender)
            state=result['state']
        except Exception as exc:
            saved=task._batch(cell['run_id'])/'run-result.json'
            result=read(saved) if saved.exists() else {'state':'not_started','error_type':type(exc).__name__}
            state=result['state']
        tree=task.workspace.snapshot();final_hash=digest(tree)
        runtime_file=task._batch(cell['run_id'])/'runtime/result.json'
        native=read(runtime_file) if runtime_file.exists() else result.get('runtime',{})
        native_hash=native.get('after_tree_hash')
        if native_hash is not None and native_hash!=final_hash:raise ValueError('candidate differs from Runtime final tree')
        record={**cell,'runtime_state':state,'runtime_seconds':round(time.monotonic()-started,3),
                'budget':CallBudget(task._batch(cell['run_id'])/'gateway',cell['grant']).summary(),
                'final_tree_hash':final_hash,'native_after_tree_hash':native_hash,
                'changed_files':[n for n in set(tree['files'])|set(task.workspace.baseline['files'])
                                 if tree['files'].get(n)!=task.workspace.baseline['files'].get(n)],'result':result}
        (task.root/'final-candidate.json').write_bytes(encoded(tree))
        task.export();results.append(record)
        (root/'model-results.json').write_bytes(encoded(results))
        print('结束 '+cell['cell_id']+' '+state,flush=True)
    return grade_pilot(root)


def grade_pilot(root):
    root=Path(root);scope=read(root/'outbound-scope.json');scope_only(root,scope['scope_sha256'])
    results=read(root/'model-results.json')
    frozen=[]
    for record in results:
        task=DevelopmentTask(root/'tasks'/record['cell_id'])
        tree=read(task.root/'final-candidate.json');identity=digest(tree)
        native_hash=record.get('native_after_tree_hash') or record.get('result',{}).get('runtime',{}).get('after_tree_hash')
        if identity!=record['final_tree_hash'] or (native_hash is not None and native_hash!=identity):
            raise ValueError('frozen final candidate does not match model completion evidence')
        before=task.workspace.baseline['files'];after=tree['files']
        if any(not editable(n) and before.get(n)!=after.get(n) for n in set(before)|set(after)):
            raise ValueError('frozen candidate changed trusted read-only materials')
        frozen.append((record,task,tree))
    for record,task,tree in frozen:
        record['grade']=grade_cell(task,record,root/'grading'/record['cell_id'],tree=tree)
    summary={'schema':'game-agent-pilot-results-v1','scope_sha256':scope['scope_sha256'],'results':results,
             'known_cost_usd':str(sum((Decimal(r['budget']['known_cost_usd']) for r in results),Decimal(0))),
             'unknown_requests':sum(r['budget']['unknown'] for r in results),
             'limitation':scope['limitation'],'human_semantic_review':'尚未进行；保留原始模型说明与工具记录供复核。'}
    (root/'results.json').write_bytes(encoded(summary));return summary
