"""Prepare/verify offline or explicitly run the current LangGraph baseline."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from agent_workbench.development.assessment import (
    prepare_assessment, verify_assessment, run_assessment, grade_assessment)


def _execution_key():
    # This function is called only by the explicit run action, after offline
    # scope verification. Never place the value in an artifact or print it.
    key = os.environ.get('DEEPSEEK_API_KEY', '')
    if not key and os.name == 'nt':
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment') as source:
                key = winreg.QueryValueEx(source, 'DEEPSEEK_API_KEY')[0]
        except FileNotFoundError:
            pass
    if not isinstance(key, str) or not key.strip():
        raise ValueError('DeepSeek execution credential is missing')
    return key


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'verify', 'run', 'grade'])
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--project', type=Path)
    parser.add_argument('--authorize-scope-sha256')
    args = parser.parse_args(argv)
    if args.action == 'prepare':
        if args.project is None: parser.error('prepare requires --project')
        value = prepare_assessment(args.project, args.data)
    elif args.action == 'grade':
        value = grade_assessment(args.data)
    else:
        if not args.authorize_scope_sha256:
            parser.error('verify/run require --authorize-scope-sha256 with the exact frozen scope')
        value = verify_assessment(args.data, args.authorize_scope_sha256)
        if args.action == 'run':
            value = run_assessment(args.data, args.authorize_scope_sha256, _execution_key())
    print(json.dumps(value, ensure_ascii=False, indent=2))
    return value


if __name__ == '__main__':
    main()
