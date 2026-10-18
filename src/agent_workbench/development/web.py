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
from ..coding.responses_transport import deepseek_sender,CallBudget
from .service import DevelopmentTask
from .workspace import encoded,editable
from .adoption import Adoption
from .sandbox import CHECK_SETS,IMAGE

DEFAULT_GRANT={'max_calls':18,'max_input_bytes':150000,'max_output_tokens':4096,'cost_cap_usd':'0.95',
    'input_usd_per_million':'0.30','cached_input_usd_per_million':'0.006','output_usd_per_million':'1.20',
    'pricing_checked_on':'2026-10-18'}
CHECK_LABELS={'rules':'完整规则回归','effects':'伤害、护盾与边界','scheduler':'行动顺序','session':'战斗与保存恢复','resource_inputs':'战技点参数与接口'}


class Workbench:
    def __init__(self,root,*,api_key='',runtime_python=None,dist=None,default_project='D:/Desktop/graytower-game'):
        self.root=Path(root).resolve();(self.root/'tasks').mkdir(parents=True,exist_ok=True)
        self.api_key=api_key;self.runtime_python=Path(runtime_python or sys.executable)
        self.dist=Path(dist) if dist else Path(__file__).resolve().parents[3]/'frontend/dist'
        self.default_project=default_project;self.active=set();self.lock=threading.RLock();self.cache={}

    def task(self,task_id):
        if not isinstance(task_id,str) or not re.fullmatch('[a-f0-9]{32}',task_id):raise HTTPException(404)
        if not (self.root/'tasks'/task_id/'project.json').is_file():raise HTTPException(404)
        if task_id not in self.cache:self.cache[task_id]=DevelopmentTask(self.root/'tasks'/task_id)
        return self.cache[task_id]

    def detail(self,task_id):
        task=self.task(task_id);view=task.summary();runs=[];events=[];explanation=''
        for folder in sorted((task.root/'runs').glob('*')) if (task.root/'runs').exists() else []:
            if not (folder/'outbound-scope.json').exists():continue
            scope=json.loads((folder/'outbound-scope.json').read_text(encoding='utf-8'))
            result=json.loads((folder/'run-result.json').read_text(encoding='utf-8')) if (folder/'run-result.json').exists() else None
            state=result['state'] if result else 'running' if task_id in self.active else 'interrupted' if (folder/'claimed').exists() else 'prepared'
            runs.append({'run_id':folder.name,'state':state,'budget':result.get('budget') if result else None,
                         'error_type':result.get('error_type') if result else None})
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
                'workflow_state':state,'adoption':Adoption(task.workspace).status(),'runs':runs,
                'model_state':runs[-1]['state'] if runs else 'not_started','busy':task_id in self.active,
                'tool_events':events[-24:],'model_summary':explanation}

    def writable(self,task_id):
        task=self.task(task_id)
        if task_id in self.active:raise ValueError('AI正在处理，请等待当前任务结束。')
        if (task.root/'discarded.json').exists():raise ValueError('这份候选已放弃；请创建新任务。')
        return task

    def start(self,task_id,run_id,scope_hash):
        task=self.writable(task_id);folder=task._batch(run_id)
        scope=json.loads((folder/'outbound-scope.json').read_text(encoding='utf-8'))
        if scope_hash!=scope['scope_sha256']:raise ValueError('授权预览不匹配，请重新查看。')
        if (folder/'claimed').exists():return self.detail(task_id)
        if not self.api_key:raise ValueError('本机尚未配置DEEPSEEK_API_KEY，请配置后重新启动。')
        if not self.runtime_python.is_file():raise ValueError('未找到官方SDK解释器，请先运行环境安装。')
        self.active.add(task_id)
        def work():
            try:task.execute(run_id,scope_hash,self.runtime_python,Path(sys.executable),sender=deepseek_sender(self.api_key))
            except Exception as exc:
                (folder/'worker-error.json').write_bytes(encoded({'error_type':type(exc).__name__}))
            finally:
                with self.lock:self.active.discard(task_id)
        threading.Thread(target=work,daemon=True).start()
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
            'runtime_available':workbench.runtime_python.is_file(),'default_project':workbench.default_project,
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
        args=await body(request,['project','request'])
        if not isinstance(args['project'],str):raise ValueError('请填写本机游戏Git项目目录。')
        task_id=uuid.uuid4().hex
        await asyncio.to_thread(DevelopmentTask.create,Path(args['project']),workbench.root/'tasks'/task_id,args['request'])
        return JSONResponse(workbench.detail(task_id))

    async def task_action(request):
        task_id=request.path_params['task_id'];action=request.path_params.get('action','')
        if request.method=='GET':
            if action=='file':
                task=workbench.task(task_id);name=request.query_params.get('path','')
                current=task.workspace.read_file(name);before=task.workspace.baseline['files'].get(name)
                return JSONResponse({**current,'before':base64.b64decode(before['content']).decode('utf-8') if before else '',
                                     'editable':editable(name)})
            if action=='scope':
                task=workbench.task(task_id);folder=task._batch(request.query_params.get('run_id',''))
                return FileResponse(folder/'outbound-preview.json',filename='模型材料预览.json')
            return JSONResponse(workbench.detail(task_id))
        schemas={'check':(['check_set'],[]),'prepare':([],[]),'run':(['run_id','scope_sha256','accept_data','accept_cost'],[]),
                 'edit':(['operation_id','path','expected_sha256','content'],[]),'apply':(['tree_hash'],[]),
                 'restore':(['operation_id'],[]),'discard':(['tree_hash'],[]),'export':([],[])}
        if action not in schemas:raise HTTPException(404)
        args=await body(request,*schemas[action])
        with workbench.lock:
            task=workbench.writable(task_id)
            if action=='check':task.jobs.start(task.workspace,args['check_set'])
            elif action=='edit':task.workspace.write_file(**args)
            elif action=='apply':Adoption(task.workspace).apply(args['tree_hash'])
            elif action=='restore':Adoption(task.workspace).restore(args['operation_id'])
            elif action=='discard':
                if args['tree_hash']!=task.workspace.inspect()['tree_hash']:raise ValueError('候选已变化，请重新查看。')
                adopted=Adoption(task.workspace).status()
                if adopted and adopted['state']!='restored':raise ValueError('请先恢复已采用的修改，再放弃候选。')
                (task.root/'discarded.json').write_bytes(encoded({'tree_hash':args['tree_hash']}))
            elif action=='export':return JSONResponse(task.export())
            elif action=='prepare':
                run_id='user-'+uuid.uuid4().hex
                scope=task.prepare(run_id,DEFAULT_GRANT)
                return JSONResponse({**scope,'run_id':run_id,'file_count':len(json.loads((task._batch(run_id)/'outbound-preview.json').read_text(encoding='utf-8'))['files'])})
            elif action=='run':
                if args['accept_data'] is not True or args['accept_cost'] is not True:
                    raise ValueError('请明确确认外发材料和本批费用上限。')
                return JSONResponse(workbench.start(task_id,args['run_id'],args['scope_sha256']))
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
