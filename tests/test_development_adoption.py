import unittest
import test_development_checks as fixtures
try:
    from agent_workbench.development.adoption import Adoption
except ModuleNotFoundError:
    Adoption=None


class AdoptionTests(unittest.TestCase):
    def setUp(self):
        fixtures.DevelopmentCheckTests.setUp(self)
        self.assertIsNotNone(Adoption)
        self.name='game-core/combat_core/v2/effects.py'
        before=self.workspace.read_file(self.name)
        self.workspace.write_file('edit',self.name,before['sha256'],'VALUE = 2\n')
        self.adoption=Adoption(self.workspace,jobs=self.jobs)

    def approve(self,verdict='PASS'):
        job=self.jobs.start(self.workspace,'effects')
        self.jobs.complete(job['job_id'],{'exit_code':0 if verdict=='PASS' else 1,
            'tests':[{'name':'fixture-check','status':verdict}]})
        return self.workspace.inspect()['tree_hash']

    def test_apply_and_restore_real_files_without_git_commit(self):
        tree=self.approve();receipt=self.adoption.apply(tree)
        self.assertEqual((self.root/'source'/self.name).read_text(),'VALUE = 2\n')
        self.assertEqual(self.adoption.apply(tree),receipt)
        self.assertEqual(self.adoption.restore(receipt['operation_id'])['state'],'restored')
        self.assertEqual((self.root/'source'/self.name).read_text(),'VALUE = 1\n')

    def test_source_user_edit_and_stale_candidate_are_not_overwritten(self):
        tree=self.approve();source=self.root/'source'/self.name
        source.write_text('USER = 9\n')
        with self.assertRaises(ValueError):self.adoption.apply(tree)
        self.assertEqual(source.read_text(),'USER = 9\n')
        source.write_bytes(b'VALUE = 1\n')
        with self.assertRaises(ValueError):self.adoption.apply('0'*64)

    def test_missing_or_failed_checks_do_not_apply(self):
        tree=self.workspace.inspect()['tree_hash']
        with self.assertRaises(ValueError):self.adoption.apply(tree)
        self.approve('FAIL')
        with self.assertRaises(ValueError):self.adoption.apply(tree)

    def test_restore_rejects_later_user_changes(self):
        receipt=self.adoption.apply(self.approve())
        source=self.root/'source'/self.name;source.write_text('USER = 3\n')
        with self.assertRaises(ValueError):self.adoption.restore(receipt['operation_id'])
        self.assertEqual(source.read_text(),'USER = 3\n')

    def test_crash_after_write_recovers_original_operation(self):
        tree=self.approve()
        def crash():raise RuntimeError('lost reply')
        with self.assertRaises(RuntimeError):self.adoption.apply(tree,_after_write=crash)
        recovered=Adoption(self.workspace,jobs=self.jobs).apply(tree)
        self.assertEqual(recovered['state'],'applied')
        self.adoption.restore(recovered['operation_id'])
        self.assertEqual((self.root/'source'/self.name).read_text(),'VALUE = 1\n')

    def test_new_and_deleted_files_restore_exactly(self):
        self.workspace.write_file('delete',self.name,self.workspace.read_file(self.name)['sha256'],None)
        new='game-core/combat_core/v2/new.py';self.workspace.write_file('new',new,None,'NEW = 1')
        receipt=self.adoption.apply(self.approve())
        self.assertFalse((self.root/'source'/self.name).exists())
        self.assertEqual((self.root/'source'/new).read_bytes(),b'NEW = 1')
        self.adoption.restore(receipt['operation_id'])
        self.assertFalse((self.root/'source'/new).exists())
        self.assertEqual((self.root/'source'/self.name).read_bytes(),b'VALUE = 1\n')

if __name__=='__main__':unittest.main()
