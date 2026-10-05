"""Freeze this local V1 evidence without rewriting any historical evaluation."""
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from agent_workbench.jobs import JobStore, digest
from agent_workbench.report_view import facts_for_report


def main():
    root = ROOT / 'local-data/v1-demo'
    out = ROOT / 'research/evidence/v1-implementation-20261005.json'
    store = JobStore(root)
    request = store.get('v1-live-demo')
    events = [json.loads(l) for l in (root / 'model-calls.jsonl').read_text(encoding='utf-8').splitlines()]
    reserved = {r['call_id'] for r in events if r['status'] == 'reserved'}
    completed = {r['call_id']: r for r in events if r['status'] == 'completed'}
    assert reserved == set(completed) and len(reserved) == 6
    total_input = total_output = total_cached = 0
    for row in completed.values():
        usage = row['usage']
        total_input += usage['input_tokens']
        total_output += usage['output_tokens']
        total_cached += usage.get('input_token_details', {}).get('cache_read', 0)
    cost = ((total_input-total_cached)*.30 + total_cached*.006 + total_output*1.20)/1_000_000
    assert cost < .5
    test_log = ROOT / 'local-data/v1-final-tests.log'
    log = test_log.read_text(encoding='utf-8')
    matched = re.search(r'Ran (\d+) tests in ([\d.]+)s\s+OK \(skipped=(\d+)\)', log)
    assert matched, 'full suite did not pass'
    recovery_path = ROOT / 'local-data/recovery-demo/receipt-93e305f1eafc/recovery-result.json'
    recovery = json.loads(recovery_path.read_text(encoding='utf-8'))
    live_recovery = json.loads((root / 'recovery-result.json').read_text(encoding='utf-8'))
    assert live_recovery['original_report_hash'] == digest(request['report'])
    assert live_recovery['new_battles'] == recovery['additional_battles_after_resume'] == 0
    facts = facts_for_report(request['report'])
    assert [p['direction'] for p in facts['comparisons']] == ['行动值减少', '行动值减少']
    paths = [p for folder in (ROOT / 'src', ROOT / 'tests', ROOT / 'scripts') for p in folder.rglob('*.py')]
    paths += [ROOT / 'requirements-v1.lock.txt', ROOT / 'pyproject.toml', test_log]
    paths += [p for p in root.rglob('*') if p.is_file() and p.suffix not in ('.lock',)]
    paths += [p for p in recovery_path.parent.rglob('*') if p.is_file()]
    hashes = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    summary = {
        'stage': 'local V1 CLI implementation and retained-failure business demo; not full M3 acceptance',
        'candidate': request['manifest_hash'], 'report_hash': digest(request['report']),
        'real_model': {'model': 'deepseek-flash', 'calls': len(reserved), 'unknown_calls': 0,
                       'input_tokens': total_input, 'cached_input_tokens': total_cached, 'output_tokens': total_output,
                       'peak_price_estimate_usd': cost, 'authorized_cap_usd': .5,
                       'price_source': 'https://api-docs.deepseek.com/quick_start/pricing/'},
        'battles': {'live': 4, 'live_recovery_extra': 0, 'separate_hard_exit_test': 2,
                    'domain_unit_live_test': 4, 'known_this_implementation_total': 10},
        'tests': {'run': int(matched[1]), 'skipped': int(matched[3]), 'seconds': float(matched[2]),
                  'skips': 'opt-in domain 4-battle and hard-exit 2-battle tests; both separately executed'},
        'facts': facts,
        'incidents': [
            {'kind': 'tool delivery', 'detail': 'locals() included closure object in MCP log serialization after receipt commit',
             'fixed': True, 'original_error_count_preserved': 4,
             'regression': 'real MCP receipt/trace replay succeeded with zero new battles'},
            {'kind': 'model explanation quality', 'detail': 'seed 11 negative AV delta was described as longer, and directions as inconsistent',
             'model_quality_fixed': False, 'original_appendix_preserved': True,
             'mitigation': 'CLI report computes exact paired facts; model appendix is an unverified draft, not verdict or authoritative arithmetic'}],
        'recovery': recovery, 'a2a_duplicate': {'report_reused': True, 'new_qa_calls': 0},
        'limits': ['No paid clean end-to-end rerun after fixing the logging bug; initial failure remains in denominator.',
                   'No independent Config quality set, statistical population guarantee, React/Electron UI, Coding integration or Unity/NPC delivery.',
                   'Local single trusted operator, no distributed production features; no SDK fork.'],
        'sha256': hashes}
    if out.exists():
        raise RuntimeError('refusing to overwrite sealed V1 evidence')
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: summary[k] for k in ('real_model','tests','battles')}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
