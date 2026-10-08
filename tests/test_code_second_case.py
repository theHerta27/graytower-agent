import tempfile
import unittest
from pathlib import Path
from agent_workbench.code_candidates import prepare_python_case
from agent_workbench.coding.runtime_adapter import instructions
from agent_workbench.code_sandbox import oracle_for

class SecondCaseTests(unittest.TestCase):
    def test_independent_skill_point_fault_has_its_own_baseline_and_oracle(self):
        with tempfile.TemporaryDirectory(dir='D:/Desktop') as directory:
            root=Path(directory)
            case=prepare_python_case(root/'control',root/'workspace','skill-points-python-v1')
            self.addCleanup(case.remove)
            text=(case.path/'game-core/combat_core/v2/effects.py').read_text(encoding='utf-8')
            self.assertIn('state.skill_points=min(4,before+gained-spent)',text)
            self.assertIn('hp_loss=min(u.hp,left)',text)
            self.assertEqual(case.preparation['profile'],'skill-points-python-v1')
            self.assertIn('技能点',instructions('skill-points-python-v1'))
            self.assertIn('test_skill_points',oracle_for('skill-points-python-v1'))
