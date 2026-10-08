import tempfile
from pathlib import Path
import unittest
from agent_workbench.code_candidates import prepare_shield_case, TARGET
from agent_workbench.coding.file_tools import FileTools, edit_handler
from agent_workbench.coding.runtime_adapter import thread_params, model_catalog, runtime_config


class PythonCodingToolsTests(unittest.TestCase):
    def test_scoped_edit_recovery_and_source_inspection(self):
        with tempfile.TemporaryDirectory(dir=Path('local-data')) as tmp:
            root=Path(tmp).resolve()
            workspace=prepare_shield_case(root/'control',root/'workspace')
            try:
                before=workspace.inspect_changes()
                self.assertEqual(before['changed_files'],[])
                reader=workspace.read_file('game-core/combat_core/v2/state.py')
                self.assertIn('ShieldInstance',reader['text'])
                with self.assertRaises(ValueError): workspace.read_file('../../preparation.json')
                tools=FileTools(workspace.path,root/'file-control',editable_file=TARGET)
                current=tools.read_file()
                args={'path':TARGET,'expected_sha256':current['sha256'],
                      'old_text':'hp_loss=min(u.hp,amount)','new_text':'hp_loss=min(u.hp,left)'}
                handler=edit_handler(tools,'primary')
                self.assertFalse(handler('item/tool/call',{'threadId':'child','tool':'edit_text','callId':'x','arguments':args})['success'])
                first=tools.replace_text('once',**args)
                self.assertEqual(first,tools.replace_text('once',**args))
                self.assertEqual(workspace.inspect_changes()['changed_files'],[TARGET])
                with self.assertRaises(ValueError):tools.read_file('game-core/combat_core/v2/state.py')
            finally: workspace.remove()

    def test_python_profile_uses_same_runtime_with_bounded_instruction(self):
        params=thread_params(Path('local-data/code'), 'single', profile='shield-damage-python-v1')
        self.assertIn('Python',params['developerInstructions'])
        self.assertIn('护盾',params['developerInstructions'])
        self.assertFalse(params['allowProviderModelFallback'])
        self.assertEqual(params['sandbox'],'read-only')
        catalog=model_catalog(profile='shield-damage-python-v1')
        self.assertEqual(catalog['models'][0]['slug'],'deepseek-flash')
        self.assertIn('Python',catalog['models'][0]['model_messages']['instructions_template'])
        config=runtime_config(Path('local-data/home'),Path('local-data/ws'),Path('local-data/data'),Path('python.exe'),
                              'http://127.0.0.1:19999','single',{'profile':'shield-damage-python-v1'})
        self.assertIn('shell_tool = false',config)
        with self.assertRaises(ValueError):thread_params(Path('.'),'single',profile='arbitrary-code')
