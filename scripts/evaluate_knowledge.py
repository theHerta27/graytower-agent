"""在全新目录执行零模型费用的本地资料检索评测。"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from agent_workbench.development.knowledge_evaluation import evaluate_retrieval


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    result = evaluate_retrieval(args.project, args.output)
    print(json.dumps({'game_head': result['game_head'], 'model_calls': result['model_calls'],
        'cost_usd': result['cost_usd'], 'metrics': result['metrics'],
        'report': str(args.output.resolve()/'evaluation-report.md')}, ensure_ascii=False, indent=2))
    return result


if __name__ == '__main__':
    main()
