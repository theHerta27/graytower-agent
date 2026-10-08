import json
from pathlib import Path
import tempfile
import unittest
from agent_workbench.domain import CandidateRepository
from agent_workbench.jobs import JobStore
from agent_workbench.releases import ReleaseService
from agent_workbench.local_game import LocalTestGame

class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.repo=CandidateRepository(self.root)
        self.candidate=self.repo.create('倍率1.6',[{'path':'skills.breaker_skill.multiplier','value':1.6}])['manifest_hash']
        jobs=JobStore(self.root);jobs.confirm(self.candidate);jobs.admit('qa',self.candidate,'检查',2)
        jobs.run('qa',{'fixture':True},2,lambda:{'structural_verdict':'PASS','overall_verdict':'INCONCLUSIVE'})
        jobs.complete('qa',{'request_id':'qa','manifest_hash':self.candidate,'verdict':'INCONCLUSIVE','structural_verdict':'PASS',
                           'jobs':jobs.receipts('qa'),'summary':'fixture'})
        self.service=ReleaseService(self.root,self.repo)

    def test_sample_limit_requires_explicit_ack_and_rollback_does_not_reapply_duplicate(self):
        with self.assertRaises(ValueError):self.service.adopt('adopt',self.candidate,'qa',accept_sample=False)
        adopted=self.service.adopt('adopt',self.candidate,'qa',accept_sample=True)
        self.assertEqual(adopted['kind'],'config')
        content=self.service.config_content()
        self.assertEqual(json.loads((content/'baseline.json').read_text())['skills']['breaker_skill']['multiplier'],1.6)
        rolled=self.service.rollback('rollback','config')
        self.assertEqual(rolled['active_release'],'baseline')
        self.assertEqual(self.service.adopt('adopt',self.candidate,'qa',accept_sample=True),adopted)
        self.assertEqual(self.service.status()['config']['active_release'],'baseline')

    def test_actual_trusted_game_new_version_and_old_save_survive_switch(self):
        game=LocalTestGame(self.service,game_root=Path('D:/Desktop/graytower-game/local-data/worktrees/local-test-content'))
        before=game.start('before')
        self.service.adopt('adopt',self.candidate,'qa',accept_sample=True)
        after=game.start('after')
        self.assertNotEqual(before['binding']['config_hash'],after['binding']['config_hash'])
        self.assertEqual(game.observe('before'),before)
        self.service.rollback('rollback','config')
        rollback=game.start('rollback')
        self.assertEqual(before['binding']['config_hash'],rollback['binding']['config_hash'])
        self.assertEqual(game.observe('after'),after)

    def test_returning_to_old_version_rolls_back_to_last_activation(self):
        jobs=JobStore(self.root)
        other=self.repo.create('倍率1.7',[{'path':'skills.breaker_skill.multiplier','value':1.7}])['manifest_hash']
        jobs.confirm(other);jobs.admit('qa_b',other,'检查',2)
        jobs.run('qa_b',{'fixture':True},2,lambda:{'structural_verdict':'PASS','overall_verdict':'INCONCLUSIVE'})
        jobs.complete('qa_b',{'request_id':'qa_b','manifest_hash':other,'verdict':'INCONCLUSIVE','structural_verdict':'PASS','jobs':jobs.receipts('qa_b')})
        a=self.service.adopt('a1',self.candidate,'qa',accept_sample=True)
        b=self.service.adopt('b1',other,'qa_b',accept_sample=True)
        self.service.adopt('a2',self.candidate,'qa',accept_sample=True)
        self.assertEqual(self.service.rollback('back1','config')['active_release'],b['active_release'])
        self.assertEqual(self.service.rollback('back2','config')['active_release'],a['active_release'])
        self.assertEqual(self.service.rollback('back3','config')['active_release'],'baseline')
