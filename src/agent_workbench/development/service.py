"""Local development task: request → isolated candidate → optional model → evidence."""
import base64
import json
from pathlib import Path
import re
import time
from ..coding.responses_transport import CallBudget, responses_endpoint
from .workspace import ProjectWorkspace, digest, encoded
from .checks import CheckJobs
from .runtime import run_runtime, INSTRUCTIONS
from .tools import TOOL_SPECS
from .sandbox import IMAGE, runner_hash
from .adoption import Adoption


class DevelopmentTask:
    def __init__(self,control):
        self.workspace=ProjectWorkspace.open(control)
        self.root=self.workspace.control
        self.request=json.loads((self.root/'request.json').read_text(encoding='utf-8'))['request']
        if not isinstance(self.request,str) or not self.request.strip() or len(self.request)>8000:
            raise ValueError('invalid development request')
        self.jobs=CheckJobs(self.root/'checks')

    @classmethod
    def create(cls,project,control,request,ref='HEAD'):
        if not isinstance(request,str) or not request.strip() or len(request)>8000:raise ValueError('require a clear bounded request')
        workspace=ProjectWorkspace.create(project,control,ref)
        (workspace.control/'request.json').write_bytes(encoded({'request':request}))
        return cls(control)

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
        return {**view,'request':self.request,'adoption':adoption,
                'candidate_state':adoption['note'] if adoption else '原项目尚未改动',
                'validation':validation,'checks':checks}

    def _batch(self,run_id):
        if not isinstance(run_id,str) or not re.fullmatch('[a-zA-Z0-9_-]{1,80}',run_id):raise ValueError('invalid run id')
        return self.root/'runs'/run_id

    def prepare(self,run_id,grant):
        folder=self._batch(run_id)
        folder.mkdir(parents=True,exist_ok=False)
        tree=self.workspace.snapshot()
        preview={'request':self.request,'instructions':INSTRUCTIONS,'tools':TOOL_SPECS,
                 'files':[{'path':name,'text':base64.b64decode(v['content']).decode('utf-8')}
                          for name,v in tree['files'].items() if not name.endswith('.gz')]}
        scope={'schema':'development-outbound-v1','created_at_ns':time.time_ns(),'endpoint':'https://api.deepseek.com/responses','model':'deepseek-flash',
            'baseline_commit':self.workspace.metadata['baseline_commit'],'candidate_tree_hash':digest(tree),
            'request_hash':digest(self.request),'preview_hash':digest(preview),'capability_hash':digest({'instructions':INSTRUCTIONS,'tools':TOOL_SPECS}),
            'image':IMAGE,'runner_hash':runner_hash(),'grant':grant,
            'material':'需求、允许范围内源码/配置/可信回归文本、工具结果、候选Diff和Agent分析；不发送凭据、整个仓库或无关文件。',
            'actions':'只修改隔离候选，可运行受限回归/诊断；不修改原游戏、不运行Unity、不发布。'}
        # Validate and seal the budget without making any request.
        CallBudget(folder/'gateway',grant)
        scope['scope_sha256']=digest(scope)
        (folder/'outbound-preview.json').write_bytes(encoded(preview))
        (folder/'outbound-scope.json').write_bytes(encoded(scope))
        return scope

    def execute(self,run_id,authorized_scope_hash,runtime_python,tools_python,*,sender):
        folder=self._batch(run_id)
        scope=json.loads((folder/'outbound-scope.json').read_text(encoding='utf-8'))
        scope_hash=scope.pop('scope_sha256')
        preview=json.loads((folder/'outbound-preview.json').read_text(encoding='utf-8'))
        if (scope_hash!=authorized_scope_hash or digest(scope)!=scope_hash or digest(preview)!=scope['preview_hash']
            or digest(self.workspace.snapshot())!=scope['candidate_tree_hash'] or digest(self.request)!=scope['request_hash']
            or digest({'instructions':INSTRUCTIONS,'tools':TOOL_SPECS})!=scope['capability_hash']
            or IMAGE!=scope['image'] or runner_hash()!=scope['runner_hash']):
            raise ValueError('authorization scope or current candidate changed; prepare a new batch')
        try:(folder/'claimed').mkdir()
        except FileExistsError:raise ValueError('batch already started or closed; inspect saved receipts, do not automatically repeat') from None
        result={'state':'unknown','closed':True,'scope_sha256':scope_hash}
        try:
            with responses_endpoint(folder/'gateway',scope['grant'],sender) as (endpoint,budget):
                try:
                    result['runtime']=run_runtime(runtime_python=runtime_python,tools_python=tools_python,
                        workspace_control=self.root,control=folder/'runtime',endpoint=endpoint,prompt=self.request)
                    result['state']=result['runtime']['status']
                finally:result['budget']=budget.summary()
            return result
        except Exception as exc:
            result['error_type']=type(exc).__name__
            raise
        finally:(folder/'run-result.json').write_bytes(encoded(result))

    def export(self):
        view=self.summary();folder=self.root/'exports'/view['tree_hash']
        folder.mkdir(parents=True,exist_ok=True)
        (folder/'candidate.patch').write_bytes(view['patch'].encode('utf-8'))
        (folder/'candidate.json').write_bytes(encoded(view))
        return {'patch':str(folder/'candidate.patch'),'summary':str(folder/'candidate.json'),
                'note':'已导出候选供人工审阅；原项目未修改。'}
