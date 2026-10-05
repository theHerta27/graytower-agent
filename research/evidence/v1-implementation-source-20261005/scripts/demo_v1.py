"""Reproducible local business demo; --live is explicit, no model fixture fallback."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
for name in ('LANGSMITH_TRACING', 'LANGCHAIN_TRACING_V2', 'LANGCHAIN_TRACING', 'LANGCHAIN_HANDLER'):
    os.environ[name] = 'false'

from agent_workbench.cli import gateway, verify, write
from agent_workbench.config import ConfigAgent
from agent_workbench.domain import CandidateRepository
from agent_workbench.game_tools import GameTools
from agent_workbench.jobs import JobStore
from agent_workbench.qa import Decision, VerificationAgent


def prepare(root):
    spec = json.loads((ROOT / 'examples/config-to-qa.json').read_text(encoding='utf-8'))
    repo = CandidateRepository(root)
    model = gateway(root)
    config = ConfigAgent(repo, model)
    preview = config.preview(spec['request'])
    write(root / 'outbound-preview.json', preview)
    # Concrete read-only QA preview uses the same schema and rule-checked example.
    sample = repo.create(spec['request'], [{'path': 'skills.breaker_skill.multiplier', 'value': 1.7}])
    request = {'request_id': 'v1-live-demo', 'manifest_hash': sample['manifest_hash'],
               'goal': spec['goal'], 'max_battles': spec['max_battles'], 'status': 'new', 'charged_battles': 0, 'report': None}
    state = {'candidate': GameTools(root).inspect_candidate(sample['manifest_hash']), 'observations': [], 'errors': [], 'steps': 0}
    qa_preview = model.preview(VerificationAgent.preview(request, state), Decision)
    write(root / 'qa-outbound-preview.json', qa_preview)
    scope = {'endpoint': 'https://api.deepseek.com/chat/completions', 'model': 'deepseek-flash',
             'max_calls_including_failed_unknown': 8, 'max_input_chars_per_call': 25000,
             'max_output_tokens_per_call': 2048, 'new_batch_cost_cap_usd': 0.5,
             'conservative_bound_usd': 0.3,
             'pricing_basis': '2026-10-05 peak $0.30/M uncached input, $1.20/M output; bound each input char by 4 UTF-8 bytes/tokens plus protocol margin',
             'price_source': 'https://api-docs.deepseek.com/quick_start/pricing/',
             'data': ['the two exact preview payloads', 'generated config edit and deterministic validation feedback',
                      'paired battle metrics and up to 6000-character trace excerpts selected by QA', 'agent structured decisions'],
             'not_sent': ['repository code', 'whole repository', 'credentials in content', 'unrelated files'],
             'preview_config_sha256': hashlib.sha256((root / 'outbound-preview.json').read_bytes()).hexdigest(),
             'preview_qa_sha256': hashlib.sha256((root / 'qa-outbound-preview.json').read_bytes()).hexdigest(),
             'historical_evaluation_budget': 'Separate closed evaluation; not reset or reused by this batch.'}
    write(root / 'outbound-scope.json', scope)
    return spec


def load_local_credential():
    for line in Path('D:/Desktop/combat-foundation/.env').read_text(encoding='utf-8').splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            key, value = line.split('=', 1)
            if key.strip() == 'COMBAT_API_KEY':
                value = value.strip().strip('"').strip("'")
                if value and not value.startswith('your-'):
                    os.environ['DEEPSEEK_API_KEY'] = value
                    return
    raise RuntimeError('specified DeepSeek credential is unavailable')


async def live(root, spec):
    started = time.monotonic()
    draft = ConfigAgent(CandidateRepository(root), gateway(root)).draft(spec['request'])
    write(root / 'live-draft.json', draft)
    if draft.get('status') != 'candidate':
        raise RuntimeError('Config did not deliver a valid candidate; see live-draft.json')
    candidate = draft['candidate']
    # This is an explicitly authorized demo operator, not a claim of human UI approval.
    write(root / 'demo-confirmation.json', {'mode': 'explicit-demo-operator', 'manifest_hash': candidate['manifest_hash'], 'diff': candidate['diff']})
    JobStore(root).confirm(candidate['manifest_hash'])
    result = await verify(root, 'v1-live-demo', candidate['manifest_hash'], spec['goal'], spec['max_battles'])
    report = result['report']
    summary = {'draft_status': draft['status'], 'manifest_hash': candidate['manifest_hash'],
               'diff': candidate['diff'], 'task_id': result['task_id'], 'task_state': result['task_state'],
               'verdict': report['verdict'], 'structural_verdict': report['structural_verdict'],
               'charged_battles': report['charged_battles'], 'errors': report['errors'],
               'end_to_end_seconds': time.monotonic() - started}
    write(root / 'demo-result.json', summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--data', type=Path, default=ROOT / 'local-data/v1-demo')
    p.add_argument('--live', action='store_true')
    p.add_argument('--use-local-game-credential', action='store_true')
    args = p.parse_args()
    root = args.data.resolve()
    root.mkdir(parents=True, exist_ok=True)
    if args.live:
        # Preparation and authorization refer to saved payloads, not silent regenerated scope.
        if not (root / 'outbound-scope.json').exists():
            raise RuntimeError('prepare outbound scope before live run')
        if args.use_local_game_credential:
            load_local_credential()
        spec = json.loads((ROOT / 'examples/config-to-qa.json').read_text(encoding='utf-8'))
        asyncio.run(live(root, spec))
    else:
        prepare(root)
        print('Prepared zero-call outbound scope at ' + str(root / 'outbound-scope.json'))


if __name__ == '__main__':
    main()
