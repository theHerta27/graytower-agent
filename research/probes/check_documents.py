"""Check this research deliverable's local links, source line references and evidence."""
import json
import hashlib
from pathlib import Path
import re
import xml.etree.ElementTree as ET

root = Path(__file__).resolve().parents[2]
docs = (list(root.glob('*.md')) + list((root / 'research').glob('*.md'))
        + list((root / 'research/evidence').glob('*.md')))
docs += list((root / 'research/evidence/cooperation-protocol-20261004-175241').glob('*.md'))
errors = []
checked = 0
for doc in docs:
    content = doc.read_text(encoding='utf-8-sig')
    if content.count('```') % 2:
        errors.append(f'{doc.name}: unbalanced code fence')
    for raw in re.findall(r'\]\(([^)]+)\)', content):
        raw = raw.strip('<>')
        if raw.startswith(('http:', 'https:', '#', 'codex:')):
            continue
        loc = re.match(r'^(.*?):(\d+)$', raw)
        path_string = loc.group(1) if loc else raw.split('#', 1)[0]
        path = Path(path_string)
        if not path.is_absolute():
            path = doc.parent / path
        checked += 1
        if not path.exists():
            errors.append(f'{doc.name}: missing {raw}')
        elif loc and path.is_file():
            lines = len(path.read_text(encoding='utf-8-sig', errors='replace').splitlines())
            if int(loc.group(2)) > lines:
                errors.append(f'{doc.name}: out-of-range line {raw}')

game_xml = ET.parse(root / 'research/game-verification-evidence/pytest-results.xml').getroot()
suites = list(game_xml.iter('testsuite'))
game_counts = {name: sum(int(s.attrib.get(name, 0)) for s in suites)
               for name in ('tests', 'errors', 'failures', 'skipped')}
assert game_counts == {'tests': 181, 'errors': 0, 'failures': 0, 'skipped': 0}, game_counts
coding = (root / 'research/coding-pytest-20261003.log').read_text(encoding='utf-8-sig')
assert '206 passed, 13 skipped, 167 subtests passed' in coding
protocol = json.loads((root / 'research/evidence/codex-probe-20261003-231459/result.json').read_text())
assert protocol['result'] == 'PASS'
assert protocol['checks']['persisted_turn_statuses'] == ['completed', 'interrupted']
sdk = json.loads((root / 'research/evidence/codex-sdk-static-probe-result.json').read_text())
assert sdk['checks']['waiting_approval_blocks_notification_reader'] is True
framework = json.loads((root / 'research/evidence/langgraph-20261004-mtqwchsr/result.json').read_text())
assert framework['status'] == 'PASS'
assert framework['probe_sha256'] == hashlib.sha256((root / 'research/probes/langgraph_recovery_probe.py').read_bytes()).hexdigest()
assert framework['experiment']['budget_reserved'] == 12
assert framework['npc']['rewards'] == framework['npc']['outbox_count'] == 1
assert framework['interrupt']['entries_for_one_approval'] == 2
stats = json.loads((root / 'research/evidence/statistical-budget-20261004/results.json').read_text())
assert stats['numerical_checks']['passed'] is True
assert stats['zero_discordance_min_n'] == 272
assert stats['script_sha256'] == hashlib.sha256((root / 'research/probes/statistical_budget_probe.py').read_bytes()).hexdigest()
assert stats['av_primary_exact_binomial']['power_rows'][-1]['critical_success_count'] == 273
recovery = json.loads((root / 'research/evidence/verification-recovery-n7zc67l5/result.json').read_text(encoding='utf-8'))
assert recovery['death_code'] == 73 and recovery['new_process_resumes'] == 3
assert recovery['charged_battles'] == 4 and recovery['domain_row_unchanged']
assert recovery['unknown_case'] == {'death_code': 74, 'resume_rejected': True, 'charged_battles': 4, 'simulations_started': 0}
for path, expected_hash in recovery['sources'].items():
    assert hashlib.sha256((root / path).read_bytes()).hexdigest() == expected_hash, path
