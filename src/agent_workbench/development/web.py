"""Single-user local workbench for the real development service."""
import asyncio
import base64
import json
import re
from pathlib import Path
import sys
import threading
import uuid
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.responses import FileResponse,JSONResponse,RedirectResponse
from starlette.routing import Route,Mount
from starlette.staticfiles import StaticFiles
from ..workbench import LocalOriginMiddleware
from .service import DevelopmentTask
from .memory import ProjectMemory
from .agent import saved_agent_state
from .knowledge import KnowledgeBase,search_knowledge
from .workspace import encoded,editable
from .adoption import Adoption
from .sandbox import CHECK_SETS,IMAGE

DEFAULT_GRANT={'model_profile':'reasoned','max_calls':18,'max_input_bytes':100000,'max_output_tokens':16384,'cost_cap_usd':'0.95',
    'input_usd_per_million':'0.30','cached_input_usd_per_million':'0.006','output_usd_per_million':'1.20',
    'pricing_checked_on':'2026-10-18'}
CHECK_LABELS={'rules':'完整规则回归','effects':'伤害、护盾与边界','scheduler':'行动顺序','session':'战斗与保存恢复','resource_inputs':'战技点参数与接口'}


class Workbench:
    def __init__(self,root,*,api_key='',runtime_python=None,dist=None,default_project='D:/Desktop/graytower-game',launcher=None):
        self.root=Path(root).resolve();(self.root/'tasks').mkdir(parents=True,exist_ok=True)
        self.api_key=api_key;self.runtime_python=Path(runtime_python or sys.executable)
        self.dist=Path(dist) if dist else Path(__file__).resolve().parents[3]/'frontend/dist'
        self.default_project=default_project;self.active={};self.lock=threading.RLock();self.cache={}
        self.memory=ProjectMemory(self.root/'project-memory.sqlite')
        self.knowledge=KnowledgeBase(self.root/'project-knowledge.sqlite')
        self.launch=launcher or (lambda work:threading.Thread(target=work,daemon=True).start())

    def task(self,task_id):
        if not isinstance(task_id,str) or not re.fullmatch('[a-z0-9][a-z0-9_-]{0,79}',task_id):raise HTTPException(404)
        if not (self.root/'tasks'/task_id/'project.json').is_file():raise HTTPException(404)
        if task_id not in self.cache:self.cache[task_id]=DevelopmentTask(self.root/'tasks'/task_id,memory=self.memory,knowledge=self.knowledge)
        return self.cache[task_id]

    def detail(self,task_id):
        task=self.task(task_id);view=task.summary();runs=[];events=[];explanation='';resumable=None
        folders=[]
        for folder in (task.root/'runs').glob('*') if (task.root/'runs').exists() else []:
            scope_path=folder/'outbound-scope.json'
            if not scope_path.exists():continue
            scope=json.loads(scope_path.read_text(encoding='utf-8'))
            folders.append((scope.get('created_at_ns',scope_path.stat().st_mtime_ns),folder,scope))
        folders.sort(key=lambda item:(item[0],item[1].name))
        unfinished=set(task.unfinished_runs())
        selected_run=self.active.get(task_id) or next((folder.name for _,folder,_ in reversed(folders) if folder.name in unfinished),None) or (folders[-1][1].name if folders else None)
        for created,folder,scope in folders:
            result=json.loads((folder/'run-result.json').read_text(encoding='utf-8')) if (folder/'run-result.json').exists() else None
            error=json.loads((folder/'worker-error.json').read_text(encoding='utf-8')) if (folder/'worker-error.json').exists() else {}
            if self.active.get(task_id)==folder.name or (result and not result.get('error_type')):error={}
            claimed=(folder/'claimed').exists()
            state=result['state'] if result else 'running' if self.active.get(task_id)==folder.name else 'interrupted' if claimed else 'not_started' if error else 'prepared'
            runs.append({'run_id':folder.name,'state':state,'budget':result.get('budget') if result else None,
                         'created_at_ns':created,'error_type':error.get('error_type') or (result or {}).get('error_type'),
                         'error_message':error.get('message') or ('运行未正常结束，请查看保留的执行记录。' if (result or {}).get('error_type') else None)})
            if folder.name!=selected_run:continue
            if scope.get('schema')=='development-langgraph-v1':
                agent=(result or {}).get('agent',{})
                if claimed and not (result or {}).get('closed',False) and self.active.get(task_id)!=folder.name:
                    checkpoint=saved_agent_state(folder/'graph')
                    if checkpoint and checkpoint['status'] in ('waiting_user','waiting_checks'):
                        agent=checkpoint;state=checkpoint['status'];runs[-1]['state']=state
                explanation=agent.get('summary','')
                if claimed and not (result or {}).get('closed',False):
                    resumable={'run_id':folder.name,'scope_sha256':scope['scope_sha256'],'status':state,
                               'question':agent.get('question'),'note':agent.get('note') or '沿原任务和剩余额度继续，不会重置预算。'}
                path=folder/'graph/events.jsonl'
                if path.exists():
                    for line in path.read_text(encoding='utf-8').splitlines()[-200:]:
                        try:event=json.loads(line)
                        except ValueError:continue
                        if event.get('type')=='tool':events.append({'tool':event['tool'],'success':event['success'],'sources':event.get('sources',[])})
                continue
            path=folder/'runtime/events.jsonl'
            if path.exists():
                with path.open('rb') as stream:
                    size=path.stat().st_size;stream.seek(max(0,size-1_000_000))
                    lines=stream.read().decode('utf-8',errors='replace').splitlines()
                for line in lines:
                    try:event=json.loads(line)
                    except ValueError:continue
                    if event.get('type')=='host_call':
                        result_value=event.get('result',{})
                        events.append({'tool':event.get('params',{}).get('tool','操作'), 'success':result_value.get('success',False)})
                    item=event.get('params',{}).get('item',{})
                    if item.get('type')=='agentMessage' and isinstance(item.get('text'),str):explanation=item['text']
        state='discarded' if (task.root/'discarded.json').exists() else 'candidate'
        return {**view,'task_id':task_id,'project_name':Path(view['project']).name,'short_version':view['baseline_commit'][:8],
                'workflow_state':state,'runs':runs,'active_run_id':self.active.get(task_id),
                'model_state':next((r['state'] for r in runs if r['run_id']==selected_run),'not_started'),'busy':task_id in self.active,
                'model_error':next((r['error_message'] for r in runs if r['run_id']==selected_run),None),
                'tool_events':events[-24:],'model_summary':explanation,'resumable_run':resumable,'engine':'langgraph'}

    def writable(self,task_id):
        task=self.task(task_id)
        if task_id in self.active:raise ValueError('AI正在处理，请等待当前任务结束。')
        if (task.root/'discarded.json').exists():raise ValueError('这份候选已放弃；请创建新任务。')
        if task.workspace.metadata.get('archived'):raise ValueError('这份任务已归档，仅可查看。')
        return task

    def start(self,task_id,run_id,scope_hash,*,resume=False,answer=None):
        task=self.writable(task_id);folder=task._batch(run_id)
        scope=json.loads((folder/'outbound-scope.json').read_text(encoding='utf-8'))
        if scope_hash!=scope['scope_sha256']:raise ValueError('授权预览不匹配，请重新查看。')
        if (folder/'claimed').exists() and not resume:return self.detail(task_id)
        if resume:
            detail=self.detail(task_id);saved=detail.get('resumable_run')
            if not saved or saved['run_id']!=run_id:raise ValueError('这次任务已结束或不能继续，请查看保存的结果。')
            if saved['status']=='waiting_user' and (not isinstance(answer,str) or not answer.strip()):
                raise ValueError('请先回答AI提出的问题。')
        if not self.api_key:raise ValueError('本机尚未配置DEEPSEEK_API_KEY，请配置后重新启动。')
        self.active[task_id]=run_id
        def work():
            try:task.execute(run_id,scope_hash,api_key=self.api_key,resume=resume,answer=answer)
            except Exception as exc:
                # Never copy transport errors, request headers or credentials to the UI.
                stale=isinstance(exc,ValueError) and 'authorization scope or current candidate changed' in str(exc)
                message=('材料或候选已变化，本批尚未开始。请重新准备材料并确认。' if stale else
                         '本批尚未开始，请检查本机环境后重新查看材料。' if not (folder/'claimed').exists() else
                         '运行中断，已保留记录。可显式继续原任务；未知模型请求和检查不会自动重发。')
                (folder/'worker-error.json').write_bytes(encoded({'error_type':type(exc).__name__,'message':message}))
            finally:
                with self.lock:self.active.pop(task_id,None)
        self.launch(work)
        return self.detail(task_id)


