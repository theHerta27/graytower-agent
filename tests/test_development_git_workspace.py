import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from agent_workbench.development.workspace import ProjectWorkspace


class GitFixture:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / '游戏 source'
        self.project.mkdir()
        self.git('init', '-q', '-b', 'main')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.git('config', 'user.name', 'Fixture')
        self.file = 'game-core/combat_core/v2/effects.py'
        self.other = 'game-core/combat_core/v2/state.py'
        self.original = 'def damage(x):\n    return x\n'
        for name, value in {self.file:self.original, self.other:'HP = 100\n',
                            'game-core/tests/v2/test_effects.py':'assert True\n',
                            '.env':'SECRET=never-materialize\n', 'README.md':'# Game\n'}.items():
            path = self.project/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(value.encode())
        self.git('add', '.')
        self.git('commit', '-qm', 'initial')
        self.base = self.git('rev-parse', 'HEAD').strip()

    def git(self, *args, cwd=None):
        path = cwd or self.project
        return subprocess.check_output(['git', '-c', 'safe.directory='+Path(path).as_posix(),
            '-c', 'core.autocrlf=false', '-C', str(path), *args], stderr=subprocess.PIPE).decode()

    def workspace(self, name='task'):
        return ProjectWorkspace.create(self.project, self.root/name)

    def change(self, workspace, text='def damage(x):\n    return max(0, x)\n'):
        before = workspace.read_file(self.file)
        workspace.write_file('fix', self.file, before['sha256'], text)


