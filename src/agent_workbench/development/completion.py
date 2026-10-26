"""One bounded local completion campaign. Reuses ordinary task execution receipts.

This is a research runner, not another Agent or a replacement model loop.
Optional revisions consume two fixed slots; they never reset an earlier grant.
"""
from decimal import Decimal
import base64
import hashlib
import json
from pathlib import Path
import time
import httpx
from langchain_core.messages import HumanMessage,ToolMessage
from .assessment import _child,_run_cell,implementation_identity
from .evaluation import PUBLIC,PRIVATE,grade_cell
from .agent import agent_specs
from .model import ToolModel
from .service import DevelopmentTask,run_lock
from .memory import ProjectMemory
from .knowledge import KnowledgeBase
from .workspace import digest,encoded,editable,git
from ..coding.responses_transport import CallBudget

REPO=Path(__file__).resolve().parents[3]
CORPUS=REPO/'research/evals/knowledge-rag-v1/corpus.json'
RAG_TASKS=REPO/'research/evals/knowledge-rag-v1/agent-tasks.json'
RAG_ORACLE=REPO/'research/evals/knowledge-rag-v1/private/rule_acceptance.py'
RUN='completion-v1'
RATES={'input_usd_per_million':'0.30','cached_input_usd_per_million':'0.006','output_usd_per_million':'1.20','pricing_checked_on':'2026-10-27'}
CANARY={**RATES,'model_profile':'reasoned','max_calls':2,'max_input_bytes':12000,'max_output_tokens':4096,'cost_cap_usd':'0.03'}
REVISION={**RATES,'model_profile':'reasoned','max_calls':10,'max_input_bytes':100000,'max_output_tokens':16384,'cost_cap_usd':'0.525'}
CANARY_PROMPT='必须调用probe_add核对17+25后给中文简短结论，结果用阿拉伯数字。'
CANARY_SPEC={'name':'probe_add','description':'返回两个整数的和。','inputSchema':{'type':'object','properties':{'left':{'type':'integer'},'right':{'type':'integer'}},'required':['left','right'],'additionalProperties':False}}

def _read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def _save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix(path.suffix+'.tmp');temporary.write_bytes(encoded(value));temporary.replace(path)

def _seal(path,value):
    value={**value};value['receipt_sha256']=digest(value);_save(path,value);return value

def _receipt(path):
    value=_read(path);body=dict(value);body.pop('receipt_sha256',None)
    if digest(body)!=value.get('receipt_sha256'):raise ValueError('campaign receipt changed')
    return value

def _documents(task,corpus):
    if task.workspace.metadata['baseline_commit']!=corpus['game_head']:raise ValueError('corpus game version changed')
    for source in corpus['sources']:
        preview=task.knowledge.preview_file(task.workspace,source['path'])
        if preview['sha256']!=source['sha256']:raise ValueError('corpus source changed')
        section=next(s for s in preview['sections'] if s['heading']==source['heading'])
        if source.get('section_sha256') and hashlib.sha256(section['text'].encode()).hexdigest()!=source['section_sha256']:raise ValueError('corpus section changed')
        doc=task.knowledge.import_file(task.workspace,source['path'],[source['heading']])
        task.knowledge.set_status(task.workspace.metadata['project'],doc['id'],'confirmed')

def _prepare_cell(root,project,case,grant,*,mode='off',profile='standard',corpus=None,parent=None,feedback=''):
    cell_id=case['cell_id'];request=case['request']
    if parent:request+='\n这是对上一候选的修订。请依据当前候选及以下实际诊断继续完成，不改原游戏：\n'+feedback
    ref=parent['baseline_commit'] if parent else corpus['game_head'] if corpus else 'HEAD'
    task=DevelopmentTask.create(project,root/'tasks'/cell_id,request,ref=ref,tool_profile=profile,knowledge_mode=mode,
        memory=ProjectMemory(root/'project-memory.sqlite'),knowledge=KnowledgeBase(root/'project-knowledge.sqlite'))
    if parent:
        before=task.workspace.baseline['files'];after=_read(root/'tasks'/parent['cell_id']/'final-candidate.json')['files']
        final=_read(root/'tasks'/parent['cell_id']/'final-candidate.json')
        if digest(final)!=parent['final_tree_hash']:raise ValueError('revision parent candidate changed')
        for name in sorted(set(before)|set(after)):
            if before.get(name)==after.get(name):continue
            if not editable(name):raise ValueError('revision parent changed trusted material')
            current=task.workspace.snapshot()['files'].get(name)
            text=base64.b64decode(after[name]['content']).decode('utf-8') if name in after else None
            sha=task.workspace.read_file(name)['sha256'] if current else None
            task.workspace.write_file('inherit-'+digest(name),name,sha,text)
    if mode=='lexical':_documents(task,corpus)
    child=task.prepare(RUN,grant)
    return {'cell_id':cell_id,'task_id':case['id'],'stage':case['stage'],'profile':profile,'knowledge_mode':mode,
            'read_only':profile=='review','run_id':RUN,'grant':grant,'scope_sha256':child['scope_sha256'],
            'baseline_commit':child['baseline_commit'],'request_file_hash':digest(_read(task.root/'request.json')),
            'project_hash':digest(_read(task.root/'project.json')),'baseline_tree_hash':digest(task.workspace.baseline),
            'parent_cell_id':parent['cell_id'] if parent else None,'shared_stores':True}

