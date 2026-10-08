"""One explicit compatibility revision after failed code QA; never reset a trial."""
import argparse
import json
import os
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from v1_close_demo import write,sha,source_hashes
from run_python_coding_demo import runtime_identity,RUNTIME_PYTHON
from agent_workbench.code_candidates import prepare_python_case
from agent_workbench.code_tools import CodeCatalog
from agent_workbench.coding.service import CodingAuthorization,CodingService
from agent_workbench.coding.responses_transport import CallBudget,deepseek_sender
from agent_workbench.coding.runtime_adapter import instructions
from agent_workbench.jobs import JobStore
from agent_workbench.workbench import create_app

OP='code_d02_revision_v1'
PARENT='ad0287674007ceb113b364d346d8e628c876a99b185ce36572aea80b72217649'
PARENT_QA='task_5993fca92edc439492c9f251e4b1822d_qa'
PROMPT='修订战技点上限修复：上一候选改变了 skill_points 函数参数，独立检查按原接口调用时出现 TypeError，未通过。请从原始故障版重新做最小兼容修复：保持所有现有函数参数和调用方式不变，让普通攻击补给与消耗遵守已有5点上限，溢出事件一致，不改其他规则。已定位在 game-core/combat_core/v2/effects.py，请先读这个文件，按需要再读配置，避免无关重构。只允许修改effects.py；交付新补丁并接受原生 Review。'

def sources():return source_hashes()|{Path(__file__).relative_to(ROOT).as_posix():sha(__file__)}
def prepare(root,data):
    parent=CodeCatalog(data).view(PARENT);report=JobStore(data).get(PARENT_QA)['report']
    if report['verdict']!='FAIL' or report['manifest_hash']!=PARENT:raise ValueError('fixed failed parent required')
    root.mkdir(parents=True,exist_ok=False)
    base=data/'coding-runs'/OP
    workspace=prepare_python_case(base/'python-data/control',base/'workspace','skill-points-python-v1')
    tree=workspace.artifacts.read_ref(workspace.preparation['baseline_tree'],'code-tree-v1')
    write(root/'outbound-preview.json',{'request':PROMPT,'instructions':instructions(workspace.preparation['profile']),
        'readable_files':[workspace.read_file(n) for n in sorted(tree['files'])],
        'failure_feedback':'Original function signature required by the existing checker; candidate invocation raises TypeError.',
        'additional_material':'authorized tool results, new patch, Agent analysis and native Review',
        'not_sent':['oracle code','reference fix','test expected values','credentials as content','project adapter source','unrelated files']})
    write(root/'outbound-scope.json',{'schema':'coding-service-grant-v1','tasks':{OP:{'request':PROMPT,'mode':'single'}},
        'case_profiles':{OP:'skill-points-python-v1'},'case_preparations':{OP:workspace.preparation},
        'data_root':str(data),'parent_candidate':PARENT,'parent_qa':PARENT_QA,
        'coding_grant':{'max_calls':12,'max_input_bytes':140000,'max_output_tokens':2048,'cost_cap_usd':'0.55',
            'input_usd_per_million':'0.30','cached_input_usd_per_million':'0.006','output_usd_per_million':'1.20'},
        'endpoint':'https://api.deepseek.com/responses','model':'deepseek-flash','conservative_bound_usd':'0.540864',
        'local_checks':{'qa_model_calls':0,'new_battles':0,'variants':2,'tests_per_variant':4,'adoption_recheck':4},
        'limits':['Single new revision, not rerunning or overwriting the failed candidate.','No automatic retries or cap increase.',
                  'No edits to the original game/Unity; explicit local-test adoption only.'],
        'preview_sha256':sha(root/'outbound-preview.json'),'source_hashes':sources(),'runtime_identity':runtime_identity()})
    print(json.dumps({'scope':str(root/'outbound-scope.json'),'sha256':sha(root/'outbound-scope.json'),'game_files':len(tree['files'])},ensure_ascii=False))

def serve(root,port):
    path=root/'outbound-scope.json';value=json.loads(path.read_text(encoding='utf-8'))
    if (root/'closed.json').exists() or json.loads((root/'authorization.json').read_text(encoding='utf-8'))!={'authorized':True,'scope_sha256':sha(path)}:
        raise ValueError('explicit authorization for this revision required')
    if value['source_hashes']!=sources() or sha(root/'outbound-preview.json')!=value['preview_sha256'] or runtime_identity()!=value['runtime_identity']:
        raise ValueError('sealed source/preview/runtime changed')
    auth=CodingAuthorization(path,sha(path),root/'coding-calls')
    coding=CodingService(Path(value['data_root']),authorization=auth,sender=deepseek_sender(os.environ['DEEPSEEK_API_KEY']),runtime_python=RUNTIME_PYTHON)
    app=create_app(coding.root,coding_service=coding,code_demo_root=Path('D:/Desktop/mihoyo-agent-project/local-data/python-coding-d01-v1'),
        test_game_root=Path('D:/Desktop/graytower-game/local-data/worktrees/local-test-content'))
    import uvicorn;uvicorn.run(app,host='127.0.0.1',port=port,access_log=False)

def close(root):
    value=json.loads((root/'outbound-scope.json').read_text(encoding='utf-8'))
    budget=CallBudget(root/'coding-calls',value['coding_grant']|{'authorization_sha256':sha(root/'outbound-scope.json')}).summary()
    write(root/'closed.json',{'closed':True,'scope_sha256':sha(root/'outbound-scope.json'),'budget':budget,'reason':'Revision trial ended; unused budget closed; failure history retained.'})
    print((root/'closed.json').read_text(encoding='utf-8'))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','serve','close']);p.add_argument('--data',type=Path,required=True)
    p.add_argument('--product-data',type=Path);p.add_argument('--port',type=int,default=18785);a=p.parse_args();root=a.data.resolve()
    if a.action=='prepare':
        if not a.product_data:p.error('prepare requires product-data')
        prepare(root,a.product_data.resolve())
    elif a.action=='serve':serve(root,a.port)
    else:close(root)