normal = json.loads((root / 'research/evidence/verification-slice-final-20261004/result.json').read_text(encoding='utf-8'))
assert normal['status'] == 'completed' and normal['charged_battles'] == 12
assert normal['report']['verdict'] == 'DESCRIPTIVE_ONLY'
live = json.loads((root / 'research/evidence/runtime-deepseek-20261004-152744/live-result.json').read_text(encoding='utf-8'))
assert live['pass'] and live['tool_roundtrip'] and live['review_turn'] == 'completed'
requests = live['budget']['requests']
assert len(requests) == 3 and all(r['model'] == 'deepseek-flash' and r['http_status'] == 200 for r in requests)
assert sum(r['usage']['input_tokens'] for r in requests) == 7513
assert sum(r['usage']['output_tokens'] for r in requests) == 159
bridge = json.loads((root / 'research/evidence/runtime-deepseek-20261004-154144/dynamic-mcp-result.json').read_text(encoding='utf-8'))
assert bridge['turn_status'] == 'completed' and bridge['mcp_owner_closed']
calibration = json.loads((root / 'research/evidence/game-semantics-calibration-20261004.json').read_text(encoding='utf-8'))
assert calibration['source_sha256_before'] == calibration['source_sha256_after']
assert calibration['probe_sha256'] == 'sha256:' + hashlib.sha256((root / 'research/probes/game_semantics_calibration.py').read_bytes()).hexdigest()
retrieval = json.loads((root / 'research/evidence/retrieval-structure-probe-20261004.json').read_text(encoding='utf-8'))
assert retrieval['summary']['shared_structured_corpus_lexical_alias']['all_evidence_cases'] == 3
assert retrieval['summary']['shared_structured_corpus_relations']['all_evidence_cases'] == 5
test_bytes = (root / 'research/evidence/verification-slice-tests-20261004.log').read_bytes()
test_text = test_bytes.decode('utf-16' if test_bytes.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig')
assert 'Ran 16 tests' in test_text and '\nOK' in test_text
cooperation = json.loads((root / 'research/evidence/cooperation-protocol-20261004-175241/result.json').read_text(encoding='utf-8'))
assert cooperation['pass'] and cooperation['turn_status'] == 'completed'
assert cooperation['request_count'] == 5 and cooperation['models'] == ['deepseek-flash']
assert all(cooperation['checks'].values())
assert cooperation['probe_sha256'] == hashlib.sha256((root / 'research/probes/cooperation_protocol_probe.py').read_bytes()).hexdigest()
confirmation_dir = root / 'research/evidence/collaboration-confirmation-final'
confirmation = json.loads((confirmation_dir / 'run-scores.json').read_text(encoding='utf-8'))
assert confirmation['summary']['assigned_runs'] == 28
assert confirmation['summary']['independent_tasks'] == 4
assert confirmation['summary']['pending_adjudication_runs'] == 0
assert confirmation['summary']['actually_started_runs'] == 28
assert confirmation['summary']['delivered_runs'] == 28
manifest_path = root / 'research/evidence/collaboration-confirmation-manifest-20261004-fixed-v1.json'
assert hashlib.sha256(manifest_path.read_bytes()).hexdigest() == '7171ca528582cb2a6ff4db17d7668e7f26454b75866a377eb67006f68ef1d005'
manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
native_audit = json.loads((root / 'research/evidence/collaboration-confirmation-native-audit-20261004.json').read_text(encoding='utf-8'))
assert {r['run_id'] for r in native_audit['runs']} == {r['run_id'] for r in manifest['assignments']}
assert all(r['all_applicable_native_checks_passed'] for r in native_audit['runs'])
for run in native_audit['runs']:
    raw_dir = root / 'research/evidence/collaboration-confirmation-20261004-fixed-v1' / run['run_id']
    for name, expected in run['artifact_sha256'].items():
        assert hashlib.sha256((raw_dir / name).read_bytes()).hexdigest() == expected, (run['run_id'], name)
test_record = json.loads((root / 'research/evidence/collaboration-tests-20261004.json').read_text(encoding='utf-8'))
assert sum(c.get('passed', 0) for c in test_record['checks']) == 54
for path, expected in test_record['source_sha256'].items():
    assert hashlib.sha256((root / path).read_bytes()).hexdigest() == expected, path
parts = sorted((root / 'research/evidence').glob('collaboration-confirmation-scoring-part*/review'))
assert len(parts) == 4
for part in parts:
    seal = json.loads((part / 'adjudication-seal.json').read_text(encoding='utf-8'))
    for name, key in [('adjudications.json', 'adjudications_sha256'), ('review-packet.json', 'packet_sha256'), ('adjudication-notes.json', 'notes_sha256')]:
        assert hashlib.sha256((part / name).read_bytes()).hexdigest() == seal[key], (part, name)
assert (confirmation_dir / 'runs.json').read_bytes() == (root / 'research/evidence/collaboration-confirmation-20261004-fixed-v1/runs.json').read_bytes()
frozen_dir = root / 'research/evidence/frozen-candidate-probe-20261005'
frozen_manifest = json.loads((frozen_dir / 'manifest.json').read_text(encoding='utf-8'))
for name, expected in frozen_manifest['files'].items():
    assert hashlib.sha256((frozen_dir / name).read_bytes()).hexdigest() == expected, name
for name, expected in frozen_manifest['probe_sources'].items():
    assert hashlib.sha256((root / 'research/probes' / name).read_bytes()).hexdigest() == expected, name
frozen_result = json.loads((frozen_dir / 'verification/result.json').read_text(encoding='utf-8'))
assert frozen_result['completed_battles'] == 4 and frozen_result['model_calls'] == 0
assert frozen_result['structural_verdict'] == 'PASS' and frozen_result['overall_verdict'] == 'INCONCLUSIVE'
assert frozen_result['frozen_artifact_hashes_unchanged'] and len(frozen_result['trace_refs']) == 4
protocol_dir = root / 'research/evidence/a2a-mcp-test-20261005-e8qqhg02'
protocol_seal = json.loads((protocol_dir / 'seal-final.json').read_text(encoding='utf-8'))
for name, expected in protocol_seal.items():
    assert hashlib.sha256((root / name).read_bytes()).hexdigest() == expected, name
protocol_boundary = json.loads((protocol_dir / 'result.json').read_text(encoding='utf-8'))
assert protocol_boundary['passed'] and not protocol_boundary['production_ready']
assert protocol_boundary['model_api_calls'] == 0 and len(protocol_boundary['checks']) == 37
assert all(protocol_boundary['checks'].values())
assert protocol_boundary['observed']['mcp_protocol_version'] == '2026-07-28'
assert protocol_boundary['observed']['dispatchers_before_terminal_replay'] == []
assert len(protocol_boundary['observed']['dispatchers_after_terminal_replay']) == 2
parent_validation = json.loads((root / 'research/evidence/architecture-validation-20261005.json').read_text(encoding='utf-8'))
parent_result_path = root / parent_validation['protocol_parent_run'] / 'result.json'
assert hashlib.sha256(parent_result_path.read_bytes()).hexdigest() == parent_validation['protocol_result_sha256']
assert parent_validation['protocol_lifecycle_ready'] is False and all(parent_validation['checks'].values())
summary = {'documents': len(docs), 'local_links_checked': checked,
           'game_junit': game_counts, 'coding_log_totals_verified': True,
           'protocol_and_sdk_evidence_verified': True,
           'framework_and_statistics_evidence_verified': True,
           'current_slice_sources_tests_and_evidence_verified': True,
           'deepseek_and_retrieval_calibration_evidence_verified': True,
           'native_cooperation_offline_evidence_verified': True,
           'real_collaboration_sources_native_traces_and_blind_seals_verified': True,
           'frozen_candidate_artifacts_and_probe_sources_verified': True,
           'a2a_mcp_functional_evidence_and_known_lifecycle_gap_verified': True,
           'independent_parent_boundary_validation_verified': True, 'errors': errors,
           'result': 'PASS' if not errors else 'FAIL'}
out = root / 'research/evidence/document-check.json'
out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(summary, ensure_ascii=False, indent=2))
raise SystemExit(bool(errors))
