"""Scripted decisions + real Git/LangGraph/Docker. No external model calls."""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from probe_development_graph import ScriptedModel
from agent_workbench.development.service import DevelopmentTask
from agent_workbench.development.git_support import git,oid
from agent_workbench.development.workspace import encoded
from agent_workbench.development.memory import ProjectMemory
from agent_workbench.development.knowledge import KnowledgeBase


def wait_delivery(task, preparation):
    identity=preparation['preparation_id']
    task.delivery.check(identity)
    deadline=time.monotonic()+180
    while time.monotonic()<deadline:
        status=task.delivery.status(identity)
        if status['can_approve']:return status
        if any(j['status'] not in ('running',) for j in status['checks']):
            raise RuntimeError('交付检查未通过，请查看真实回执：'+json.dumps(status['checks'],ensure_ascii=False))
        time.sleep(.5)
    raise RuntimeError('交付检查超时，保留记录，不自动重跑。')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--data',type=Path,required=True)
    parser.add_argument('--project',type=Path,default=Path('D:/Desktop/graytower-game'))
    args=parser.parse_args()
    args.data=args.data.resolve();args.project=args.project.resolve()
    args.data.mkdir(parents=True,exist_ok=False)
    before={'head':oid(args.project),'status':git(args.project,'status','--porcelain').decode()}
    clone=args.data/'game-clone'
    git(args.project,'-c','safe.directory='+(args.project/'.git').as_posix(),
        'clone','--quiet','--no-hardlinks',str(args.project),str(clone))
    workbench=args.data/'workbench';workbench.mkdir()
    task=DevelopmentTask.create(clone,workbench/'tasks'/'scripted-game','修复非法资源参数在报错前改变状态的问题。',
        memory=ProjectMemory(workbench/'project-memory.sqlite'),knowledge=KnowledgeBase(workbench/'project-knowledge.sqlite'))
    task.memory.add(str(clone),'非法资源参数必须在改变状态之前拒绝。',source='user:probe-fixture',version='*',status='confirmed')
    grant={'max_calls':10,'max_input_bytes':100000,'max_output_tokens':512,'cost_cap_usd':'0',
           'input_usd_per_million':'0','cached_input_usd_per_million':'0','output_usd_per_million':'0'}
    scope=task.prepare('scripted-engineering',grant)
    model=ScriptedModel()
    result=task.execute('scripted-engineering',scope['scope_sha256'],model=model)
    deadline=time.monotonic()+240
    while result['state']=='waiting_checks' and time.monotonic()<deadline:
        pending=[j for j in task.jobs.list(task.workspace) if j['status']!='completed']
        if any(j['status']!='running' for j in pending):raise RuntimeError('候选检查未启动或结果未知，保留记录。')
        time.sleep(.5)
        result=task.execute('scripted-engineering',scope['scope_sha256'],model=model,resume=True)
    if result['state']!='completed':raise RuntimeError('脚本图未完成：'+json.dumps(result,ensure_ascii=False))
    checks=task.jobs.list(task.workspace)
    resource=[j for j in checks if j['check_set']=='resource_inputs']
    assert [j['result']['verdict'] for j in resource]==['FAIL','PASS']
    assert any(j['check_set']=='rules' and j['result']['verdict']=='PASS' for j in checks)
    prepared=task.delivery.prepare()
    ready=wait_delivery(task,prepared)
    applied=task.delivery.approve(ready['preparation_id'],ready['approval_hash'])
    assert oid(clone)==applied['merge_commit']
    revert=wait_delivery(task,task.delivery.prepare('revert',applied['preparation_id']))
    restored=task.delivery.approve(revert['preparation_id'],revert['approval_hash'])
    assert restored['state']=='restored'
    assert not git(clone,'diff',before['head'],'HEAD','--')
    assert before=={'head':oid(args.project),'status':git(args.project,'status','--porcelain').decode()}
    output={'schema':'git-worktree-engineering-v1','model':'scripted-not-DeepSeek','external_calls':0,
        'original_unchanged':True,'source_commit':before['head'],'candidate_commit':prepared['candidate_commit'],
        'merge_commit':applied['merge_commit'],'revert_commit':restored['merge_commit'],
        'candidate_checks':checks,'merge_checks':ready['checks'],'revert_checks':revert['checks'],
        'scope_sha256':scope['scope_sha256'],'agent':result}
    (args.data/'result.json').write_bytes(encoded(output))
    print(json.dumps({k:v for k,v in output.items() if k not in ('candidate_checks','merge_checks','revert_checks','agent')},ensure_ascii=False,indent=2))
    for group in ('candidate_checks','merge_checks','revert_checks'):
        print(group,[(j['check_set'],j['result']['verdict'],len(j['result']['tests'])) for j in output[group]])


if __name__=='__main__':main()