def prepare_campaign(project,root,*,corpus_path=CORPUS):
    root=Path(root).resolve();root.mkdir(parents=True,exist_ok=False);corpus=_read(corpus_path)
    _save(root/'corpus.json',corpus);cases=_read(PUBLIC);cells=[];previews=[]
    grants=[(18,'0.92'),(24,'1.22'),(10,'0.52')]
    for case,(calls,cap) in zip(cases,grants,strict=True):
        grant={**RATES,'model_profile':'reasoned','max_calls':calls,'max_input_bytes':100000,'max_output_tokens':16384,'cost_cap_usd':cap}
        cells.append(_prepare_cell(root,project,{**case,'cell_id':case['id'],'stage':'development'},grant))
    for case in _read(RAG_TASKS):
        for mode in ('off','lexical'):
            grant={**RATES,'model_profile':'reasoned','max_calls':8,'max_input_bytes':100000,'max_output_tokens':8192,'cost_cap_usd':'0.33'}
            cells.append(_prepare_cell(root,project,{**case,'cell_id':case['id']+'-'+mode,'stage':'rag'},grant,mode=mode,profile='review',corpus=corpus))
    for cell in cells:previews.append({'cell_id':cell['cell_id'],**_read(root/'tasks'/cell['cell_id']/'runs'/RUN/'outbound-preview.json')})
    authorization={'endpoint':ToolModel.endpoint,'model':'deepseek-flash','thinking':{'type':'enabled'},'reasoning_effort':'high',
        'max_calls':106,'cost_cap_usd':'5.10','canary_grant':CANARY,'revision_slots':[REVISION,REVISION],
        'actions':'协议2次、原3题52次、可选2次候选修订各10次、2题有/无资料各8次共32次；失败和未知占额度，不自动重试未知，不改原游戏，不自动采用。',
        'materials':'49份允许范围游戏原始源码/配置/既有回归、公开需求、已审2份规则文档6章节、工具定义、推理/分析、候选产生的代码与Diff、实际执行和必要错误诊断；不发送凭据、独立验收源码或参考修复。修订仅继承本批候选与必要诊断。'}
    if any(c['baseline_commit']!=corpus['game_head'] for c in cells):raise ValueError('campaign contains different game baselines')
    preview={'authorization':authorization,'canary_request':CANARY_PROMPT,'canary_tools':[CANARY_SPEC],'cells':previews}
    _save(root/'outbound-preview.json',preview)
    maximum=sum((Decimal(c['grant']['max_input_bytes']+2048)*Decimal('0.30')+Decimal(c['grant']['max_output_tokens'])*Decimal('1.20'))*c['grant']['max_calls']/1_000_000 for c in cells)
    maximum+=sum((Decimal(g['max_input_bytes']+2048)*Decimal('0.30')+Decimal(g['max_output_tokens'])*Decimal('1.20'))*g['max_calls']/1_000_000 for g in [CANARY,REVISION,REVISION])
    scope={'schema':'development-completion-campaign-v1',**authorization,'project':str(Path(project).resolve()),'baseline_commit':corpus['game_head'],'cells':cells,
        'implementation_hash':implementation_identity(),'public_tasks_hash':digest(_read(PUBLIC)),'rag_tasks_hash':digest(_read(RAG_TASKS)),
        'oracle_hashes':[digest(PRIVATE.read_text(encoding='utf-8')),digest(RAG_ORACLE.read_text(encoding='utf-8'))],
        'corpus_hash':digest(corpus),'preview_hash':digest(preview),'conservative_max_usd':str(maximum),
        'limitation':'同题开发与有限规则核查，不是独立成功率或Bug修复RAG增益。候选程序检查与最终语义分别判断。'}
    scope['scope_sha256']=digest(scope);_save(root/'outbound-scope.json',scope);return scope

