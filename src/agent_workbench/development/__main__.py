"""Business CLI for real requests, without fixed demo cases."""
import argparse
import json
import os
from pathlib import Path
import sys
from .service import DevelopmentTask
from ..coding.responses_transport import deepseek_sender


def main():
    parser=argparse.ArgumentParser(description='灰塔研发助手：创建隔离候选、查看差异、按需检查。默认不改原项目、不调用模型。')
    commands=parser.add_subparsers(dest='action',required=True)
    create=commands.add_parser('create',help='从真实Git版本创建新需求')
    create.add_argument('--project',type=Path,required=True);create.add_argument('--task',type=Path,required=True)
    create.add_argument('--request',required=True);create.add_argument('--ref',default='HEAD')
    for name,help_text in [('status','查看候选与实际检查'),('check','开始受限可信回归'),('receipt','读取已有作业'),
                           ('prepare','准备模型材料和预算，不发起调用'),('run','按明确授权的批次调用模型'),('export','导出真实Diff供人工审阅')]:
        sub=commands.add_parser(name,help=help_text);sub.add_argument('--task',type=Path,required=True)
        if name=='check':sub.add_argument('--set',default='rules')
        if name=='receipt':sub.add_argument('--job',required=True)
        if name in ('prepare','run'):sub.add_argument('--run-id',required=True)
        if name=='prepare':sub.add_argument('--grant',type=Path,required=True)
        if name=='run':
            sub.add_argument('--authorize-scope-sha256',required=True)
            sub.add_argument('--runtime-python',type=Path,required=True)
    args=parser.parse_args()
    try:
        if args.action=='create':task=DevelopmentTask.create(args.project,args.task,args.request,args.ref);value=task.summary()
        else:
            task=DevelopmentTask(args.task)
            if args.action=='status':value=task.summary()
            elif args.action=='check':value=task.jobs.start(task.workspace,args.set)
            elif args.action=='receipt':value=task.jobs.read(args.job,task.workspace)
            elif args.action=='prepare':value=task.prepare(args.run_id,json.loads(args.grant.read_text(encoding='utf-8-sig')))
            elif args.action=='run':value=task.execute(args.run_id,args.authorize_scope_sha256,args.runtime_python,Path(sys.executable),
                sender=deepseek_sender(os.environ.get('DEEPSEEK_API_KEY','')))
            else:value=task.export()
        print(json.dumps(value,ensure_ascii=False,indent=2))
    except (ValueError,OSError,RuntimeError) as exc:
        print(json.dumps({'error':str(exc)},ensure_ascii=False),file=sys.stderr);return 1
    return 0


if __name__=='__main__':raise SystemExit(main())
