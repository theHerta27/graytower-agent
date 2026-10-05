"""Prepare an inspectable Coding→QA batch; run only with its explicit grant hash.

single/auto selects native Runtime capability at task start. A two-mode run is
functional acceptance, not a statistically meaningful collaboration comparison.
"""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import subprocess

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from agent_workbench.cli import write
from agent_workbench.coding.candidates import CodingWorkspace
from agent_workbench.coding.file_tools import EDIT_TOOL, FILE
from agent_workbench.coding.runtime_adapter import INSTRUCTIONS, model_catalog, run_runtime, validate_runtime_receipt
from agent_workbench.coding.responses_transport import responses_endpoint, deepseek_sender
from agent_workbench.domain import CandidateRepository
from agent_workbench.game_tools import GameTools, connect_tools
from agent_workbench.jobs import JobStore
from agent_workbench.models import ModelGateway
from agent_workbench.protocol import delegate, local_verifier
from agent_workbench.qa import Decision, VerificationAgent

PROMPT = '把击破手的战技倍率从 1.4 调到 1.58，保留战技点消耗、削韧和其他全部配置。请阅读实际文件，完成编辑和检查，说明改动依据与仍需验证的部分。'
GOAL = '独立核对击破手战技候选是否只改了倍率、是否保留1点战技点消耗与90点削韧；用balanced策略、种子7和11分别比较两版本（总预算4场），解释样本的胜负与通关行动值AV变化，有需要时查看必要Trace。小样本只做描述，不推断总体提升。'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_files():
    paths = list((ROOT / 'src/agent_workbench').rglob('*.py'))
    paths += [Path(__file__), ROOT / 'scripts/demo_v1.py']
    return {str(path.relative_to(ROOT)).replace('\\', '/'): sha(path) for path in sorted(paths)}


def runtime_identity():
    script = ('import json,hashlib,importlib.metadata,openai_codex.client; from pathlib import Path; '
              'from codex_cli_bin import bundled_codex_path; '
              'print(json.dumps({"sdk":importlib.metadata.version("openai-codex"),'
              '"runtime":importlib.metadata.version("openai-codex-cli-bin"),'
              '"binary_sha256":hashlib.sha256(bundled_codex_path().read_bytes()).hexdigest(),'
              '"client_sha256":hashlib.sha256(Path(openai_codex.client.__file__).read_bytes()).hexdigest()}))')
    return json.loads(subprocess.check_output([str(ROOT / 'research/.venv-coding/Scripts/python.exe'), '-I', '-c', script],
                                              text=True, encoding='utf-8', timeout=20))