def verify_campaign(root,scope_hash,*,check_project=True):
    root=Path(root).resolve();scope=_read(root/'outbound-scope.json');body=dict(scope);body.pop('scope_sha256',None)
    if (scope['scope_sha256']!=scope_hash or digest(body)!=scope_hash or scope['implementation_hash']!=implementation_identity()
        or digest(_read(root/'outbound-preview.json'))!=scope['preview_hash'] or digest(_read(root/'corpus.json'))!=scope['corpus_hash']
        or digest(_read(PUBLIC))!=scope['public_tasks_hash'] or digest(_read(RAG_TASKS))!=scope['rag_tasks_hash']
        or scope['oracle_hashes']!=[digest(PRIVATE.read_text(encoding='utf-8')),digest(RAG_ORACLE.read_text(encoding='utf-8'))]):raise ValueError('campaign scope, source or material changed')
    for cell in scope['cells']:_child(root,cell)
    if check_project and (git(scope['project'],'rev-parse','HEAD').decode().strip()!=scope['baseline_commit'] or git(scope['project'],'status','--porcelain')):
        raise ValueError('original project HEAD or uncommitted files changed')
    return scope

def _run_canary(root,key):
    wires=[]
    def capture(request):wires.append(json.loads(request.content))
    client=httpx.Client(timeout=180,follow_redirects=False,trust_env=False,event_hooks={'request':[capture]})
    model=ToolModel(root/'canary/model',CANARY,[CANARY_SPEC],api_key=key,http_client=client)
    result={'pass':False}
    try:
        messages=[HumanMessage(content=CANARY_PROMPT)]
        first=model.complete(messages,'canary-0')
        if len(first.tool_calls)!=1:raise ValueError('canary did not call one tool')
        call=first.tool_calls[0]
        if call['name']!='probe_add' or call['args']!={'left':17,'right':25}:raise ValueError('canary unexpected tool')
        reasoning=first.additional_kwargs.get('reasoning_content')
        if not isinstance(reasoning,str):raise ValueError('reasoning was not returned')
        final=model.complete(messages+[first,ToolMessage(content='42',tool_call_id=call['id'])],'canary-1',final_only=True)
        if wires[-1]['messages'][1].get('reasoning_content')!=reasoning:raise ValueError('reasoning echo missing')
        result={'pass':'42' in str(final.content),'reasoning_roundtrip':True,'summary':final.content}
    except Exception as exc:result['error_type']=type(exc).__name__
    finally:
        result['budget']=model.summary();model.close();_save(root/'canary/wires.json',wires)
    return result

def _grade(root,record):
    task,_=_child(root,record);tree=_read(task.root/'final-candidate.json')
    if digest(tree)!=record['final_tree_hash']:raise ValueError('final candidate changed')
    folder=root/'grading'/record['cell_id'];path=folder/'campaign-grade.json'
    if path.exists():grade=_receipt(path)['grade']
    elif (folder/'grade-started.json').exists():grade={'verdict':'INCONCLUSIVE','note':'prior grading attempt requires reconciliation; not repeated'}
    else:
        _save(folder/'grade-started.json',{'tree_hash':digest(tree)})
        try:grade=grade_cell(task,record,folder,tree=tree,**({'oracle':RAG_ORACLE} if record['stage']=='rag' else {}))
        except Exception as exc:grade={'verdict':'INCONCLUSIVE','error_type':type(exc).__name__}
        _seal(path,{'tree_hash':digest(tree),'grade':grade})
    value={**record,'model_record_sha256':record['record_sha256'],'grade':grade,'semantic_review':'pending'}
    value.pop('record_sha256',None);return value

def _best(root):
    rows=_receipt(root/'phase-development.json')['records'];values={r['task_id']:r for r in rows}
    if (root/'phase-revisions.json').exists():
        for row in _receipt(root/'phase-revisions.json').get('records',[]):values[row['task_id']]=row
    return values