def create_app(root,**options):
    workbench=Workbench(root,**options)

    async def body(request,required=(),optional=()):
        raw=await request.body()
        if len(raw)>1_100_000:raise ValueError('输入内容太长。')
        value=json.loads(raw or b'{}')
        if not isinstance(value,dict) or set(required)-set(value) or set(value)-set(required)-set(optional):
            raise ValueError('请求字段不完整或包含不支持的选项。')
        return value

    async def status(request):
        return JSONResponse({'model':'deepseek-flash','key_configured':bool(workbench.api_key),
            'application':'graytower-development-workbench','workbench_root':str(Path(__file__).resolve().parents[3]),
            'runtime_available':True,'engine':'langgraph','framework':'LangGraph + LangChain','default_project':workbench.default_project,
            'checks':[{'value':k,'label':CHECK_LABELS[k]} for k in CHECK_SETS],
            'model_note':'浏览、创建候选和检查不调用模型。只有你确认发送范围与费用后才会开始。',
            'image':IMAGE})

    async def tasks(request):
        if request.method=='GET':
            values=[]
            for folder in sorted((workbench.root/'tasks').iterdir(),key=lambda p:p.stat().st_mtime,reverse=True):
                if (folder/'project.json').exists():
                    t=workbench.task(folder.name)
                    values.append({'task_id':folder.name,'request':t.request,'project':t.workspace.metadata['project']})
            return JSONResponse({'tasks':values})
        args=await body(request,['project','request'],['knowledge_mode'])
        if not isinstance(args['project'],str):raise ValueError('请填写本机游戏Git项目目录。')
        task_id=uuid.uuid4().hex
        await asyncio.to_thread(DevelopmentTask.create,Path(args['project']),workbench.root/'tasks'/task_id,args['request'],memory=workbench.memory,
                                knowledge=workbench.knowledge,knowledge_mode=args.get('knowledge_mode','lexical'))
        return JSONResponse(workbench.detail(task_id))

    async def task_action(request):
        task_id=request.path_params['task_id'];action=request.path_params.get('action','')
        if request.method=='GET':
            if action=='knowledge':
                task=workbench.task(task_id)
                return JSONResponse({'documents':workbench.knowledge.list(task.workspace.metadata['project']),
                    'version':task.workspace.metadata['baseline_commit'],'mode':task.knowledge_mode})
            if action=='knowledge-sources':
                return JSONResponse({'sources':workbench.knowledge.sources(workbench.task(task_id).workspace)})
            if action=='knowledge-source':
                return JSONResponse(workbench.knowledge.preview_file(workbench.task(task_id).workspace,request.query_params.get('path','')))
            if action=='memories':
                task=workbench.task(task_id)
                return JSONResponse({'memories':workbench.memory.list(task.workspace.metadata['project']),
                                     'version':task.workspace.metadata['baseline_commit']})
            if action=='file':
                task=workbench.task(task_id);name=request.query_params.get('path','')
                current=task.workspace.read_file(name);before=task.workspace.baseline['files'].get(name)
                return JSONResponse({**current,'before':base64.b64decode(before['content']).decode('utf-8') if before else '',
                                     'editable':editable(name)})
            if action=='scope':
                task=workbench.task(task_id);folder=task._batch(request.query_params.get('run_id',''))
                return FileResponse(folder/'outbound-preview.json',filename='模型材料预览.json')
            return JSONResponse(workbench.detail(task_id))
        if action=='knowledge-search':
            args=await body(request,['query'])
            task=workbench.task(task_id)
            return JSONResponse({'results':search_knowledge(task.knowledge_snapshot(),args['query'])})
        if action=='knowledge':
            args=await body(request,['action'],['path','headings','id','status'])
            with workbench.lock:
                task=workbench.writable(task_id);project=task.workspace.metadata['project'];operation=args.pop('action')
                if operation=='import':
                    if set(args)-{'path','headings'} or 'path' not in args:raise ValueError('请选择当前版本的资料和章节。')
                    value=workbench.knowledge.import_file(task.workspace,**args)
                elif operation=='status':
                    if set(args)!={'id','status'}:raise ValueError('请指定资料及确认状态。')
                    value=workbench.knowledge.set_status(project,args['id'],args['status'])
                elif operation=='delete':
                    if set(args)!={'id'}:raise ValueError('删除只需要资料编号。')
                    value=workbench.knowledge.delete(project,args['id'])
                else:raise ValueError('不支持的资料操作。')
                return JSONResponse(value)
        if action=='memories':
            args=await body(request,['action'],['id','content','kind','version','status'])
            with workbench.lock:
                task=workbench.writable(task_id);project=task.workspace.metadata['project'];operation=args.pop('action')
                if operation=='add':
                    if set(args)-{'content','kind','version'} or {'content','version'}-set(args):raise ValueError('请填写记忆内容和适用版本。')
                    value=workbench.memory.add(project,source='user:workbench',status='confirmed',**args)
                elif operation=='update':
                    identity=args.pop('id',None);value=workbench.memory.update(project,identity,**args)
                elif operation=='delete':
                    if set(args)!={'id'}:raise ValueError('删除只需要记忆编号。')
                    value=workbench.memory.delete(project,args['id'])
                else:raise ValueError('不支持的记忆操作。')
                return JSONResponse(value)
        schemas={'check':(['check_set'],[]),'prepare':([],[]),'run':(['run_id','scope_sha256','accept_data','accept_cost'],[]),
                 'edit':(['operation_id','path','expected_sha256','content'],[]),'apply':(['tree_hash'],[]),
                 'restore':(['operation_id'],[]),'discard':(['tree_hash'],[]),'export':([],[]),
                 'resume':(['run_id','scope_sha256'],['answer']),
                 'delivery-prepare':(['kind'],['operation_id']),'delivery-resolve':(['preparation_id'],[]),
                 'delivery-check':(['preparation_id'],[]),'delivery-approve':(['preparation_id','approval_hash'],[]),
                 'delivery-discard':(['preparation_id','cleanup_hash'],[]),
                 'archive':(['tree_hash'],[])}
        if action not in schemas:raise HTTPException(404)
        args=await body(request,*schemas[action])
        with workbench.lock:
            task=workbench.writable(task_id)
            if action.startswith('delivery-'):
                if task.delivery is None:raise ValueError('旧任务请使用原采用/恢复操作。')
                if action=='delivery-prepare':task.delivery.prepare(**args)
                elif action=='delivery-resolve':task.delivery.resolve(args['preparation_id'])
                elif action=='delivery-check':task.delivery.check(args['preparation_id'])
                elif action=='delivery-discard':task.delivery.discard(args['preparation_id'],args['cleanup_hash'])
                else:task.delivery.approve(args['preparation_id'],args['approval_hash'])
            elif action=='archive':
                if task.delivery is None:raise ValueError('旧任务无需清理 Git 工作树。')
                with task.workspace.mutation_lock():
                    if args['tree_hash']!=task.workspace.inspect()['tree_hash']:raise ValueError('候选已变化，请重新查看。')
                    task.workspace.archive()
            elif action=='check':task.jobs.start(task.workspace,args['check_set'])
            elif action=='edit':
                with task.workspace.delivery_lock():task.workspace.write_file(**args)
            elif action=='apply':Adoption(task.workspace).apply(args['tree_hash'])
            elif action=='restore':Adoption(task.workspace).restore(args['operation_id'])
            elif action=='discard':
                if args['tree_hash']!=task.workspace.inspect()['tree_hash']:raise ValueError('候选已变化，请重新查看。')
                adopted=Adoption(task.workspace).status() if task.delivery is None else None
                if adopted and adopted['state']!='restored':raise ValueError('请先恢复已采用的修改，再放弃候选。')
                if task.delivery is not None:task.workspace.archive()
                (task.root/'discarded.json').write_bytes(encoded({'tree_hash':args['tree_hash']}))
            elif action=='export':return JSONResponse(task.export())
            elif action=='prepare':
                run_id='user-'+uuid.uuid4().hex
                scope=task.prepare(run_id,DEFAULT_GRANT)
                preview=json.loads((task._batch(run_id)/'outbound-preview.json').read_text(encoding='utf-8'))
                return JSONResponse({**scope,'run_id':run_id,'file_count':len(preview['files']),
                                     'knowledge_document_count':len(preview.get('knowledge',{}).get('documents',[]))})
            elif action=='run':
                if args['accept_data'] is not True or args['accept_cost'] is not True:
                    raise ValueError('请明确确认外发材料和本批费用上限。')
                return JSONResponse(workbench.start(task_id,args['run_id'],args['scope_sha256']))
            elif action=='resume':
                return JSONResponse(workbench.start(task_id,args['run_id'],args['scope_sha256'],resume=True,answer=args.get('answer')))
            return JSONResponse(workbench.detail(task_id))

    async def page(request):
        if request.url.path=='/':return RedirectResponse('/development')
        path=workbench.dist/'index.html'
        if not path.is_file():return JSONResponse({'error':'前端尚未构建，请按启动窗口提示安装环境。'},status_code=503)
        return FileResponse(path)

    async def bad_input(request,exc):return JSONResponse({'error':str(exc)[:700]},status_code=422)
    routes=[Route('/api/development/status',status),Route('/api/development/tasks',tasks,methods=['GET','POST']),
            Route('/api/development/tasks/{task_id}',task_action),
            Route('/api/development/tasks/{task_id}/{action}',task_action,methods=['GET','POST']),
            Route('/',page),Route('/development',page)]
    if (workbench.dist/'assets').is_dir():routes.append(Mount('/assets',StaticFiles(directory=workbench.dist/'assets')))
    app=Starlette(routes=routes,exception_handlers={ValueError:bad_input,OSError:bad_input})
    app.add_middleware(LocalOriginMiddleware);app.state.workbench=workbench
    return app
