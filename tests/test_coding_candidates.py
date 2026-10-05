"""Real trusted-domain imports with temporary workspaces; no model or battles."""
import base64
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from agent_workbench.domain import CandidateRepository
from agent_workbench.domain._shared import TRUSTED_GAME_ROOT


class CodingCandidateTests(unittest.TestCase):
    def setUp(self):
        from agent_workbench.coding.candidates import CodingWorkspace
        self.CodingWorkspace = CodingWorkspace
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = CandidateRepository(self.root / 'authority')
        self.workspace = CodingWorkspace.prepare(self.root / 'workspace', self.repo)
        self.file = self.workspace.root / 'configs/combat/v2/baseline.json'

    def edit(self, value=1.58, other=False):
        bundle = json.loads(self.file.read_text(encoding='utf-8'))
        bundle['skills']['breaker_skill']['multiplier'] = value
        if other:
            bundle['skills']['breaker_skill']['sp_cost'] = 0
        self.file.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    def test_import_freezes_full_bytes_diff_and_unverified_provenance(self):
        original = (TRUSTED_GAME_ROOT / 'configs/combat/v2/baseline.json').read_bytes()
        self.assertEqual(self.file.read_bytes(), original)
        self.edit()
        result = self.workspace.import_candidate('把隔离配置的战技倍率改为1.58',
                    provenance={'run_id': 'fixture-runtime', 'review_receipt': 'unverified-fixture-only'})
        self.assertEqual(result['manifest']['author'], 'coding')
        self.assertEqual(result['manifest']['kind'], 'numeric_config')
        self.assertEqual(result['diff'], [{'path': 'skills.breaker_skill.multiplier', 'before': 1.4, 'after': 1.58}])
        source = self.repo.read_artifact(result['manifest']['coding_source']['sha256'])
        self.assertEqual(source['review_status'], 'pending')
        self.assertEqual(source['provenance']['status'], 'declared_unverified')
        before = self.repo.read_artifact(source['before_file']['sha256'])
        after = self.repo.read_artifact(source['after_file']['sha256'])
        self.assertEqual(base64.b64decode(before['content_base64']), original)
        self.assertEqual(base64.b64decode(after['content_base64']), self.file.read_bytes())
        self.assertEqual(self.repo.get(result['manifest_hash']), result)
        self.assertEqual((TRUSTED_GAME_ROOT / 'configs/combat/v2/baseline.json').read_bytes(), original)

    def test_inspect_is_read_only_and_supports_unchanged_workspace(self):
        stored = set(self.repo.artifacts.root.iterdir())
        unchanged = self.workspace.inspect_changes()
        self.assertEqual(unchanged['diff'], [])
        self.assertEqual(unchanged['before_hash'], unchanged['after_hash'])
        self.edit()
        inspection = self.workspace.inspect_changes()
        self.assertEqual(inspection['diff'][0]['after'], 1.58)
        self.assertNotEqual(inspection['before_hash'], inspection['after_hash'])
        self.assertNotEqual(inspection['before_tree_hash'], inspection['after_tree_hash'])
        self.assertEqual(set(self.repo.artifacts.root.iterdir()), stored)

    def test_extra_file_script_or_directory_is_rejected(self):
        self.edit()
        for name in ('extra.json', 'run.py', 'extra-dir'):
            with self.subTest(name=name):
                path = self.workspace.root / name
                path.mkdir() if name.endswith('dir') else path.write_text('{}', encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'workspace'):
                    self.workspace.import_candidate('倍率1.58')
                path.rmdir() if path.is_dir() else path.unlink()

    def test_other_json_edit_type_coercion_and_unchanged_candidate_rejected(self):
        for value, other in ((1.58, True), ('1.58', False), (True, False), (1.4, False)):
            with self.subTest(value=value, other=other):
                self.file.write_bytes((TRUSTED_GAME_ROOT / 'configs/combat/v2/baseline.json').read_bytes())
                self.edit(value, other)
                with self.assertRaises(ValueError):
                    self.workspace.import_candidate('倍率1.58')

    def test_duplicate_json_key_is_rejected(self):
        self.edit()
        text = self.file.read_text(encoding='utf-8').replace('"multiplier": 1.58', '"multiplier": 1.4, "multiplier": 1.58')
        self.file.write_text(text, encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            self.workspace.import_candidate('倍率1.58')

    def test_hardlink_alias_is_rejected(self):
        self.edit()
        os.link(self.file, self.root / 'outside-alias.json')
        with self.assertRaisesRegex(ValueError, 'link'):
            self.workspace.import_candidate('倍率1.58')

    def test_symlink_is_rejected_without_reading_target(self):
        self.edit()
        target = self.root / 'outside.json'
        target.write_text('outside sentinel', encoding='utf-8')
        link = self.workspace.root / 'extra-link.json'
        try:
            os.symlink(target, link)
        except OSError as exc:
            self.skipTest('OS did not allow creating symlink fixture: ' + type(exc).__name__)
        with self.assertRaisesRegex(ValueError, 'link|reparse'):
            self.workspace.import_candidate('倍率1.58')
        self.assertEqual(target.read_text(encoding='utf-8'), 'outside sentinel')

    def test_direct_coding_create_without_import_source_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'coding.*source'):
            self.repo.create('倍率1.58', [{'path': 'skills.breaker_skill.multiplier', 'value': 1.58}], author='coding')
        with self.assertRaises(ValueError):
            self.repo.create('代码候选', [{'path': 'skills.breaker_skill.multiplier', 'value': 1.58}], author='code')

    def test_coding_source_tampering_cannot_change_candidate_or_discard_scope(self):
        self.edit()
        candidate = self.workspace.import_candidate('倍率1.58')
        source = self.repo.read_artifact(candidate['manifest']['coding_source']['sha256'])
        source['diff'][0]['after'] = 1.6
        ref = self.repo.artifacts.put(source, 'coding-source-v1')
        manifest = dict(candidate['manifest'], coding_source=ref)
        altered = self.repo.artifacts.put(manifest, 'candidate-manifest-v1')
        with self.assertRaisesRegex(ValueError, 'coding'):
            self.repo.get(altered['sha256'])

    def test_config_candidate_schema_and_existing_creation_api_are_unchanged(self):
        candidate = self.repo.create('倍率1.6', [{'path': 'skills.breaker_skill.multiplier', 'value': 1.6}])
        self.assertEqual(candidate['manifest']['author'], 'config')
        self.assertNotIn('coding_source', candidate['manifest'])
        self.assertEqual(self.repo.get(candidate['manifest_hash']), candidate)

    def test_reopen_import_is_idempotent_and_frozen_bytes_survive_later_edits(self):
        self.edit()
        first = self.workspace.import_candidate('倍率1.58', {'run_id': 'local-fixture'})
        reopened = self.CodingWorkspace(self.workspace.root, self.repo, self.workspace.preparation)
        self.assertEqual(reopened.import_candidate('倍率1.58', {'run_id': 'local-fixture'}), first)
        self.edit(1.6)
        self.assertEqual(self.repo.get(first['manifest_hash']), first)
        second = reopened.import_candidate('倍率1.60', {'run_id': 'local-fixture'})
        self.assertNotEqual(first['manifest_hash'], second['manifest_hash'])

    def test_rehashed_source_cannot_hide_extra_edit_tree_or_fake_review(self):
        from agent_workbench.domain._shared import coding_file, coding_tree, digest
        self.edit()
        candidate = self.workspace.import_candidate('倍率1.58')
        original = self.repo.read_artifact(candidate['manifest']['coding_source']['sha256'])
        for mutation in ('extra-field', 'extra-tree-entry', 'baseline', 'review', 'provenance'):
            with self.subTest(mutation=mutation):
                source = deepcopy(original)
                if mutation == 'extra-field':
                    bundle = json.loads(self.file.read_bytes())
                    bundle['skills']['breaker_skill']['sp_cost'] = 0
                    raw = json.dumps(bundle).encode('utf-8')
                    source['after_file'] = self.repo.artifacts.put(coding_file(raw), 'coding-file-v1')
                    source['after_snapshot'] = coding_tree(raw)
                    source['after_tree_hash'] = digest(source['after_snapshot'])
                elif mutation == 'extra-tree-entry':
                    source['after_snapshot']['script.py'] = {'type': 'file', 'sha256': hashlib.sha256(b'').hexdigest(), 'size': 0}
                    source['after_tree_hash'] = digest(source['after_snapshot'])
                elif mutation == 'baseline':
                    source['before_file'] = source['after_file']
                    source['before_snapshot'] = source['after_snapshot']
                    source['before_tree_hash'] = source['after_tree_hash']
                elif mutation == 'review':
                    source['review_status'] = 'passed'
                else:
                    source['provenance']['status'] = 'verified'
                manifest = dict(candidate['manifest'], coding_source=self.repo.artifacts.put(source, 'coding-source-v1'))
                altered = self.repo.artifacts.put(manifest, 'candidate-manifest-v1')
                with self.assertRaisesRegex(ValueError, 'coding'):
                    self.repo.get(altered['sha256'])

    def test_concurrent_edit_during_domain_freeze_is_not_delivered_as_current_tree(self):
        self.edit()
        create = self.repo.create

        def edit_after_freeze(*args, **kwargs):
            result = create(*args, **kwargs)
            self.edit(1.6)
            return result

        with patch.object(self.repo, 'create', side_effect=edit_after_freeze):
            with self.assertRaisesRegex(ValueError, 'workspace changed'):
                self.workspace.import_candidate('倍率1.58')