def prepare(root: Path, mode: str):
    root.mkdir(parents=True, exist_ok=False)
    repo = CandidateRepository(root / 'data')
    modes = ['single', 'auto'] if mode == 'both' else [mode]
    workspaces = {}
    for name in modes:
        workspace = CodingWorkspace.prepare(root / ('workspace-' + name), repo)
        workspaces[name] = {'path': str(workspace.root), 'preparation': workspace.preparation,
                            'inspection': workspace.inspect_changes()}
    write(root / 'prepared.json', workspaces)
    description = repo.describe()
    # This explicit preview-only example never enters the actual batch workflow.
    sample = repo.create('QA外发预览示例；不是Runtime产物', [{'path': 'skills.breaker_skill.multiplier', 'value': 1.58}])
    preview_model = ModelGateway(max_calls=4, max_input_chars=32000, max_output_tokens=2048,
                                 audit_path=root / 'qa-model-calls.jsonl')
    preview_request = {'request_id': 'coding-runtime-qa-v1', 'manifest_hash': sample['manifest_hash'], 'goal': GOAL,
                       'max_battles': 4, 'status': 'new', 'charged_battles': 0, 'report': None}
    preview_state = {'candidate': GameTools(root / 'data').inspect_candidate(sample['manifest_hash']),
                     'observations': [], 'errors': [], 'steps': 0}
    write(root / 'qa-outbound-preview.json', preview_model.preview(VerificationAgent.preview(preview_request, preview_state, 4), Decision))
    write(root / 'coding-outbound-preview.json', {
        'description': 'Runtime assembles messages dynamically; these are the permitted business inputs, tools and instructions.',
        'prompt': PROMPT, 'instructions': INSTRUCTIONS, 'model_catalog': model_catalog(), 'edit_tool': EDIT_TOOL,
        'configuration_file': (repo.game_root / FILE).read_text(encoding='utf-8'), 'game_schema_and_rules': description,
        'dynamic_content': ['bounded file reads and diff/check results', 'native delegation messages and Agent analysis',
                            'native Review of these same file bytes', 'no repository source or arbitrary shell output']})
    scope = {'schema': 'coding-runtime-demo-grant-v1', 'modes': modes, 'prompt': PROMPT, 'qa_goal': GOAL,
             'qa_candidate_selection': modes[-1], 'qa_confirmation': 'explicit demo operator binds the actual frozen manifest; never applies it',
             'models': ['deepseek-flash'], 'endpoints': ['https://api.deepseek.com/responses',
                                                        'https://api.deepseek.com/chat/completions'],
             'max_total_calls': 28, 'cost_cap_usd': '0.85', 'max_new_battles': 4,
             'coding_grant': {'max_calls': 24, 'max_input_bytes': 70000, 'max_output_tokens': 2048,
                              'cost_cap_usd': '0.65', 'input_usd_per_million': '0.30',
                              'cached_input_usd_per_million': '0.006', 'output_usd_per_million': '1.20'},
             'qa_grant': {'max_calls': 4, 'max_input_chars': 32000, 'max_output_tokens': 2048, 'cost_cap_usd': '0.20'},
             'conservative_cost_bound_usd': '0.743616',
             'cost_bound_basis': 'Coding: input UTF8 bytes + 2048 token margin; QA: 4 tokens per character + 2048; peak prices, no cache discount; includes failed/unknown/child/review.',
             'pricing_source': 'https://api-docs.deepseek.com/quick_start/pricing/',
             'data': ['two prepared game configuration files (same baseline, separate task modes)',
                      'game Schema/rules, task request, candidate diff and deterministic checks',
                      'Runtime built-in instructions/tool schemas and necessary local path/hash metadata',
                      'Agent analysis/delegation/Review for this task only',
                      'QA decisions and at most 4 paired battles with bounded metrics/Trace excerpts'],
             'not_sent': ['whole repository', 'program source files', 'credentials as content',
                          'old evaluation packets/answers or unrelated files'],
             'limitations': ['functional integration acceptance, not collaboration quality comparison',
                             'numeric configuration only; code/build and Unity are not accepted',
                             'no adoption/publishing; QA overall remains evidence-dependent'],
             'prepared_sha256': sha(root / 'prepared.json'),
             'preview_hashes': {name: sha(root / name) for name in ('coding-outbound-preview.json', 'qa-outbound-preview.json')},
             'preview_candidate_manifest_hash': sample['manifest_hash'], 'runtime_identity': runtime_identity(),
             'source_hashes': source_files(),
             'old_grants': 'closed; no old ledger reused'}
    write(root / 'outbound-scope.json', scope)
    print(json.dumps({'scope': str(root / 'outbound-scope.json'), 'sha256': sha(root / 'outbound-scope.json'),
                      'external_calls': 0}, ensure_ascii=False))


async def qa(root, candidate, key):
    data = root / 'data'
    store = JobStore(data)
    store.confirm(candidate['manifest_hash'])
    write(root / 'demo-confirmation.json', {'mode': 'explicit-demo-operator', 'manifest_hash': candidate['manifest_hash'],
                                          'diff': candidate['diff'], 'applied': False})
    model = ModelGateway(api_key=key, model='deepseek-flash', max_calls=4, max_input_chars=32000,
                         max_output_tokens=2048, audit_path=root / 'qa-model-calls.jsonl')
    async with connect_tools(data) as tools:
        agent = VerificationAgent(data, model, tools)
        async with local_verifier(data, agent.run) as endpoint:
            result = await delegate(endpoint, 'coding-runtime-qa-v1', candidate['manifest_hash'], GOAL, 4)
            before = model.remaining_calls()
            repeated = await delegate(endpoint, 'coding-runtime-qa-v1', candidate['manifest_hash'], GOAL, 4)
            if result['report'] != repeated['report'] or model.remaining_calls() != before:
                raise RuntimeError('duplicate A2A delegation changed evidence or consumed model calls')
    write(root / 'qa-result.json', result)
    return result


