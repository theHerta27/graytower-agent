"""Code candidates freeze real files; candidate code is never imported on host."""
from pathlib import Path
import base64
import hashlib
import tempfile
import unittest

from agent_workbench.code_candidates import CodeWorkspace, prepare_shield_case


class CodeCandidateTests(unittest.TestCase):
    def test_real_worktree_patch_identity_and_out_of_scope_edit(self):
        with tempfile.TemporaryDirectory(dir='D:/Desktop') as tmp:
            root = Path(tmp)
            workspace = prepare_shield_case(root / 'control', root / 'workspace')
            self.addCleanup(workspace.remove)
            target = workspace.path / 'game-core/combat_core/v2/effects.py'
            before = target.read_text(encoding='utf-8')
            self.assertIn('hp_loss=min(u.hp,amount)', before)
            target.write_text(before.replace('hp_loss=min(u.hp,amount)', 'hp_loss=min(u.hp,left)'), encoding='utf-8', newline='')
            frozen = workspace.freeze('修复护盾吸收后仍扣生命的问题')
            inspected = workspace.inspect(frozen['candidate_id'])
            self.assertEqual(inspected['candidate_id'], frozen['candidate_id'])
            self.assertEqual(inspected['manifest']['changed_files'], ['game-core/combat_core/v2/effects.py'])
            reconstructed = workspace.restore(root / 'replay', frozen['candidate_id'])
            self.assertEqual((reconstructed / 'game-core/combat_core/v2/effects.py').read_bytes(), target.read_bytes())
            tree = workspace.artifacts.read_ref(frozen['manifest']['candidate_tree'], 'code-tree-v1')
            tree['files']['game-core/combat_core/v2/boss.py'] = {
                'sha256': hashlib.sha256(b'# unauthorized').hexdigest(),
                'content': base64.b64encode(b'# unauthorized').decode()}
            manifest = dict(frozen['manifest'])
            manifest['candidate_tree'] = workspace.artifacts.put(tree, 'code-tree-v1')
            foreign = workspace.artifacts.put(manifest, 'code-candidate-v1')
            with self.assertRaisesRegex(ValueError, 'scope'):
                workspace.inspect(foreign['sha256'])
            baseline = workspace.artifacts.read_ref(frozen['manifest']['baseline_tree'], 'code-tree-v1')
            baseline['files']['game-core/combat_core/v2/boss.py'] = tree['files']['game-core/combat_core/v2/boss.py']
            manifest['baseline_tree'] = workspace.artifacts.put(baseline, 'code-tree-v1')
            foreign = workspace.artifacts.put(manifest, 'code-candidate-v1')
            with self.assertRaisesRegex(ValueError, 'baseline'):
                workspace.inspect(foreign['sha256'])
            (workspace.path / 'game-core/combat_core/v2/boss.py').write_text('# unauthorized', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'scope'):
                workspace.freeze('超范围修改')

    def test_untracked_python_and_symlink_are_not_silently_omitted(self):
        with tempfile.TemporaryDirectory(dir='D:/Desktop') as tmp:
            root = Path(tmp)
            workspace = prepare_shield_case(root / 'control', root / 'workspace')
            self.addCleanup(workspace.remove)
            (workspace.path / 'extra.py').write_text('print(1)', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'scope'):
                workspace.freeze('新增文件')
