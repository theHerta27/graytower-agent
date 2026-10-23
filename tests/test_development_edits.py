import unittest
import test_development_checks as fixtures


class ExactEditTests(unittest.TestCase):
    def setUp(self):
        fixtures.DevelopmentCheckTests.setUp(self)
        self.name='game-core/combat_core/v2/effects.py'
        self.assertTrue(hasattr(self.workspace,'replace_text'),'精确替换尚未实现')

    def test_replaces_only_one_fragment_and_same_id_replays(self):
        before=self.workspace.read_file(self.name)
        first=self.workspace.replace_text('replace1',self.name,before['sha256'],'VALUE = 1','VALUE = 2')
        self.assertEqual(self.workspace.read_file(self.name)['text'],'VALUE = 2\n')
        self.assertEqual(first,self.workspace.replace_text('replace1',self.name,before['sha256'],'VALUE = 1','VALUE = 2'))
        with self.assertRaises(ValueError):self.workspace.replace_text('replace1',self.name,before['sha256'],'VALUE = 1','VALUE = 3')

    def test_missing_duplicate_stale_and_readonly_are_rejected(self):
        before=self.workspace.read_file(self.name)
        for old in ('missing',''):
            with self.assertRaises(ValueError):self.workspace.replace_text('bad',self.name,before['sha256'],old,'x')
        with self.assertRaises(ValueError):self.workspace.replace_text('bad',self.name,'0'*64,'VALUE','OTHER')
        name='game-core/tests/v2/test_effects.py';item=self.workspace.read_file(name)
        with self.assertRaises(ValueError):self.workspace.replace_text('bad',name,item['sha256'],'assert True','assert False')
        self.workspace.write_file('duplicate',self.name,before['sha256'],'same\nsame\n')
        with self.assertRaises(ValueError):self.workspace.replace_text('bad',self.name,self.workspace.read_file(self.name)['sha256'],'same','new')

    def test_write_then_lost_reply_recovers_original_replacement(self):
        before=self.workspace.read_file(self.name)
        def crash():raise RuntimeError('lost reply')
        with self.assertRaises(RuntimeError):
            self.workspace.replace_text('recover',self.name,before['sha256'],'VALUE = 1','VALUE = 7',_after_write=crash)
        result=self.workspace.replace_text('recover',self.name,before['sha256'],'VALUE = 1','VALUE = 7')
        self.assertEqual(result['status'],'completed')
        self.assertEqual(self.workspace.read_file(self.name)['text'],'VALUE = 7\n')

    def test_replay_does_not_overwrite_later_edit(self):
        before=self.workspace.read_file(self.name)
        self.workspace.replace_text('one',self.name,before['sha256'],'VALUE = 1','VALUE = 2')
        self.workspace.write_file('two',self.name,self.workspace.read_file(self.name)['sha256'],'USER = 3\n')
        with self.assertRaises(ValueError):self.workspace.replace_text('one',self.name,before['sha256'],'VALUE = 1','VALUE = 2')
        self.assertEqual(self.workspace.read_file(self.name)['text'],'USER = 3\n')
