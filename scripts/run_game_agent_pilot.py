"""Prepare, locally inspect, or explicitly run one frozen paid pilot."""
import argparse
import json
import os
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from agent_workbench.development.evaluation import prepare_pilot,verify_pilot,run_pilot,grade_pilot,grade_cell
from agent_workbench.development.service import DevelopmentTask


def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','run','grade','local-check'])
    parser.add_argument('--data',type=Path,required=True);parser.add_argument('--project',type=Path,default=Path('D:/Desktop/graytower-game'))
    parser.add_argument('--runtime-python',type=Path);parser.add_argument('--authorize-scope-sha256')
    args=parser.parse_args()
    if args.action=='prepare':value=prepare_pilot(args.project,args.data)
    elif args.action=='run':
        if not args.runtime_python or not args.authorize_scope_sha256:raise ValueError('require exact authorized scope and SDK interpreter')
        verify_pilot(args.data,args.authorize_scope_sha256)
        key=os.environ.get('DEEPSEEK_API_KEY','')
        if not key:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,'Environment') as source:key=winreg.QueryValueEx(source,'DEEPSEEK_API_KEY')[0]
        from agent_workbench.coding.responses_transport import deepseek_sender
        value=run_pilot(args.data,args.authorize_scope_sha256,args.runtime_python,sender=deepseek_sender(key))
    elif args.action=='grade':value=grade_pilot(args.data)
    else:
        args.data.mkdir(parents=True,exist_ok=False);results=[]
        from agent_workbench.development.evaluation import read,PUBLIC
        for case in read(PUBLIC):
            print('本地原游戏验收 '+case['id'],flush=True)
            task=DevelopmentTask.create(args.project,args.data/'tasks'/case['id'],case['request'])
            result=grade_cell(task,{'task_id':case['id']},args.data/'grading'/case['id'])
            results.append({'task_id':case['id'],**result})
        value={'schema':'game-agent-baseline-local-v1','model_calls':0,'results':results}
        (args.data/'results.json').write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(value,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
