import json
from pathlib import Path
import tempfile
import tomllib
import unittest
try:
    from agent_workbench.development.runtime import build_config, parameters, run_runtime, INSTRUCTIONS
except ModuleNotFoundError:
    build_config=parameters=run_runtime=None;INSTRUCTIONS=''


class DevelopmentRuntimeTests(unittest.TestCase):
    def test_default_has_one_agent_real_project_tools_and_no_legacy_mcp(self):
        self.assertIsNotNone(build_config)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            config=tomllib.loads(build_config(root,root/'workspace','http://127.0.0.1:3000'))
        self.assertFalse(config['agents']['enabled'])
        self.assertFalse(config['features']['shell_tool'])
        self.assertNotIn('mcp_servers',config)
        args=parameters(Path('D:/candidate'))
        self.assertFalse(args['allowProviderModelFallback'])
        self.assertEqual(args['model'],'deepseek-flash')
        self.assertIn('start_check',[t['name'] for t in args['dynamicTools']])
        self.assertNotIn('D01',INSTRUCTIONS)
        self.assertIn('可信',INSTRUCTIONS)

    def test_only_local_gateway_and_valid_deadline_accepted(self):
        self.assertIsNotNone(build_config)
        for endpoint in ['https://api.deepseek.com','http://localhost:20','http://127.0.0.1:30/key']:
            with self.assertRaises(ValueError):build_config(Path('D:/home'),Path('D:/candidate'),endpoint)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                run_runtime(runtime_python=Path('unused'),tools_python=Path('unused'),
                    workspace_control=Path(directory),control=Path(directory)/'run',
                    endpoint='http://127.0.0.1:3000',prompt='',timeout_seconds=0)

if __name__=='__main__':unittest.main()
