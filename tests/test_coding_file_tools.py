"""Permission and lost-response recovery for the bounded Coding V1 editor."""
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from agent_workbench.coding.file_tools import FileTools, edit_handler


class CodingFileToolsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / 'workspace'
        self.path = self.workspace / 'configs/combat/v2/baseline.json'
        self.path.parent.mkdir(parents=True)
        self.path.write_text('{"multiplier":1.4}\n', encoding='utf-8')
        self.tools = FileTools(self.workspace, self.root / 'control')
        self.before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.args = {'path': 'configs/combat/v2/baseline.json', 'expected_sha256': self.before,
                     'old_text': '1.4', 'new_text': '1.58'}

    def test_edit_and_same_call_replay_do_not_write_twice(self):
        receipt = self.tools.replace_text('edit-1', **self.args)
        self.assertEqual(self.path.read_text(), '{"multiplier":1.58}\n')
        self.assertEqual(self.tools.replace_text('edit-1', **self.args), receipt)
        self.assertEqual(receipt['before_sha256'], self.before)
        with self.assertRaisesRegex(ValueError, 'different'):
            self.tools.replace_text('edit-1', **(self.args | {'new_text': '1.6'}))

    def test_child_including_fork_cannot_use_primary_dynamic_write(self):
        callback = edit_handler(self.tools, 'main-thread')
        response = callback('item/tool/call', {'threadId': 'child-thread', 'callId': 'x',
                                             'tool': 'edit_text', 'arguments': self.args})
        self.assertFalse(response['success'])
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), self.before)
        response = callback('item/tool/call', {'threadId': 'main-thread', 'callId': 'x',
                                             'tool': 'edit_text', 'arguments': self.args})
        self.assertTrue(response['success'])
        self.assertEqual(callback('item/commandExecution/requestApproval', {}), {'decision': 'decline'})

    def test_paths_and_stale_content_fail_closed(self):
        for path in ('../control/secrets', 'C:/Windows/win.ini', 'configs/combat/v2/other.json'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.tools.read_file(path)
        with self.assertRaises(ValueError):
            self.tools.replace_text('bad', **(self.args | {'expected_sha256': '0' * 64}))
        with self.assertRaises(ValueError):
            self.tools.replace_text('missing', **(self.args | {'old_text': 'not-here'}))

    def test_receipt_recovery_after_file_write_before_completion(self):
        def crash():
            raise RuntimeError('simulated crash')
        with self.assertRaisesRegex(RuntimeError, 'simulated crash'):
            self.tools.replace_text('recover', **self.args, _after_write=crash)
        self.assertEqual(self.path.read_text(), '{"multiplier":1.58}\n')
        restarted = FileTools(self.workspace, self.root / 'control')
        result = restarted.replace_text('recover', **self.args)
        self.assertEqual(result['after_sha256'], hashlib.sha256(self.path.read_bytes()).hexdigest())
        self.assertEqual(restarted.replace_text('recover', **self.args), result)

    def test_unknown_or_changed_disk_never_replays_over_new_changes(self):
        self.tools.replace_text('first', **self.args)
        self.path.write_text('{"multiplier":1.6}\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.tools.replace_text('first', **self.args)

    def test_hardlink_is_rejected(self):
        linked = self.root / 'linked.json'
        linked.hardlink_to(self.path)
        with self.assertRaises(ValueError):
            self.tools.read_file(self.args['path'])

    def test_hard_exit_before_replace_leaves_no_extra_workspace_file(self):
        script = '''import json, os, sys
from pathlib import Path
from agent_workbench.coding.file_tools import FileTools
workspace, control, args = json.loads(sys.argv[1])
os.replace = lambda *a, **kw: os._exit(73)
FileTools(Path(workspace), Path(control)).replace_text('hard-crash', **args)
'''
        process = subprocess.run([sys.executable, '-c', script, json.dumps(
            [str(self.workspace), str(self.root / 'control'), self.args])], timeout=15)
        self.assertEqual(process.returncode, 73)
        result = FileTools(self.workspace, self.root / 'control').replace_text('hard-crash', **self.args)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual([p for p in self.workspace.rglob('*') if p.is_file()], [self.path])


if __name__ == '__main__':
    unittest.main()
