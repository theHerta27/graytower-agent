"""TEST HELPER ONLY: hard exits around real durable operations, never a production switch."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from agent_workbench.game_tools import GameTools
from agent_workbench.jobs import JobStore, RecoveryRequired
from agent_workbench.qa import VerificationAgent


def append(path, value):
    with path.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(value, ensure_ascii=False) + '\n')
        stream.flush()
        os.fsync(stream.fileno())


class ScriptedModel:
    """No API client, model credential, network request or real LLM inference."""
    def __init__(self, root, phase):
        self.root, self.phase = root, phase

    def complete(self, messages, schema):
        if self.phase == 'receipt-crash':
            value = {'action': 'simulate', 'reason': '测试fixture：只观察seed7的一对真实战斗。',
                     'seeds': [7], 'policies': ['balanced']}
        else:
            value = {'action': 'finish', 'reason': '测试fixture：复用崩溃前收据；小样本保持不确定。'}
        append(self.root / 'fixture-decisions.jsonl', {'phase': self.phase, 'decision': value})
        return value


class ObservedRealTools:
    def __init__(self, root, phase):
        self.root, self.phase, self.game = root, phase, GameTools(root)
        real_verify = self.game.repo.verify

        def counted_verify(*args, **kwargs):
            append(root / 'physical-calls.jsonl', {'pid': os.getpid(), 'phase': phase, 'manifest_hash': args[0]})
            return real_verify(*args, **kwargs)

        self.game.repo.verify = counted_verify

    async def call(self, name, args):
        # Direct real GameTools owns the same JobStore and real game subprocess.
        # No long-lived MCP child can be orphaned by this test's forced OS exit.
        result = await asyncio.to_thread(getattr(self.game, name), **args)
        if name == 'run_simulation':
            append(self.root / 'received-receipts.jsonl', {'phase': self.phase, 'pid': os.getpid(),
                                                        'job_id': result['job_id'], 'units': result['units']})
            if self.phase == 'receipt-crash':
                # Durable Job receipt is already committed. The LangGraph tool
                # node has not returned, so its completed checkpoint cannot exist.
                os._exit(73)
        return result


def unknown(root, phase):
    store = JobStore(root)
    if phase == 'unknown-crash':
        def physical_fixture():
            append(root / 'unknown-attempts.jsonl', {'pid': os.getpid(), 'fixture': True})
            os._exit(74)
        store.run('unknown-fixture', {'seeds': [7]}, 2, physical_fixture)
        raise AssertionError('hard exit did not happen')
    blocked = []
    for seed in (7, 11):
        try:
            store.run('unknown-fixture', {'seeds': [seed]}, 2,
                      lambda: (_ for _ in ()).throw(AssertionError('unknown work must not execute')))
        except RecoveryRequired:
            blocked.append(seed)
    evidence = {'same_args_blocked': 7 in blocked, 'new_args_blocked': 11 in blocked,
                'physical_fixture_attempts': len((root / 'unknown-attempts.jsonl').read_text(encoding='utf-8').splitlines())}
    (root / 'unknown-result.json').write_text(json.dumps(evidence), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--phase', choices=('receipt-crash', 'receipt-resume', 'unknown-crash', 'unknown-resume'), required=True)
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    if args.phase.startswith('unknown-'):
        unknown(root, args.phase)
        return
    agent = VerificationAgent(root, ScriptedModel(root, args.phase), ObservedRealTools(root, args.phase))
    report = asyncio.run(agent.run('recovery-real'))
    (root / 'resumed-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
