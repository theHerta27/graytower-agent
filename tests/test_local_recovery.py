"""OS-process crash checks. Fixture decisions are not real LLM acceptance."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid

from agent_workbench.domain import CandidateRepository
from agent_workbench.jobs import JobStore

HELPER = Path(__file__).with_name('recovery_driver.py')


def child(root, phase):
    env = {key: value for key, value in os.environ.items()
           if key.upper() in {'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'PATH'}}
    return subprocess.run([sys.executable, '-X', 'utf8', '-B', str(HELPER), '--root', str(root), '--phase', phase],
                          env=env, text=True, encoding='utf-8', capture_output=True, timeout=90)


class LocalRecoveryTests(unittest.TestCase):
    def test_hard_exit_before_receipt_stays_unknown_across_processes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = JobStore(root)
            store.confirm('a'*64)
            store.admit('unknown-fixture', 'a'*64, 'fixture only', 4)
            first = child(root, 'unknown-crash')
            self.assertEqual(first.returncode, 74, first.stderr)
            resumed = child(root, 'unknown-resume')
            self.assertEqual(resumed.returncode, 0, resumed.stderr)
            evidence = json.loads((root / 'unknown-result.json').read_text(encoding='utf-8'))
            self.assertTrue(evidence['same_args_blocked'])
            self.assertTrue(evidence['new_args_blocked'])
            self.assertEqual(evidence['physical_fixture_attempts'], 1)
            self.assertEqual(store.get('unknown-fixture')['charged_battles'], 2)

    @unittest.skipUnless(os.environ.get('RUN_REAL_RECOVERY_BATTLES') == '1', 'opt-in two real recovery battles')
    def test_real_receipt_survives_hard_exit_before_graph_checkpoint(self):
        root = Path(__file__).resolve().parents[1] / 'local-data/recovery-demo' / ('receipt-' + uuid.uuid4().hex[:12])
        repo = CandidateRepository(root)
        candidate = repo.create('恢复演示：战技倍率1.4到1.7，仅观察一对seed7。',
                                [{'path': 'skills.breaker_skill.multiplier', 'value': 1.7}])
        store = JobStore(root)
        store.confirm(candidate['manifest_hash'])
        store.admit('recovery-real', candidate['manifest_hash'], '单机硬退出后复用收据，不追加样本', 2)
        first = child(root, 'receipt-crash')
        self.assertEqual(first.returncode, 73, first.stderr)
        before = store.receipts('recovery-real')
        self.assertEqual(len(before), 1)
        self.assertIsNone(store.get('recovery-real')['report'])
        artifacts = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (root / 'artifacts').glob('*.json')}
        resumed = child(root, 'receipt-resume')
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        after = store.receipts('recovery-real')
        self.assertEqual(before, after)
        attempts = (root / 'physical-calls.jsonl').read_text(encoding='utf-8').splitlines()
        observed = [json.loads(line) for line in (root / 'received-receipts.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual(len(attempts), 1)
        self.assertEqual([row['phase'] for row in observed], ['receipt-crash', 'receipt-resume'])
        self.assertEqual(observed[0]['job_id'], observed[1]['job_id'])
        self.assertEqual(artifacts, {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (root / 'artifacts').glob('*.json')})
        self.assertEqual(store.get('recovery-real')['charged_battles'], 2)
        self.assertEqual(store.get('recovery-real')['report']['verdict'], 'INCONCLUSIVE')
        evidence = {'kind': 'real_process_receipt_before_checkpoint_recovery', 'model': 'scripted fixture, no LLM',
                    'request_id': 'recovery-real', 'manifest_hash': candidate['manifest_hash'],
                    'first_exit_code': first.returncode, 'resume_exit_code': resumed.returncode,
                    'physical_verify_calls': len(attempts), 'real_battles': 2, 'additional_battles_after_resume': 0,
                    'job_id': before[0]['job_id'], 'artifact_hashes_unchanged': True,
                    'final_verdict': 'INCONCLUSIVE', 'transport': 'direct real GameTools; MCP separately tested'}
        (root / 'recovery-result.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'recovery_evidence': str(root), **evidence}, ensure_ascii=False))


if __name__ == '__main__':
    unittest.main()
