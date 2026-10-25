"""Local development task: request → isolated candidate → optional model → evidence."""
import base64
import json
from pathlib import Path
import re
import time
from contextlib import contextmanager
import os
from ..coding.responses_transport import CallBudget
from .workspace import ProjectWorkspace, digest, encoded
from .checks import CheckJobs
from .agent import run_agent, agent_specs, INSTRUCTIONS
from .model import ToolModel
from .memory import ProjectMemory
from .tools import tool_specs
from .sandbox import IMAGE, runner_hash
from .adoption import Adoption


@contextmanager
def run_lock(folder):
    """Single local driver, including CLI/service processes; no distributed lease."""
    with (folder/'driver.lock').open('a+b') as stream:
        if stream.tell()==0:stream.write(b'0');stream.flush()
        stream.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            raise ValueError('this run already has a local driver') from None
        try:yield
        finally:
            stream.seek(0)
            if os.name=='nt':msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(stream.fileno(),fcntl.LOCK_UN)


class DevelopmentTask:
    def __init__(self,control,*,memory=None):
        self.workspace=ProjectWorkspace.open(control)
        self.root=self.workspace.control
        request=json.loads((self.root/'request.json').read_text(encoding='utf-8'))
        self.request=request['request'];self.tool_profile=request.get('tool_profile','standard')
        tool_specs(self.tool_profile)
        if not isinstance(self.request,str) or not self.request.strip() or len(self.request)>8000:
            raise ValueError('invalid development request')
        self.jobs=CheckJobs(self.root/'checks')
        self.memory=memory if memory is not None else ProjectMemory(self.root.parent/'project-memory.sqlite')

    @classmethod
    def create(cls,project,control,request,ref='HEAD',*,tool_profile='standard',memory=None):
        tool_specs(tool_profile)
        if not isinstance(request,str) or not request.strip() or len(request)>8000:raise ValueError('require a clear bounded request')
        workspace=ProjectWorkspace.create(project,control,ref)
        (workspace.control/'request.json').write_bytes(encoded({'request':request,'tool_profile':tool_profile}))
        return cls(control,memory=memory)

    def summary(self):
        view=self.workspace.inspect();checks=self.jobs.list(self.workspace)
        current=[j for j in checks if j['matches_current_candidate'] and j['matches_current_definition']
                 and j['status']=='completed' and j['check_set']!='diagnostic']
        if any(j['result']['verdict']=='FAIL' for j in current):validation='检查发现问题'
        elif any(j['check_set']=='rules' and j['result']['verdict']=='PASS' for j in current):validation='已通过完整规则回归'
        elif any(j['result']['verdict']=='PASS' for j in current):validation='指定检查已通过，尚未完成完整规则回归'
        elif current:validation='检查未形成确定结论'
        else:validation='尚未验证'
        adoption=Adoption(self.workspace).status()
        return {**view,'request':self.request,'tool_profile':self.tool_profile,'adoption':adoption,
                'candidate_state':adoption['note'] if adoption else '原项目尚未改动',
                'validation':validation,'checks':checks}

    def _batch(self,run_id):
        if not isinstance(run_id,str) or not re.fullmatch('[a-zA-Z0-9_-]{1,80}',run_id):raise ValueError('invalid run id')
        return self.root/'runs'/run_id

    def unfinished_runs(self):
        result=[]
        for prior in (self.root/'runs').glob('*') if (self.root/'runs').exists() else []:
            if not (prior/'claimed').exists() or not (prior/'outbound-scope.json').exists():continue
            old_scope=json.loads((prior/'outbound-scope.json').read_text(encoding='utf-8'))
            if old_scope.get('schema')!='development-langgraph-v1':continue
            saved=json.loads((prior/'run-result.json').read_text(encoding='utf-8')) if (prior/'run-result.json').exists() else {}
            if not saved.get('closed',False):result.append(prior.name)
        return result

    def prepare(self,run_id,grant):
        if (self.root/'discarded.json').exists():raise ValueError('这份候选已放弃，请创建新任务。')
        if self.unfinished_runs():raise ValueError('请先继续原任务；需要另一项工作时，请创建新的隔离候选。')
        # Validate before creating a preview folder; no provider request is made.
        selected=self.memory.retrieve(self.workspace.metadata['project'],self.request,self.workspace.metadata['baseline_commit'])
        folder=self._batch(run_id)
        folder.mkdir(parents=True,exist_ok=False)
        tree=self.workspace.snapshot()
        capability={'instructions':INSTRUCTIONS,'tools':agent_specs(self.tool_profile),'tool_profile':self.tool_profile}
        preview={'request':self.request,**capability,'memories':selected,
                 'files':[{'path':name,'text':base64.b64decode(v['content']).decode('utf-8')}
                          for name,v in tree['files'].items() if not name.endswith('.gz')]}
        scope={'schema':'development-langgraph-v1','engine':'langgraph','created_at_ns':time.time_ns(),'endpoint':'https://api.deepseek.com/chat/completions','model':'deepseek-flash',
            'baseline_commit':self.workspace.metadata['baseline_commit'],'candidate_tree_hash':digest(tree),
            'request_hash':digest(self.request),'preview_hash':digest(preview),'capability_hash':digest(capability),'tool_profile':self.tool_profile,
            'image':IMAGE,'runner_hash':runner_hash(),'grant':grant,
            'material':'需求、允许范围内源码/配置/可信回归文本、命中的项目记忆、工具结果、候选Diff、Agent分析及用户主动提交的澄清答复；不发送凭据、整个仓库或无关文件。',
            'actions':'只修改隔离候选，可运行受限回归/诊断；不修改原游戏、不运行Unity、不发布。'}
        # Validate and seal the budget without making any request.
        CallBudget(folder/'gateway',grant)
        scope['scope_sha256']=digest(scope)
        (folder/'outbound-preview.json').write_bytes(encoded(preview))
        (folder/'outbound-scope.json').write_bytes(encoded(scope))
        return scope

    def execute(self,run_id,authorized_scope_hash,runtime_python=None,tools_python=None,*,api_key='',model=None,resume=False,answer=None,sender=None):
        # runtime_python/tools_python remain positional compatibility only. The
        # new entry never launches the historical SDK/Responses worker.
        if (self.root/'discarded.json').exists():raise ValueError('这份候选已放弃，请创建新任务。')
        folder=self._batch(run_id)
        scope=json.loads((folder/'outbound-scope.json').read_text(encoding='utf-8'))
        scope_hash=scope.pop('scope_sha256')
        preview=json.loads((folder/'outbound-preview.json').read_text(encoding='utf-8'))
        if (scope.get('schema')!='development-langgraph-v1' or scope_hash!=authorized_scope_hash or digest(scope)!=scope_hash or digest(preview)!=scope['preview_hash']
            or (not resume and digest(self.workspace.snapshot())!=scope['candidate_tree_hash']) or digest(self.request)!=scope['request_hash']
            or digest({'instructions':INSTRUCTIONS,'tools':agent_specs(self.tool_profile),'tool_profile':self.tool_profile})!=scope['capability_hash']
            or IMAGE!=scope['image'] or runner_hash()!=scope['runner_hash']):
            raise ValueError('authorization scope or current candidate changed; prepare a new batch')
        if sender is not None:raise ValueError('legacy Responses sender cannot execute a LangGraph batch')
        if answer is not None and (not isinstance(answer,str) or not answer.strip() or len(answer)>8000):
            raise ValueError('require a bounded clarification answer')
        if not resume and preview['memories']!=self.memory.retrieve(self.workspace.metadata['project'],self.request,self.workspace.metadata['baseline_commit']):
            raise ValueError('authorization scope or current candidate changed; project memory changed')
        with run_lock(self.root):
            if any(prior!=run_id for prior in self.unfinished_runs()):
                raise ValueError('请先继续原任务；同一候选不能交给两个运行同时处理。')
            result_path=folder/'run-result.json'
            previous=json.loads(result_path.read_text(encoding='utf-8')) if result_path.exists() else None
            if resume:
                if not (folder/'claimed').exists() or (previous and previous.get('closed')):
                    raise ValueError('run has not started or is already closed')
                if previous and previous['state']=='waiting_user' and answer is None:
                    raise ValueError('please answer the pending question before resume')
            else:
                try:(folder/'claimed').mkdir()
                except FileExistsError:raise ValueError('batch already started or closed; inspect saved receipts, use explicit resume if interrupted') from None
            own_model=model is None
            model=model or ToolModel(folder/'model',scope['grant'],agent_specs(self.tool_profile),api_key=api_key)
            result={'state':'interrupted','closed':False,'scope_sha256':scope_hash,'engine':'langgraph'}
            try:
                result['agent']=run_agent(workspace=self.workspace,jobs=self.jobs,control=folder/'graph',model=model,
                    request=self.request,profile=self.tool_profile,memories=preview['memories'],resume=resume,answer=answer,memory=self.memory)
                result['state']=result['agent']['status']
                result['closed']=result['state'] not in ('waiting_user','waiting_checks','interrupted')
                return result
            except Exception as exc:
                result['error_type']=type(exc).__name__
                raise
            finally:
                result['budget']=model.summary()
                temporary=result_path.with_suffix('.tmp');temporary.write_bytes(encoded(result));temporary.replace(result_path)
                if own_model and hasattr(model,'close'):model.close()

    def export(self):
        view=self.summary();folder=self.root/'exports'/view['tree_hash']
        folder.mkdir(parents=True,exist_ok=True)
        (folder/'candidate.patch').write_bytes(view['patch'].encode('utf-8'))
        (folder/'candidate.json').write_bytes(encoded(view))
        return {'patch':str(folder/'candidate.patch'),'summary':str(folder/'candidate.json'),
                'note':'已导出候选供人工审阅；原项目未修改。'}
