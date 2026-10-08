import asyncio
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
spec=importlib.util.spec_from_file_location('close_trial',ROOT/'scripts/v1_close_demo.py')
trial=importlib.util.module_from_spec(spec);spec.loader.exec_module(trial)
from agent_workbench.coding.service import CodingService
from agent_workbench.workbench import APIError,VerificationInput
from agent_workbench.jobs import JobStore

class ScopeTests(unittest.TestCase):
    def test_wrong_qa_goal_rejected_before_admission_or_physical_jobs(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);coding=CodingService(root)
            cls=trial.scoped_workbench_class({'d01_candidate':'a'*64},coding)
            bench=cls(root,call_cap=0,audit_path=None,model_factory=None,model_actions=('verify',),coding_service=coding)
            candidate={'kind':'code','profile':'shield-damage-python-v1','manifest_hash':'a'*64}
            with patch.object(bench,'candidate',return_value=candidate):
                with self.assertRaises(APIError):
                    asyncio.run(bench.verify(VerificationInput(request_id='wrong',manifest_hash='a'*64,goal='比较配置的战斗表现',max_battles=2)))
            with self.assertRaises(KeyError):JobStore(root).get('wrong')
