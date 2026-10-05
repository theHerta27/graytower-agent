"""One known-case development regression, using the SAME authorized 16-call ledger.

Round 1 remains immutable. All six Config tasks run once; no cherry-picked retry,
no new QA/battles, no confirmation tasks, no automatic generation repair.
"""
import hashlib
import json
import time

from evaluate_config_development import DATA, ROOT, CASES, cases, model, load_local_credential
from agent_workbench.cli import write
from agent_workbench.config import ConfigAgent
from agent_workbench.domain import CandidateRepository
from agent_workbench.domain._shared import source_snapshot, TRUSTED_GAME_ROOT


def main():
    gateway = model()
    if gateway.remaining_calls() != 6:
        raise RuntimeError('expected exactly six remaining calls in the original authorized development ledger')
    scope = json.loads((DATA / 'outbound-scope.json').read_text(encoding='utf-8'))
    if scope['cases_sha256'] != hashlib.sha256(CASES.read_bytes()).hexdigest():
        raise RuntimeError('frozen cases changed')
    first = json.loads((DATA / 'observations.json').read_text(encoding='utf-8'))
    if list(first) != [c['id'] for c in cases()]:
        raise RuntimeError('all six original observations required')
    dest = DATA / 'round2'
    dest.mkdir(parents=True, exist_ok=True)
    with (dest / 'live-started.json').open('x', encoding='utf-8') as stream:
        json.dump({'kind': 'known-development-regression', 'case_ids': list(first),
                   'shared_ledger': str(DATA / 'model-calls.jsonl'), 'max_new_calls': 6,
                   'max_repairs_per_case': 0, 'new_battles': 0}, stream)
    source = ROOT / 'src/agent_workbench/config/workflow.py'
    write(dest / 'source-manifest.json', {'config_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
          'cases_sha256': scope['cases_sha256'],
          'change': 'Explicit status descriptions and distinction between clarifiable goal conflicts and unsupported scope.',
          'limit': 'Known development cases; cannot establish independent generalization or isolate prompt effect from run variance.'})
    (dest / 'config-workflow.py').write_bytes(source.read_bytes())
    baseline = source_snapshot(TRUSTED_GAME_ROOT)
    load_local_credential()
    observations = {}
    for case in cases():
        tick = time.monotonic()
        output = ConfigAgent(CandidateRepository(dest / case['id']), gateway, max_repairs=0).draft(case['prompt'])
        observations[case['id']] = {'output': output, 'audit': {
            'source': 'live', 'completed': not bool(output.get('error_type')),
            'baseline_unchanged': source_snapshot(TRUSTED_GAME_ROOT) == baseline,
            'battle_count': 0, 'candidate_created': output.get('candidate') is not None,
            'elapsed_seconds': time.monotonic() - tick,
            'known_development_regression': True, 'max_generation_repairs': 0}}
        write(dest / 'observations.json', observations)
        print(case['id'] + ': ' + output['status'], flush=True)
    write(dest / 'run-summary.json', {'cases': len(observations), 'remaining_calls': gateway.remaining_calls(),
                                     'new_battles': 0, 'independent_confirmation': False})


if __name__ == '__main__':
    main()
