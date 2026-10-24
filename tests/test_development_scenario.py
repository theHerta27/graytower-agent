import json
import unittest
try:
    from agent_workbench.development.scenario import scenario_script
    from agent_workbench.development.tools import tool_specs
except ImportError:
    scenario_script=tool_specs=None


class ScenarioToolsTests(unittest.TestCase):
    def setUp(self):self.assertIsNotNone(scenario_script,'结构化规则观察尚未实现')

    def test_profile_adds_only_scenario_and_standard_remains_capable(self):
        standard={t['name'] for t in tool_specs('standard')};game={t['name'] for t in tool_specs('game')}
        self.assertEqual(game-standard,{'run_scenario'})
        self.assertTrue({'replace_text','start_diagnostic','start_check'}<=standard)
        with self.assertRaises(ValueError):tool_specs('anything')

    def test_script_embeds_bounded_json_data_not_python_interpolation(self):
        script=scenario_script(json.dumps({'actions':[{'kind':'resource','gained':-1,'spent':0}]}))
        compile(script,'scenario','exec')
        self.assertIn('OBSERVATION',script)
        for bad in ["__import__('os').system('x')",{'actions':[{'kind':'shell','command':'x'}]},
                    {'actions':[{'kind':'resource','gained':True,'spent':0}]},
                    {'actions':[{'kind':'resource','gained':0,'spent':0}]*9},
                    {'actions':[],'path':'C:/key'},
                    {'shields':[{'target_id':'../bad','value':10,'duration':1}],'actions':[]}]:
            with self.assertRaises(ValueError):scenario_script(bad if isinstance(bad,str) else json.dumps(bad))

    def test_no_hidden_expectation_or_verdict_in_scenario_program(self):
        script=scenario_script('{"initial_skill_points":3,"actions":[]}')
        self.assertNotIn('pytest',script)
        self.assertNotIn('PASS',script)
        self.assertIn('state_before',script)
        self.assertIn('state_after',script)
        self.assertIn('events',script)

    def test_runtime_capability_and_service_scope_bind_profile(self):
        import tempfile
        from pathlib import Path
        from agent_workbench.development.runtime import parameters
        self.assertIn('run_scenario',{t['name'] for t in parameters(Path('candidate'),tool_profile='game')['dynamicTools']})
        import test_development_checks as fixtures
        from agent_workbench.development.service import DevelopmentTask
        fixtures.DevelopmentCheckTests.setUp(self)
        (self.workspace.control/'request.json').write_text(json.dumps({'request':'新的规则需求','tool_profile':'game'}))
        task=DevelopmentTask(self.workspace.control)
        grant={'max_calls':1,'max_input_bytes':128000,'max_output_tokens':512,'cost_cap_usd':'0',
               'input_usd_per_million':'0','cached_input_usd_per_million':'0','output_usd_per_million':'0'}
        scope=task.prepare('profile-check',grant)
        self.assertEqual(scope['tool_profile'],'game')
        task.tool_profile='standard'
        with self.assertRaises(ValueError):task.execute('profile-check',scope['scope_sha256'],Path('unused'),Path('unused'),sender=lambda x:b'')
