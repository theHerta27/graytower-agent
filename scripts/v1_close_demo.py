"""A bounded product trial: formal D-02 Coding and independent D-01/D-02 QA.

Preparing sends nothing. Serving requires a human authorization record tied to
the exact scope. Closing makes every unused call unavailable.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from decimal import Decimal

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from agent_workbench.code_candidates import prepare_python_case
from agent_workbench.code_tools import CodeCatalog,CODE_QA_GOALS
from agent_workbench.coding.service import CodingAuthorization,CodingService
from agent_workbench.coding.responses_transport import deepseek_sender
from agent_workbench.models import ModelGateway
from agent_workbench.verification.code_agent import CodeDecision
from run_python_coding_demo import runtime_identity,RUNTIME_PYTHON
from agent_workbench.coding.runtime_adapter import instructions

PROMPT='普通攻击补充战技点时，界面显示上限5点，但实际只能存到4点。请阅读真实Python规则，修复这个资源上限问题，保持普通攻击补给、战技消耗与溢出事件的规则一致，不改其他机制。只能修改effects.py，完成后交付补丁与说明。'
OP='code_d02_v1'
GOALS=CODE_QA_GOALS

def scoped_workbench_class(value,coding):
    from agent_workbench.workbench import Workbench,APIError
    class ScopedWorkbench(Workbench):
        async def verify(self,request,*,resume=False):
            candidate=self.candidate(request.manifest_hash)
            profile=candidate.get('profile')
            if candidate.get('kind')!='code' or request.goal!=GOALS.get(profile) or request.max_battles!=2:
                raise APIError('outside_scope','请使用这份代码改动已准备好的独立检查目标，不扩大本次授权。',403)
            expected=value['d01_candidate'] if profile=='shield-damage-python-v1' else (coding.store.get(OP).get('result') or {}).get('candidate',{}).get('manifest_hash')
            if request.manifest_hash!=expected:
                raise APIError('outside_scope','本批只检查冻结的护盾候选和本次战技点修复候选。',403)
            return await super().verify(request,resume=resume)
    return ScopedWorkbench

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(path,value):
    with Path(path).open('x',encoding='utf-8',newline='\n') as file:
        json.dump(value,file,ensure_ascii=False,indent=2);file.write('\n')
def source_hashes():
    return {p.relative_to(ROOT).as_posix():sha(p) for p in [Path(__file__),ROOT/'scripts/run_python_coding_demo.py',*sorted((ROOT/'src').rglob('*.py'))]}

def prepare(root,data):
    root.mkdir(parents=True,exist_ok=False)
    base=data/'coding-runs'/OP
    case=prepare_python_case(base/'python-data/control',base/'workspace','skill-points-python-v1')
    tree=case.artifacts.read_ref(case.preparation['baseline_tree'],'code-tree-v1')
    d01=[c for c in CodeCatalog(data).ids() if CodeCatalog(data).view(c)['profile']=='shield-damage-python-v1']
    if len(d01)!=1:raise ValueError('exact sealed D-01 candidate required')
    preview={'D02':{'request':PROMPT,'instructions':instructions(case.preparation['profile']),
        'readable_files':[case.read_file(n) for n in sorted(tree['files'])],
        'additional_material':'scoped tool results, new candidate diff, Agent/child analysis and native Review'},
        'QA':{'goals':GOALS,'D01_candidate':CodeCatalog(data).view(d01[0]),
            'D02_candidate':'Only the frozen result of code_d02_v1; no other candidate',
            'additional_material':'frozen patch, test labels and actual before/after structured tests; no whole source tree'}}
    write(root/'outbound-preview.json',preview)
    write(root/'outbound-scope.json',{
        'schema':'coding-service-grant-v1','tasks':{OP:{'request':PROMPT,'mode':'auto'}},
        'case_profiles':{OP:'skill-points-python-v1'},'case_preparations':{OP:case.preparation},
        'data_root':str(data),'coding_grant':{'max_calls':18,'max_input_bytes':140000,'max_output_tokens':2048,
            'cost_cap_usd':'0.85','input_usd_per_million':'0.30','cached_input_usd_per_million':'0.006','output_usd_per_million':'1.20'},
        'qa_grant':{'max_calls':2,'max_input_chars':32000,'max_output_tokens':2048,'cost_bound_usd':'0.082944'},
        'qa_goals':GOALS,'d01_candidate':d01[0],
        'endpoints':['https://api.deepseek.com/responses','https://api.deepseek.com/chat/completions'],
        'model':'deepseek-flash','total_max_calls':20,'total_cost_cap_usd':'0.95','conservative_bound_usd':'0.894240',
        'price_source':'https://api-docs.deepseek.com/quick_start/pricing/','price_checked':'2026-10-08',
        'bound':'18*((140000+2048)*0.30+2048*1.20)/1e6 + 2*((32000*4+2048)*0.30+2048*1.20)/1e6',
        'local_checks':{'new_battles':0,'independent_qa':2,'tests_per_variant':4,'adoption_recheck':4},
        'not_sent':['credentials as content','hidden oracle or reference fix to Coding','project adapter source','unrelated repository files'],
        'limits':['No automatic model retries; failures/unknown calls consume the cap.',
                  'Only these fixed tasks; no expansion by HTTP or new task ID.',
                  'Local isolated tests and explicit local-test adoption only; no original game or Unity edits.',
                  'Functional trial, not collaboration quality or speed evidence.'],
        'preview_sha256':sha(root/'outbound-preview.json'),'source_hashes':source_hashes(),'runtime_identity':runtime_identity()})
    print(json.dumps({'scope':str(root/'outbound-scope.json'),'sha256':sha(root/'outbound-scope.json'),
                      'game_files':len(tree['files']),'total_cost_cap_usd':'0.95'},ensure_ascii=False))

def checked(root):
    path=root/'outbound-scope.json';auth=json.loads((root/'authorization.json').read_text(encoding='utf-8'))
    if (root/'closed.json').exists() or auth!={'authorized':True,'scope_sha256':sha(path)}:
        raise ValueError('explicit open authorization for this exact scope required')
    value=json.loads(path.read_text(encoding='utf-8'))
    if value['source_hashes']!=source_hashes() or value['preview_sha256']!=sha(root/'outbound-preview.json'):
        raise ValueError('reviewed code or preview changed')
    if runtime_identity()!=value['runtime_identity']:raise ValueError('Runtime identity changed')
    return value

def serve(root,port):
    value=checked(root)
    key=os.environ.get('DEEPSEEK_API_KEY')
    if not key:raise ValueError('local credential missing')
    data=Path(value['data_root'])
    auth=CodingAuthorization(root/'outbound-scope.json',sha(root/'outbound-scope.json'),root/'coding-calls')
    coding=CodingService(data,authorization=auth,sender=deepseek_sender(key),runtime_python=RUNTIME_PYTHON)
    class ScopedQA(ModelGateway):
        def complete(self,messages,schema):
            checked(root)
            if schema is not CodeDecision:raise ValueError('only code QA decisions authorized')
            material=json.loads(messages[-1]['content']);candidate=material['candidate']
            profile=candidate['profile']
            if material['goal']!=GOALS.get(profile):raise ValueError('QA goal outside scope')
            expected=value['d01_candidate'] if profile=='shield-damage-python-v1' else coding.store.get(OP)['result']['candidate']['manifest_hash']
            if candidate['manifest_hash']!=expected:raise ValueError('QA candidate outside scope')
            records=[] if not self.audit_path.exists() else [json.loads(s) for s in self.audit_path.read_text(encoding='utf-8').splitlines() if s]
            for record in records:
                if record['status']=='reserved':
                    old=json.loads(record['preview']['payload']['messages'][-1]['content'])
                    if old['candidate']['profile']==profile:raise ValueError('this QA case already consumed its one call')
            return super().complete(messages,schema)
    import uvicorn
    import agent_workbench.workbench as web
    original=web.Workbench
    web.Workbench=scoped_workbench_class(value,coding)
    try:
        app=web.create_app(data,coding_service=coding,call_cap=2,audit_path=root/'qa-calls.jsonl',
            model_factory=ScopedQA,model_actions=('verify',),code_demo_root=Path('D:/Desktop/mihoyo-agent-project/local-data/python-coding-d01-v1'),
            test_game_root=Path('D:/Desktop/graytower-game/local-data/worktrees/local-test-content'))
    finally:web.Workbench=original
    uvicorn.run(app,host='127.0.0.1',port=port,access_log=False)

def close(root):
    value=json.loads((root/'outbound-scope.json').read_text(encoding='utf-8'))
    from agent_workbench.coding.responses_transport import CallBudget
    budget=CallBudget(root/'coding-calls',value['coding_grant']|{'authorization_sha256':sha(root/'outbound-scope.json')}).summary()
    records=[] if not (root/'qa-calls.jsonl').exists() else [json.loads(s) for s in (root/'qa-calls.jsonl').read_text(encoding='utf-8').splitlines() if s]
    write(root/'closed.json',{'closed':True,'scope_sha256':sha(root/'outbound-scope.json'),'coding_budget':budget,
        'qa_reserved':sum(r['status']=='reserved' for r in records),'qa_completed':sum(r['status']=='completed' for r in records),
        'reason':'Trial ended; unused budget permanently closed. Original ledgers retained.'})
    print((root/'closed.json').read_text(encoding='utf-8'))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['prepare','serve','close'])
    parser.add_argument('--data',type=Path,required=True);parser.add_argument('--product-data',type=Path);parser.add_argument('--port',type=int,default=18785)
    args=parser.parse_args();root=args.data.resolve()
    if args.action=='prepare':
        if not args.product_data:parser.error('prepare requires product-data')
        prepare(root,args.product_data.resolve())
    elif args.action=='serve':serve(root,args.port)
    else:close(root)
