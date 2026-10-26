"""Prepare once; explicit authorization covers bounded stages and candidate revisions."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from agent_workbench.development.completion import prepare_campaign,verify_campaign,run_stage,close_campaign
from assess_development import _execution_key

def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['prepare','verify','run','close'])
    parser.add_argument('--data',type=Path,required=True)
    parser.add_argument('--project',type=Path,default=Path('D:/Desktop/graytower-game'))
    parser.add_argument('--scope-sha256')
    parser.add_argument('--stage',choices=['canary','development','revisions','rag'])
    args=parser.parse_args(argv)
    if args.action=='prepare':value=prepare_campaign(args.project,args.data)
    else:
        if not args.scope_sha256:parser.error('exact scope required')
        value=verify_campaign(args.data,args.scope_sha256)
        if args.action=='run':
            if not args.stage:parser.error('stage required')
            value=run_stage(args.data,args.scope_sha256,args.stage,_execution_key())
        elif args.action=='close':value=close_campaign(args.data,args.scope_sha256)
    print(json.dumps(value,ensure_ascii=False,indent=2))
    return value
if __name__=='__main__':main()
