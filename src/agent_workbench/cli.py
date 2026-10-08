"""Local operator CLI: draft → review/confirm → independent A2A QA → report."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from .domain import CandidateRepository
from .jobs import JobStore


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def gateway(root):
    from .models import ModelGateway
    return ModelGateway(model='deepseek-flash', max_calls=8, max_input_chars=25000,
                        max_output_tokens=2048, audit_path=root / 'model-calls.jsonl')


async def verify(root, request_id, manifest_hash, goal, max_battles, url=None):
    from .protocol import local_verifier, delegate
    if url:
        result = await delegate(url, request_id, manifest_hash, goal, max_battles)
    else:
        from .game_tools import connect_tools
        from .verification.agent import VerificationAgent
        async with connect_tools(root) as tools:
            agent = VerificationAgent(root, gateway(root), tools)
            async with local_verifier(root, agent.run) as endpoint:
                result = await delegate(endpoint, request_id, manifest_hash, goal, max_battles)
    write(root / 'reports' / (request_id + '-' + result['task_id'] + '.json'), result)
    return result


async def serve(root, port):
    from .game_tools import connect_tools
    from .protocol import local_verifier
    from .verification.agent import VerificationAgent
    async with connect_tools(root) as tools:
        agent = VerificationAgent(root, gateway(root), tools)
        async with local_verifier(root, agent.run, port=port) as endpoint:
            print('本地 Verification 服务: ' + endpoint, flush=True)
            print('仅服务当前本机可信用户；Ctrl+C 停止。', flush=True)
            await asyncio.Event().wait()


def main(argv=None):
    for name in ('LANGSMITH_TRACING', 'LANGCHAIN_TRACING_V2', 'LANGCHAIN_TRACING', 'LANGCHAIN_HANDLER'):
        os.environ[name] = 'false'
    parser = argparse.ArgumentParser(description='策划配置与独立验证工作台 V1（本地 CLI）')
    parser.add_argument('--data', type=Path, default=Path('local-data/workbench'))
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('preview', 'draft'):
        sub = commands.add_parser(name)
        sub.add_argument('request')
        sub.add_argument('--parent')
    for name in ('candidate', 'confirm'):
        commands.add_parser(name).add_argument('manifest_hash')
    sub = commands.add_parser('verify')
    sub.add_argument('request_id')
    sub.add_argument('manifest_hash')
    sub.add_argument('goal')
    sub.add_argument('--max-battles', type=int, default=4)
    sub.add_argument('--url')
    commands.add_parser('show').add_argument('request_id')
    commands.add_parser('report').add_argument('request_id')
    commands.add_parser('explain').add_argument('request_id')
    commands.add_parser('coding-runs', help='读取已保存 Coding 运行；不调用模型')
    commands.add_parser('coding-show', help='读取已保存 Coding 结果；不调用模型').add_argument('operation_id')
    commands.add_parser('serve').add_argument('--port', type=int, default=8771)
    sub = commands.add_parser('web', help='本机 React 工作台；模型默认关闭')
    sub.add_argument('--port', type=int, default=8765)
    sub.add_argument('--call-cap', type=int, default=0)
    sub.add_argument('--audit-path', type=Path)
    sub.add_argument('--code-demo-root', type=Path, help='只读展示已关闭的 Python 代码修复演示；不授予模型调用')
    sub.add_argument('--qa-only', action='store_true', help='本次启动仅允许 Verification 消耗模型额度')
    args = parser.parse_args(argv)
    root = args.data.resolve()
    root.mkdir(parents=True, exist_ok=True)
    if args.command == 'web':
        from .workbench import serve as serve_workbench
        serve_workbench(root, port=args.port, call_cap=args.call_cap, audit_path=args.audit_path,
                        model_actions=('verify',) if args.qa_only else ('draft', 'verify'), code_demo_root=args.code_demo_root)
        return
    if args.command in ('coding-runs', 'coding-show'):
        from .coding.service import CodingService
        coding = CodingService(root)
        result = ({'runs': coding.list_runs()} if args.command == 'coding-runs'
                  else {'run': coding.get_run(args.operation_id)})
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    repo, store = CandidateRepository(root), JobStore(root)
    if args.command in ('preview', 'draft'):
        from .config import ConfigAgent
        config = ConfigAgent(repo, gateway(root))
        if args.command == 'preview':
            result = config.preview(args.request, args.parent)
            write(root / 'outbound-preview.json', result)
        else:
            result = config.draft(args.request, args.parent)
            write(root / 'latest-draft.json', result)
    elif args.command in ('candidate', 'confirm'):
        result = repo.get(args.manifest_hash)
        if args.command == 'confirm':
            store.confirm(args.manifest_hash)
            result = {'confirmed_manifest': args.manifest_hash, 'diff': result['diff'],
                      'message': '已确认此冻结候选；尚未验证，也未采纳到游戏基线。'}
    elif args.command == 'verify':
        result = asyncio.run(verify(root, args.request_id, args.manifest_hash, args.goal, args.max_battles, args.url))
    elif args.command == 'show':
        result = store.get(args.request_id)
    elif args.command == 'report':
        from .report_view import render_report
        report = store.get(args.request_id)['report']
        if report is None:
            raise ValueError('report is not available yet')
        print(render_report(report))
        return
    elif args.command == 'explain':
        from .explain import explain_report
        from .game_tools import connect_tools
        async def explain():
            async with connect_tools(root) as tools:
                return await explain_report(root, args.request_id, gateway(root), tools)
        saved = asyncio.run(explain())
        from .report_view import facts_for_report
        result = {'authoritative_facts': facts_for_report(store.get(args.request_id)['report']),
                  'unverified_model_draft_path': str(root / 'explanations' / (args.request_id + '.json')),
                  'draft_artifact_hash': saved['artifact_hash']}
    else:
        try:
            asyncio.run(serve(root, args.port))
        except KeyboardInterrupt:
            pass
        return
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