def run_stage(root,scope_hash,stage,api_key,model_factory=None):
    root=Path(root).resolve()
    with run_lock(root):
        scope=verify_campaign(root,scope_hash)
        if (root/'campaign-close.json').exists():raise ValueError('campaign closed')
        if stage not in ('canary','development','revisions','rag'):raise ValueError('unknown campaign stage')
        path=root/f'phase-{stage}.json'
        if path.exists():raise ValueError('stage already attempted; do not rerun')
        if model_factory is None and not api_key:raise ValueError('explicit credential required')
        if stage!='canary':
            canary=_receipt(root/'phase-canary.json')
            if not canary.get('pass') or canary.get('budget',{}).get('unknown'):raise ValueError('canary must pass with known usage first')
        if stage in ('revisions','rag') and not (root/'phase-development.json').exists():raise ValueError('development not completed')
        if stage in ('revisions','rag'):
            development=_receipt(root/'phase-development.json')
            required={c['task_id'] for c in scope['cells'] if c['stage']=='development'}
            rows=development.get('records',[])
            if (development.get('state')!='closed' or {r['task_id'] for r in rows}!=required or any(r['budget'].get('unknown') for r in rows)
                or any(r['grade']['verdict']=='INCONCLUSIVE' for r in rows)):
                raise ValueError('all core attempts must have known usage and conclusive checks before continuing')
        if stage=='rag' and any(r['grade']['verdict']!='PASS' or not r['handoff_completed'] or r['budget'].get('unknown') for r in _best(root).values()):raise ValueError('finish core tasks before RAG')
        _seal(path,{'stage':stage,'state':'started','scope_sha256':scope_hash})
        if stage=='canary':
            result=_run_canary(root,api_key);return _seal(path,{'stage':stage,'state':'closed',**result})
        cells=[c for c in scope['cells'] if c['stage']==stage];records=[]
        if stage=='revisions':
            current=_best(root)
            for slot,grant in enumerate(scope['revision_slots'],1):
                pending=[r for r in current.values() if r['grade']['verdict']!='PASS' or not r['handoff_completed']]
                if not pending:break
                parent=pending[0]
                if parent['budget'].get('unknown'):raise ValueError('unknown request cannot be retried')
                original=next(c for c in _read(PUBLIC) if c['id']==parent['task_id'])
                allowed={'AssertionError','ValueError','TypeError','ValidationError','KeyError','RuntimeError'}
                errors=sorted({c.get('error_type') for c in parent['grade'].get('independent_checks',[]) if c.get('status')=='FAIL' and c.get('error_type') in allowed})
                feedback='独立检查或交付未通过。诊断类别：'+(', '.join(errors) or '未完整交付')+'。请依原公开需求，通过自己的工具复现并修订；本反馈不包含私有断言、日志或参考实现。'
                case={**original,'cell_id':original['id']+f'-revision-{slot}','stage':'revisions'}
                verify_campaign(root,scope_hash)
                cell=_prepare_cell(root,scope['project'],case,grant,parent=parent,feedback=feedback)
                _save(root/f'revision-{slot}-scope.json',cell)
                row=_grade(root,_run_cell(root,cell,api_key,model_factory));records.append(row);current[row['task_id']]=row
                if row['budget'].get('unknown') or row['grade']['verdict']=='INCONCLUSIVE':break
        else:
            for cell in cells:
                verify_campaign(root,scope_hash)
                task,child=_child(root,cell)
                if (task._batch(RUN)/'claimed').exists() or task.workspace.inspect()['tree_hash']!=child['candidate_tree_hash']:raise ValueError('child already started or changed')
                row=_grade(root,_run_cell(root,cell,api_key,model_factory));records.append(row)
                if row['budget'].get('unknown'):break
        return _seal(path,{'stage':stage,'state':'closed','records':records})

def close_campaign(root,scope_hash):
    root=Path(root).resolve()
    with run_lock(root):
        scope=verify_campaign(root,scope_hash,check_project=False)
        if (root/'campaign-close.json').exists():return _receipt(root/'campaign-close.json')
        budgets=[]
        canary=root/'canary/model/responses-ledger.sqlite'
        if canary.exists():budgets.append(CallBudget(canary.parent,CANARY).summary())
        elif (root/'phase-canary.json').exists():budgets.append(_receipt(root/'phase-canary.json').get('budget',{}))
        for folder in (root/'tasks').iterdir():
            path=folder/'runs'/RUN/'outbound-scope.json'
            if not path.exists():continue
            child=_read(path);batch=path.parent;database=batch/'model/responses-ledger.sqlite'
            if database.exists():budgets.append(CallBudget(database.parent,child['grant']).summary())
            old=_read(batch/'run-result.json') if (batch/'run-result.json').exists() else {'state':'not_started'}
            _save(batch/'campaign-close.json',{'closed':True,'scope_sha256':scope_hash})
            (batch/'claimed').mkdir(exist_ok=True);_save(batch/'run-result.json',{**old,'closed':True,'campaign_closed':True})
        reserved=sum(b.get('reserved',0) for b in budgets)
        cost=sum((Decimal(b.get('known_cost_usd','0')) for b in budgets),Decimal(0))
        if reserved>scope['max_calls'] or cost>Decimal(scope['cost_cap_usd']):raise ValueError('campaign allowance exceeded')
        return _seal(root/'campaign-close.json',{'closed':True,'scope_sha256':scope_hash,'reserved_calls':reserved,
            'known_cost_usd':str(cost),'unknown_requests':sum(b.get('unknown',0) for b in budgets),
            'unused_calls_closed':scope['max_calls']-reserved})