def run(root: Path, authorization_sha256: str):
    scope_path = root / 'outbound-scope.json'
    if sha(scope_path) != authorization_sha256:
        raise ValueError('authorization must name the exact prepared scope hash')
    scope = json.loads(scope_path.read_text(encoding='utf-8'))
    if scope['source_hashes'] != source_files():
        raise ValueError('source changed after preparation; prepare a new reviewable scope')
    if sha(root / 'prepared.json') != scope['prepared_sha256'] or any(sha(root / name) != value for name, value in scope['preview_hashes'].items()):
        raise ValueError('prepared scope files changed')
    CandidateRepository(root / 'data').get(scope['preview_candidate_manifest_hash'])
    if runtime_identity() != scope['runtime_identity']:
        raise ValueError('pinned SDK/Runtime identity changed after preparation')
    with (root / 'execution-started.json').open('x', encoding='utf-8') as stream:
        json.dump({'scope_sha256': authorization_sha256}, stream)
    # Only after the frozen scope and one-shot guard have been checked.
    from demo_v1 import load_local_credential
    load_local_credential()
    key = os.environ.pop('DEEPSEEK_API_KEY')
    prepared = json.loads((root / 'prepared.json').read_text(encoding='utf-8'))
    repo = CandidateRepository(root / 'data')
    grant = scope['coding_grant'] | {'authorization_sha256': authorization_sha256}
    outcomes = {}
    started = time.monotonic()
    try:
        with responses_endpoint(root / 'coding-calls', grant, deepseek_sender(key)) as (endpoint, budget):
            for mode in scope['modes']:
                info = prepared[mode]
                workspace = CodingWorkspace(Path(info['path']), repo, info['preparation'])
                if workspace.inspect_changes() != info['inspection']:
                    raise ValueError('prepared workspace changed before the batch')
                begin = time.monotonic()
                result = run_runtime(runtime_python=ROOT / 'research/.venv-coding/Scripts/python.exe',
                                     tools_python=Path(sys.executable), workspace=workspace.root,
                                     data=root / 'data', control=root / ('control-' + mode), preparation=workspace.preparation,
                                     endpoint=endpoint, mode=mode, prompt=PROMPT, timeout_seconds=300)
                inspection = workspace.inspect_changes()
                validate_runtime_receipt(result, inspection)
                if inspection['diff'] != [
                        {'path': 'skills.breaker_skill.multiplier', 'before': 1.4, 'after': 1.58}]:
                    raise ValueError('Coding did not deliver the specified completed file change')
                receipt = repo.artifacts.put(result, 'coding-runtime-receipt-v1')
                candidate = workspace.import_candidate(PROMPT, {'source': 'DeepSeek through official Codex Runtime',
                                                               'mode': mode, 'runtime_receipt': receipt})
                frozen_source = repo.read_artifact(candidate['manifest']['coding_source']['sha256'])
                if frozen_source['after_tree_hash'] != result['review_tree_hash']:
                    raise ValueError('frozen candidate differs from the reviewed workspace')
                write(root / ('candidate-' + mode + '.json'), candidate)
                outcomes[mode] = {'manifest_hash': candidate['manifest_hash'], 'runtime_receipt': receipt,
                                  'actual_native_spawn_count': len(result['native_spawn_events']),
                                  'seconds': time.monotonic() - begin}
            write(root / 'coding-summary.json', {'runs': outcomes, 'budget': budget.summary()})
        selected = json.loads((root / ('candidate-' + scope['qa_candidate_selection'] + '.json')).read_text(encoding='utf-8'))
        qa_result = asyncio.run(qa(root, selected, key))
        write(root / 'batch-result.json', {'coding': outcomes, 'qa': qa_result, 'seconds': time.monotonic() - started,
                                         'claim': 'functional integration only; no collaboration quality uplift claim'})
    finally:
        from agent_workbench.coding.responses_transport import CallBudget
        summary = CallBudget(root / 'coding-calls', grant).summary()
        write(root / 'closed.json', {'unused_calls_closed': True, 'coding': summary,
                                    'reason': 'single authorized attempt ended; do not automatically replay'})
    print(json.dumps({'result': str(root / 'batch-result.json'), 'coding': outcomes}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--mode', choices=['single', 'auto', 'both'], default='both')
    parser.add_argument('--authorization-sha256')
    args = parser.parse_args()
    if args.authorization_sha256:
        run(args.data.resolve(), args.authorization_sha256)
    else:
        prepare(args.data.resolve(), args.mode)