class CodingAdmissionTests(unittest.IsolatedAsyncioTestCase):
    """Real local A2A and SQLite; report callback is explicitly a zero-battle fixture."""
    async def asyncSetUp(self):
        from agent_workbench.coding.candidates import CodingWorkspace
        from agent_workbench.jobs import JobStore
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = CandidateRepository(self.root / 'authority')
        workspace = CodingWorkspace.prepare(self.root / 'workspace', self.repo)
        path = workspace.root / 'configs/combat/v2/baseline.json'
        data = json.loads(path.read_text(encoding='utf-8'))
        data['skills']['breaker_skill']['multiplier'] = 1.58
        path.write_text(json.dumps(data), encoding='utf-8')
        self.candidate = workspace.import_candidate('独立查看配置候选')
        self.store = JobStore(self.repo.data_dir)
        self.calls = []

    async def fixture_report(self, request_id):
        self.calls.append(request_id)
        return {'request_id': request_id, 'manifest_hash': self.candidate['manifest_hash'],
                'verdict': 'INCONCLUSIVE', 'summary': 'fixture callback only; no model or battle'}

    async def test_confirmed_coding_uses_same_a2a_contract_and_durable_receipt_fixture(self):
        from agent_workbench.protocol import delegate, local_verifier
        manifest = self.candidate['manifest_hash']
        self.store.confirm(manifest)
        async with local_verifier(self.repo.data_dir, self.fixture_report) as base:
            first = await delegate(base, 'coding-fixture', manifest, '查看证据边界', 4)
            replay = await delegate(base, 'coding-fixture', manifest, '查看证据边界', 4)
        self.assertEqual(first['report'], replay['report'])
        self.assertEqual(first['task_state'], 'TASK_STATE_COMPLETED')
        self.assertEqual(self.calls, ['coding-fixture'])
        self.assertEqual(self.store.get('coding-fixture')['charged_battles'], 0)

    async def test_coding_requires_confirmation_and_cannot_admit_code_build(self):
        from a2a.utils.errors import InvalidParamsError, UnsupportedOperationError
        from agent_workbench.protocol import delegate, local_verifier
        async with local_verifier(self.repo.data_dir, self.fixture_report) as base:
            with self.assertRaises(InvalidParamsError):
                await delegate(base, 'unconfirmed', self.candidate['manifest_hash'], '查看', 4)
            for kind in ('code', 'build'):
                manifest = dict(self.candidate['manifest'], kind=kind)
                ref = self.repo.artifacts.put(manifest, 'candidate-manifest-v1')
                self.store.confirm(ref['sha256'])
                with self.assertRaises(UnsupportedOperationError):
                    await delegate(base, kind, ref['sha256'], '查看', 4)
        self.assertEqual(self.calls, [])
        for request_id in ('unconfirmed', 'code', 'build'):
            with self.assertRaises(KeyError):
                self.store.get(request_id)

    async def test_coding_missing_source_cannot_claim_admission(self):
        from a2a.utils.errors import InvalidParamsError
        from agent_workbench.protocol import delegate, local_verifier
        manifest = dict(self.candidate['manifest'])
        del manifest['coding_source']
        ref = self.repo.artifacts.put(manifest, 'candidate-manifest-v1')
        self.store.confirm(ref['sha256'])
        async with local_verifier(self.repo.data_dir, self.fixture_report) as base:
            with self.assertRaises(InvalidParamsError):
                await delegate(base, 'missing-source', ref['sha256'], '查看', 4)
        self.assertEqual(self.calls, [])
        with self.assertRaises(KeyError):
            self.store.get('missing-source')


if __name__ == '__main__':
    unittest.main()
