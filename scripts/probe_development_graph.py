"""Offline-model business probe; real Git, LangGraph, Docker, edits and restore.

This is explicitly a scripted model, not a DeepSeek quality evaluation.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from langchain_core.messages import AIMessage,ToolMessage
from agent_workbench.development.service import DevelopmentTask
from agent_workbench.development.adoption import Adoption
from agent_workbench.development.workspace import encoded


class ScriptedModel:
    def __init__(self):self.saved={};self.limit=10
    def remaining_calls(self):return self.limit-len(self.saved)
    def summary(self):return {'reserved':0,'scripted_decisions':len(self.saved),'known_cost_usd':'0','max_calls':self.limit}
    def complete(self,messages,decision_id,final_only=False):
        if decision_id in self.saved:return self.saved[decision_id]
        number=int(decision_id.rsplit('-',1)[1])
        path='game-core/combat_core/v2/effects.py'
        if number==0:
            if '非法资源参数' not in str(messages[0].content):raise AssertionError('project memory not supplied')
            name,args='start_check',{'check_set':'resource_inputs'}
        elif number==1:name,args='read_file',{'path':path,'start_line':1,'max_lines':120}
        elif number==2:
            result=json.loads(next(m.content for m in reversed(messages) if isinstance(m,ToolMessage)))
            name,args='replace_text',{'path':path,'expected_sha256':result['sha256'],
                'old_text':'def skill_points(state,gained,spent,recorder,uid,reason):\n',
                'new_text':'def skill_points(state,gained,spent,recorder,uid,reason):\n    if gained < 0 or spent < 0: raise ValueError("negative skill points")\n'}
        elif number==3:name,args='start_check',{'check_set':'resource_inputs'}
        elif number==4:name,args='start_check',{'check_set':'rules'}
        elif number==5:name,args='propose_memory',{'kind':'lesson','content':'资源参数检查应在改变战技点和记录事件之前完成；本条来自脚本工程探针，待人工核实。'}
        else:
            result=AIMessage(content='脚本模型工程验收：候选已添加负数输入的前置检查。真实Docker结果及原项目影响以任务记录为准。')
            self.saved[decision_id]=result;return result
        result=AIMessage(content='',tool_calls=[{'name':name,'args':args,'id':'probe-'+str(number)}])
        self.saved[decision_id]=result;return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--data',type=Path,required=True)
    parser.add_argument('--resume',action='store_true')
    parser.add_argument('--project',type=Path,default=Path('D:/Desktop/graytower-game'))
    args=parser.parse_args();args.data=args.data.resolve()
    args.data.mkdir(parents=True,exist_ok=args.resume)
    clone=args.data/'game-clone'
    if not args.resume:
        subprocess.run(['git','clone','--quiet','--no-hardlinks',str(args.project),str(clone)],check=True)
        task=DevelopmentTask.create(clone,args.data/'task','修复非法资源参数在报错前改变状态的问题。')
        task.memory.add(task.workspace.metadata['project'],'非法资源参数必须在改变状态之前拒绝。',source='user:probe-fixture',version='*',status='confirmed')
    else:task=DevelopmentTask(args.data/'task')
    grant={'max_calls':10,'max_input_bytes':100000,'max_output_tokens':512,'cost_cap_usd':'0',
           'input_usd_per_million':'0','cached_input_usd_per_million':'0','output_usd_per_million':'0'}
    scope=task.prepare('scripted-engineering',grant) if not args.resume else json.loads((task._batch('scripted-engineering')/'outbound-scope.json').read_text(encoding='utf-8'))
    model=ScriptedModel()
    if args.resume:
        for job in task.jobs.list(task.workspace):
            if job['status']=='not_started':task.jobs.start(task.workspace,job['check_set'])
    result_path=task._batch('scripted-engineering')/'run-result.json'
    saved=json.loads(result_path.read_text(encoding='utf-8')) if args.resume and result_path.exists() else {}
    result=saved if saved.get('closed') and saved.get('state')=='completed' else task.execute('scripted-engineering',scope['scope_sha256'],model=model,resume=args.resume)
    # Long-running jobs pause without consuming model decisions. Explicitly
    # continue the same checkpoint; never launch another physical check here.
    import time
    deadline=time.monotonic()+240
    while result['state']=='waiting_checks' and time.monotonic()<deadline:
        unfinished=[j for j in task.jobs.list(task.workspace) if j['status']!='completed']
        if any(j['status'] not in ('running',) for j in unfinished):raise RuntimeError('check unavailable; inspect receipts')
        time.sleep(.5)
        result=task.execute('scripted-engineering',scope['scope_sha256'],model=model,resume=True)
    if result['state']!='completed':raise RuntimeError('probe did not complete')
    checks=task.jobs.list(task.workspace)
    by_set={}
    for check in checks:by_set.setdefault(check['check_set'],[]).append(check)
    assert by_set['resource_inputs'][0]['result']['verdict']=='FAIL'
    assert by_set['resource_inputs'][-1]['result']['verdict']=='PASS'
    assert by_set['rules'][-1]['result']['verdict']=='PASS'
    git=['git','-c','safe.directory='+clone.as_posix(),'-C',str(clone)]
    before=subprocess.check_output([*git,'status','--porcelain'])
    assert not before
    adoption=Adoption(task.workspace);applied=adoption.apply(task.workspace.inspect()['tree_hash'])
    assert applied['state']=='applied'
    restored=adoption.restore(applied['operation_id']);assert restored['state']=='restored'
    assert not subprocess.check_output([*git,'status','--porcelain'])
    memories=task.memory.list(task.workspace.metadata['project'])
    assert any(m['status']=='pending' and m['kind']=='lesson' for m in memories)
    output={'schema':'development-langgraph-engineering-probe-v1','model':'scripted-not-DeepSeek',
        'external_calls':0,'original_project_modified':False,'result':result,
        'checks':[{'set':j['check_set'],'verdict':j['result']['verdict'],'tests':len(j['result'].get('tests',[])),
                   'tree_hash':j['tree_hash'],'resources_removed':j['result'].get('resources_removed')} for j in checks],
        'clone_adoption_restored':True,'memory_proposal_pending':True}
    (args.data/'result.json').write_bytes(encoded(output))
    print(json.dumps(output,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
