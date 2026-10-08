"""Actual frozen D-01 → common A2A → LangGraph → MCP → isolated tests.

No inference, no source edits, no application. Explicitly different from the
closed author's original tests and from a new model attempt.
"""
import argparse
import asyncio
import json
from pathlib import Path
import sqlite3
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from agent_workbench.code_demo_view import load_code_demo
from agent_workbench.code_candidates import CodeWorkspace
from agent_workbench.code_tools import CodeCatalog
from agent_workbench.game_tools import connect_tools
from agent_workbench.jobs import JobStore
from agent_workbench.protocol import delegate, local_verifier
from agent_workbench.verification.code_agent import CodeVerificationAgent
from agent_workbench.tasks import TaskStore, TaskInput


async def run(source, root, request_id):
    checked=load_code_demo(source)
    prep=json.loads((source/'data/control/preparation.json').read_text(encoding='utf-8'))
    catalog=CodeCatalog(root)
    candidate=catalog.register(CodeWorkspace(source/'data/control',source/'workspace',prep),checked['candidate_id'])
    store=JobStore(root);store.confirm(candidate)
    async with connect_tools(root,module='agent_workbench.code_tools') as tools:
        agent=CodeVerificationAgent(root,None,tools)
        async with local_verifier(root,agent.run) as endpoint:
            first=await delegate(endpoint,request_id,candidate,'复核护盾修复与游戏事件，限定4项检查。',2,kind='code',profile=prep['profile'])
            repeated=await delegate(endpoint,request_id,candidate,'复核护盾修复与游戏事件，限定4项检查。',2,kind='code',profile=prep['profile'])
    assert first['report']==repeated['report']
    with sqlite3.connect(root/'code-jobs.sqlite') as db:
        jobs=db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0]
    assert jobs==2,'Repeated delivery must not start another execution'
    tasks=TaskStore(root)
    tasks.create(TaskInput(task_id='shield_independent_qa',kind='verification',request='检查护盾修复：抵消伤害后不再错误扣血',candidate_id=candidate))
    tasks.link_history('shield_independent_qa',request_id)
    result={'schema':'code-qa-business-demo-v1','new_model_calls':0,'physical_test_runs':jobs,
            'tests_per_variant':4,'candidate_id':candidate,'a2a':first,'repeat_task_id':repeated['task_id'],
            'repeat_report_identical':True,'candidate_applied':False,
            'mode':'预设检查，无模型推理；真实MCP/A2A/LangGraph和容器执行'}
    (root.parent/'code-qa-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:result[k] for k in ['candidate_id','new_model_calls','physical_test_runs','repeat_report_identical']},ensure_ascii=False))
    print('结论:',first['report']['verdict'])

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True);parser.add_argument('--data',type=Path,required=True)
    parser.add_argument('--request-id',default='code_d01_qa_fixed')
    args=parser.parse_args();asyncio.run(run(args.source.resolve(),args.data.resolve(),args.request_id))