class GitWorkspaceTests(GitFixture, unittest.TestCase):
    def test_real_worktrees_keep_source_and_secret_untouched(self):
        first, second = self.workspace(), self.workspace('second')
        self.assertEqual(first.metadata.get('mode'), 'git_worktree')
        self.assertTrue((first.path/'.git').is_file())
        self.assertIn(first.path.as_posix(), self.git('worktree', 'list', '--porcelain'))
        self.assertNotEqual(first.metadata['task_branch'], second.metadata['task_branch'])
        self.change(first)
        self.assertEqual((self.project/self.file).read_text(), self.original)
        self.assertEqual(second.read_file(self.file)['text'], self.original)
        self.assertEqual(self.git('rev-parse', 'HEAD').strip(), self.base)
        self.assertFalse((first.path/'.env').exists())
        self.assertNotIn('.git', first.snapshot()['files'])
        self.assertFalse((first.control/'baseline.json').exists())

    def test_git_diff_add_delete_and_no_newline(self):
        work = self.workspace()
        self.assertEqual(work.metadata.get('mode'), 'git_worktree')
        self.change(work, 'VALUE = 2')
        work.write_file('new', 'game-core/combat_core/v2/new.py', None, 'NEW = 1')
        work.write_file('delete', self.other, work.read_file(self.other)['sha256'], None)
        view = work.inspect()
        self.assertIn('diff --git', view['patch'])
        self.assertIn('No newline at end of file', view['patch'])
        patch = self.root/'change.patch'
        patch.write_bytes(view['patch'].encode())
        self.git('apply', '--check', str(patch))
        commit = work.freeze()
        self.assertNotEqual(commit, self.base)
        self.assertEqual(self.git('rev-parse', 'HEAD', cwd=work.path).strip(), commit)
        self.assertEqual(ProjectWorkspace.open(work.control).inspect()['patch'], view['patch'])
        self.assertEqual(self.git('status', '--porcelain', cwd=work.path), '')

    def test_external_head_index_and_pointer_changes_rejected(self):
        work = self.workspace()
        self.assertEqual(work.metadata.get('mode'), 'git_worktree')
        self.change(work)
        self.git('add', self.file, cwd=work.path)
        with self.assertRaisesRegex(ValueError, 'index|暂存'):
            work.inspect()
        self.git('reset', '--mixed', 'HEAD', cwd=work.path)
        # This host protects .git from direct file writes; simulate its changed
        # read while retaining real Git for every other identity check.
        from unittest.mock import patch
        read = Path.read_text
        with patch.object(Path, 'read_text', lambda p, *a, **kw: 'gitdir: nowhere\n'
                          if p == work.path/'.git' else read(p,*a,**kw)):
            with self.assertRaises(ValueError): work.inspect()
        (work.path/'unknown.txt').write_text('keep this')
        with self.assertRaises(ValueError):
            work.inspect()

    def test_edit_replay_and_cross_process_lock(self):
        work = self.workspace()
        self.assertTrue(hasattr(work, 'mutation_lock'))
        before = work.read_file(self.file)
        def crash(): raise RuntimeError('lost response')
        with self.assertRaises(RuntimeError):
            work.write_file('edit', self.file, before['sha256'], 'X=2\n', _after_write=crash)
        reopened = ProjectWorkspace.open(work.control)
        self.assertEqual(reopened.write_file('edit', self.file, before['sha256'], 'X=2\n')['status'], 'completed')
        import os, sys
        code = "from pathlib import Path; from agent_workbench.development.git_support import FileLock; import sys\ntry:\n with FileLock(Path(sys.argv[1])): pass\nexcept ValueError: sys.exit(7)"
        with work.mutation_lock():
            run = subprocess.run([sys.executable, '-c', code, str(work.control/'mutation.lock')], env=os.environ.copy(), capture_output=True)
        self.assertEqual(run.returncode, 7, run.stderr)

    def test_old_snapshot_still_opens(self):
        self.assertIn('mode', __import__('inspect').signature(ProjectWorkspace.create).parameters)
        old = ProjectWorkspace.create(self.project, self.root/'old', mode='snapshot')
        self.assertEqual(old.metadata['schema'], 'development-project-v1')
        self.assertFalse((old.path/'.git').exists())
        self.assertEqual(ProjectWorkspace.open(old.control).read_file(self.file)['text'], self.original)

    def test_archive_preserves_evidence_and_rejects_unknown_files(self):
        work = self.workspace()
        self.assertTrue(hasattr(work,'archive'))
        self.change(work)
        extra = work.path/'keep.txt'; extra.write_text('manual note')
        with self.assertRaises(ValueError): work.archive()
        self.assertTrue(extra.exists())
        extra.unlink()
        patch = work.inspect()['patch']
        work.archive()
        self.assertFalse(work.path.exists())
        reopened = ProjectWorkspace.open(work.control)
        self.assertEqual(reopened.inspect()['patch'],patch)
        self.assertTrue(reopened.inspect()['archived'])
        with self.assertRaises(ValueError): self.change(reopened)

    def test_partial_creation_does_not_remove_unowned_path(self):
        self.assertTrue(hasattr(ProjectWorkspace,'cleanup_creation'))
        control = self.root/'failed'; control.mkdir()
        workspace = control/'workspace'; workspace.mkdir()
        (workspace/'keep.txt').write_text('mine')
        with self.assertRaises(ValueError): ProjectWorkspace.cleanup_creation(control)
        self.assertEqual((workspace/'keep.txt').read_text(),'mine')

    def test_freeze_recovers_after_git_ref_moves_before_metadata(self):
        work=self.workspace(); self.change(work)
        from unittest.mock import patch
        from agent_workbench.development.git_support import atomic_json
        def crash(path,value):
            if Path(path).name=='project.json':raise RuntimeError('metadata response lost')
            return atomic_json(path,value)
        with patch('agent_workbench.development.git_workspace.atomic_json',side_effect=crash):
            with self.assertRaises(RuntimeError):work.freeze()
        actual=self.git('rev-parse','HEAD',cwd=work.path).strip()
        reopened=ProjectWorkspace.open(work.control)
        self.assertEqual(reopened.metadata['candidate_commit'],actual)
        self.assertIn('max(0, x)',reopened.read_file(self.file)['text'])
        self.assertEqual(self.git('rev-parse','HEAD').strip(),self.base)

    def test_archive_recovers_after_worktree_removed_before_metadata(self):
        work=self.workspace(); self.change(work)
        from unittest.mock import patch
        from agent_workbench.development.git_support import atomic_json
        def crash(path,value):
            if Path(path).name=='project.json' and value.get('archived'):
                raise RuntimeError('archive metadata response lost')
            return atomic_json(path,value)
        with patch('agent_workbench.development.git_workspace.atomic_json',side_effect=crash):
            with self.assertRaises(RuntimeError):work.archive()
        self.assertFalse(work.path.exists())
        reopened=ProjectWorkspace.open(work.control)
        self.assertTrue(reopened.inspect()['archived'])
        self.assertIn('max(0, x)',reopened.read_file(self.file)['text'])
