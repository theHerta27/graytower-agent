import importlib.util
import unittest
from test_development_git_workspace import GitFixture


class GitDeliveryTests(GitFixture, unittest.TestCase):
    def delivery(self, workspace=None):
        self.assertIsNotNone(importlib.util.find_spec('agent_workbench.development.git_delivery'), 'Git delivery is missing')
        from agent_workbench.development.git_delivery import GitDelivery
        return GitDelivery(workspace or self.workspace(), launcher=lambda request: None)

    def pass_checks(self, delivery, preparation):
        job = delivery.check(preparation['preparation_id'])
        delivery.jobs(preparation['preparation_id']).complete(job['job_id'], {
            'exit_code':0,'tests':[{'name':'fixture-rule','status':'PASS'}]})
        return delivery.status()

    def target_commit(self, path, content):
        (self.project/path).write_text(content,encoding='utf-8')
        self.git('add',path); self.git('commit','-qm','developer change')
        return self.git('rev-parse','HEAD').strip()

    def test_merge_preserves_target_changes_and_requires_new_rules_receipt(self):
        delivery = self.delivery(); work = delivery.workspace
        self.change(work)
        tip = self.target_commit(self.other,'HP = 200\n')
        prep = delivery.prepare()
        self.assertEqual(prep['target_commit'],tip)
        self.assertFalse(prep['can_approve'])
        self.assertEqual((self.project/self.file).read_text(),self.original)
        with self.assertRaises(ValueError): delivery.approve(prep['preparation_id'],prep['approval_hash'])
        ready = self.pass_checks(delivery,prep)
        self.assertTrue(ready['can_approve'])
        applied = delivery.approve(ready['preparation_id'],ready['approval_hash'])
        self.assertEqual(applied['state'],'applied')
        self.assertEqual([j['result']['verdict'] for j in applied['checks']],['PASS'])
        self.assertEqual((self.project/self.other).read_text(),'HP = 200\n')
        self.assertIn('max(0, x)',(self.project/self.file).read_text())
        self.assertEqual(self.git('rev-parse','HEAD^1').strip(),tip)
        self.assertEqual(self.git('rev-parse','HEAD^2').strip(),prep['candidate_commit'])
        self.assertEqual(self.git('status','--porcelain'),'')

    def test_stale_approval_and_dirty_source_rejected(self):
        delivery = self.delivery(); self.change(delivery.workspace)
        ready = self.pass_checks(delivery,delivery.prepare())
        self.target_commit(self.other,'HP = 250\n')
        with self.assertRaises(ValueError): delivery.approve(ready['preparation_id'],ready['approval_hash'])
        self.assertEqual((self.project/self.file).read_text(),self.original)
        ready = self.pass_checks(delivery,delivery.prepare())
        (self.project/self.other).write_text('HP = 300\n')
        with self.assertRaises(ValueError): delivery.approve(ready['preparation_id'],ready['approval_hash'])
        self.assertEqual((self.project/self.other).read_text(),'HP = 300\n')

    def test_conflict_resolution_requires_staged_allowed_files(self):
        delivery = self.delivery(); self.change(delivery.workspace)
        self.target_commit(self.file,'def damage(x):\n    return x * 2\n')
        conflict = delivery.prepare()
        self.assertEqual(conflict['state'],'conflict')
        self.assertIn(self.file,conflict['conflicts'])
        from pathlib import Path
        folder = Path(conflict['worktree_path'])
        with self.assertRaises(ValueError): delivery.resolve(conflict['preparation_id'])
        (folder/self.file).write_text('def damage(x):\n    return max(0, x * 2)\n',encoding='utf-8')
        with self.assertRaises(ValueError): delivery.resolve(conflict['preparation_id'])
        self.git('add',self.file,cwd=folder)
        resolved = delivery.resolve(conflict['preparation_id'])
        ready = self.pass_checks(delivery,resolved)
        delivery.approve(ready['preparation_id'],ready['approval_hash'])
        self.assertIn('max(0, x * 2)',(self.project/self.file).read_text())

    def test_merge_lost_ack_reconciles_once(self):
        delivery = self.delivery(); self.change(delivery.workspace)
        ready = self.pass_checks(delivery,delivery.prepare())
        def crash(): raise RuntimeError('lost response after Git')
        with self.assertRaises(RuntimeError):
            delivery.approve(ready['preparation_id'],ready['approval_hash'],_after_merge=crash)
        merged = self.git('rev-parse','HEAD').strip()
        reopened = self.delivery(delivery.workspace)
        self.assertEqual(reopened.approve(ready['preparation_id'],ready['approval_hash'])['state'],'applied')
        self.assertEqual(self.git('rev-parse','HEAD').strip(),merged)

    def test_revert_adds_commit_and_rejects_later_changes(self):
        delivery = self.delivery(); self.change(delivery.workspace)
        ready = self.pass_checks(delivery,delivery.prepare())
        applied = delivery.approve(ready['preparation_id'],ready['approval_hash'])
        revert = delivery.prepare(kind='revert',operation_id=applied['preparation_id'])
        ready = self.pass_checks(delivery,revert)
        restored = delivery.approve(ready['preparation_id'],ready['approval_hash'])
        self.assertEqual(restored['state'],'restored')
        self.assertEqual((self.project/self.file).read_text(),self.original)
        self.assertEqual(self.git('rev-parse','HEAD^').strip(),applied['merge_commit'])
        self.assertNotEqual(self.git('rev-parse','HEAD').strip(),self.base)

    def test_pending_jobs_and_operations_block_cleanup(self):
        work = self.workspace()
        self.assertTrue(hasattr(work,'archive'))
        from agent_workbench.development.checks import CheckJobs
        jobs = CheckJobs(work.control/'checks',launcher=lambda request:None)
        job = jobs.start(work,'rules')
        with self.assertRaises(ValueError): work.archive()
        self.assertTrue(work.path.exists())
        jobs.complete(job['job_id'],{'exit_code':0,'tests':[{'name':'fixture','status':'PASS'}]})
        self.change(work)
        delivery = self.delivery(work)
        ready = self.pass_checks(delivery,delivery.prepare())
        delivery.approve(ready['preparation_id'],ready['approval_hash'])
        # A completed merge is not an unfinished operation. Cleanup must keep
        # the adopted fix and must not require reverting it first.
        work.archive()
        self.assertIn('max(0, x)',(self.project/self.file).read_text())

    def test_stale_conflict_can_be_discarded_with_saved_manual_edits(self):
        delivery=self.delivery();self.change(delivery.workspace)
        self.target_commit(self.file,'def damage(x):\n    return x * 2\n')
        conflict=delivery.prepare()
        from pathlib import Path
        path=Path(conflict['worktree_path'])
        manual='def damage(x):\n    return max(x * 2, 0)\n'
        (path/self.file).write_bytes(manual.encode())
        self.target_commit(self.other,'HP = 777\n')
        with self.assertRaises(ValueError):delivery.resolve(conflict['preparation_id'])
        status=delivery.status()
        self.assertIsNotNone(status.get('cleanup_hash'),'missing explicit discard flow')
        discarded=delivery.discard(conflict['preparation_id'],status['cleanup_hash'])
        self.assertEqual(discarded['state'],'abandoned')
        self.assertFalse(path.exists())
        import json,base64
        saved=json.loads((path.parent/'abandoned.json').read_text(encoding='utf-8'))
        self.assertEqual(base64.b64decode(saved['snapshot']['tree']['files'][self.file]['content']).decode(),manual)
        delivery.workspace.archive()
        self.assertEqual((self.project/self.other).read_text(),'HP = 777\n')
