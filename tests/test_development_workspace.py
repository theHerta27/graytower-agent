import hashlib
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

try:
    from agent_workbench.development.workspace import ProjectWorkspace
except ModuleNotFoundError:
    ProjectWorkspace = None


class ProjectWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(ProjectWorkspace, '真实项目工作区尚未实现')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / 'game'
        self.project.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.git('config', 'user.name', 'Fixture')
        self.files = {
            'game-core/combat_core/v2/effects.py': 'def damage(x):\n    return x\n',
            'game-core/combat_core/v2/state.py': 'HP = 100\n',
            'game-core/tests/v2/test_effects.py': 'def test_known_rule():\n    assert True\n',
            'configs/combat/v2/baseline.json': '{"hp":100}\n',
            '.env': 'DO_NOT_MATERIALIZE=fixture\n',
            'README.md': '# Game\n',
        }
        for name, content in self.files.items():
            file = self.project / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(content.encode('utf-8'))
        self.git('add', '.')
        self.git('commit', '-qm', 'initial')
        self.commit = self.git('rev-parse', 'HEAD').strip()
        self.control = self.root / 'task'

    def git(self, *args):
        return subprocess.check_output(['git', '-c', 'safe.directory='+self.project.as_posix(),
            '-c', 'core.autocrlf=false', '-C', str(self.project), *args], stderr=subprocess.PIPE).decode()

    def create(self):
        return ProjectWorkspace.create(self.project, self.control)

    def test_materializes_actual_commit_without_fault_injection_or_credentials(self):
        w = self.create()
        view = w.inspect()
        self.assertEqual(view['baseline_commit'], self.commit)
        self.assertEqual(view['changed_files'], [])
        self.assertFalse((w.path / '.env').exists())
        self.assertEqual(w.read_file('game-core/combat_core/v2/effects.py')['text'], self.files['game-core/combat_core/v2/effects.py'])
        self.assertEqual(self.git('status', '--porcelain'), '')

    def test_multiple_files_new_and_deleted_are_real_diffs_and_source_stays_unchanged(self):
        w = self.create()
        for name in ('effects.py', 'state.py'):
            path = 'game-core/combat_core/v2/' + name
            original = w.read_file(path)
            w.write_file('edit-'+name.replace('.', '-'), path, original['sha256'], original['text'] + '# reviewed\n')
        added = 'game-core/combat_core/v2/helper.py'
        w.write_file('new', added, None, 'VALUE = 1\n')
        view = w.inspect()
        self.assertEqual(len(view['changed_files']), 3)
        self.assertEqual(view['added_files'], [added])
        self.assertIn('helper.py', view['patch'])
        w.write_file('delete', added, w.read_file(added)['sha256'], None)
        self.assertNotIn(added, w.inspect()['changed_files'])
        self.assertEqual(self.git('status', '--porcelain'), '')

    def test_readonly_tests_scope_escape_and_unknown_files_are_rejected(self):
        w = self.create()
        for path in ('../outside.py', '/etc/passwd', 'C:/Windows/test.py', 'game-core/combat_core/../../secret.py',
                     'game-core/combat_core/v2/CON.py', 'game-core/combat_core/v2/case.py:stream'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                w.write_file('bad', path, None, 'pass\n')
        test = 'game-core/tests/v2/test_effects.py'
        with self.assertRaises(ValueError):
            w.write_file('test', test, w.read_file(test)['sha256'], 'pass\n')
        with self.assertRaises(ValueError):
            w.read_file('.env')

    def test_same_operation_reopens_and_stale_or_changed_input_cannot_overwrite(self):
        w = self.create()
        path = 'game-core/combat_core/v2/state.py'
        before = w.read_file(path)
        first = w.write_file('edit-once', path, before['sha256'], 'HP = 200\n')
        again = ProjectWorkspace.open(self.control)
        self.assertEqual(first, again.write_file('edit-once', path, before['sha256'], 'HP = 200\n'))
        with self.assertRaises(ValueError):
            again.write_file('edit-once', path, before['sha256'], 'HP = 300\n')
        with self.assertRaises(ValueError):
            again.write_file('stale', path, before['sha256'], 'HP = 300\n')

    def test_dirty_source_and_existing_control_are_not_silently_adopted(self):
        source = self.project / 'game-core/combat_core/v2/state.py'
        source.write_text('HP = 999\n', encoding='utf-8')
        with self.assertRaises(ValueError):
            self.create()
        self.assertEqual(source.read_text(encoding='utf-8'), 'HP = 999\n')

    def test_search_has_file_line_and_bounded_results(self):
        w = self.create()
        result = w.search('damage', limit=1)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['path'], 'game-core/combat_core/v2/effects.py')
        self.assertEqual(result[0]['line'], 1)

    def test_unrecorded_file_or_link_changes_fail_inspection(self):
        w = self.create()
        extra = w.path / 'secret.txt'
        extra.write_text('not allowed', encoding='utf-8')
        with self.assertRaises(ValueError):
            w.inspect()

    def test_prepared_edit_recovers_after_file_change_before_receipt(self):
        w = self.create()
        path = 'game-core/combat_core/v2/state.py'
        before = w.read_file(path)
        def crash():
            raise RuntimeError('lost acknowledgement')
        with self.assertRaises(RuntimeError):
            w.write_file('crash', path, before['sha256'], 'HP = 300\n', _after_write=crash)
        recovered = ProjectWorkspace.open(self.control).write_file('crash', path, before['sha256'], 'HP = 300\n')
        self.assertEqual(recovered['status'], 'completed')
        self.assertEqual(w.read_file(path)['text'], 'HP = 300\n')

    def test_tree_limit_rejects_before_writing_and_keeps_workspace_repairable(self):
        w = self.create()
        size = sum(len(__import__('base64').b64decode(v['content'])) for v in w.baseline['files'].values())
        name = 'game-core/combat_core/v2/state.py'
        before = w.read_file(name)
        with patch('agent_workbench.development.workspace.MAX_TREE', size + 1):
            with self.assertRaises(ValueError):
                w.write_file('over-tree', name, before['sha256'], before['text'] + '# too much\n')
        self.assertEqual(w.read_file(name), before)

    def test_regression_dependencies_are_materialized_but_readonly(self):
        names = ('scripts/accept_combat_v2.py', 'configs/combat/baseline.json')
        for name in names:
            target=self.project/name;target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(b'{}\n' if name.endswith('.json') else b'# acceptance helper\n')
        self.git('add','.');self.git('commit','-qm','regression dependencies')
        w=self.create()
        for name in names:
            before=w.read_file(name)
            with self.assertRaises(ValueError):w.write_file('bad-dependency',name,before['sha256'],'changed')


if __name__ == '__main__':
    unittest.main()
