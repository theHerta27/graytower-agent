import importlib.util
from pathlib import Path
import tempfile
import tomllib
import unittest

from agent_workbench.coding.runtime_adapter import runtime_config, safe_environment, thread_params, validate_runtime_receipt


class RuntimeConfigTests(unittest.TestCase):
    def test_only_loopback_provider_endpoint_and_explicit_modes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for mode in ('single', 'auto'):
                config = tomllib.loads(runtime_config(root, root / 'w', root / 'data',
                                       Path('D:/python.exe'), 'http://127.0.0.1:4567', mode))
                self.assertEqual(config['model'], 'deepseek-flash')
                self.assertEqual(config['review_model'], 'deepseek-flash')
                self.assertFalse(config['features']['shell_tool'])
                self.assertEqual(config['sandbox_mode'], 'read-only')
                self.assertEqual(config['agents']['enabled'], mode == 'auto')
                self.assertFalse(config['model_providers']['deepseek_local']['requires_openai_auth'])
            for endpoint in ('https://api.openai.com', 'http://localhost:22',
                             'http://127.0.0.1:12/secret', 'http://user@127.0.0.1:20'):
                with self.assertRaises(ValueError):
                    runtime_config(root, root / 'w', root / 'data', Path('D:/python.exe'), endpoint, 'single')

    def test_environment_does_not_inherit_auth_or_proxy(self):
        result = safe_environment({'SYSTEMROOT': 'C:/Windows', 'DEEPSEEK_API_KEY': 'secret',
                                   'OPENAI_API_KEY': 'secret', 'HTTPS_PROXY': 'secret',
                                   'PATH': 'D:/bin', 'PYTHONPATH': 'secret'}, Path('D:/src'))
        self.assertNotIn('DEEPSEEK_API_KEY', result)
        self.assertNotIn('OPENAI_API_KEY', result)
        self.assertNotIn('HTTPS_PROXY', result)
        self.assertEqual(result['PYTHONPATH'], 'D:\\src' if __import__('os').name == 'nt' else 'D:/src')

    def test_sdk_thread_has_no_fallback_and_explicit_tool_capability(self):
        value = thread_params(Path('D:/work'), 'single')
        self.assertEqual(value['model'], 'deepseek-flash')
        self.assertEqual(value['modelProvider'], 'deepseek_local')
        self.assertFalse(value['allowProviderModelFallback'])
        self.assertEqual(value['approvalPolicy'], 'never')
        self.assertEqual(value['approvalsReviewer'], 'user')
        self.assertEqual([x['name'] for x in value['dynamicTools']], ['edit_text'])

    def test_review_receipt_must_bind_current_bytes_and_tree_before_import(self):
        receipt = {'status': 'completed', 'review_turn': {'status': 'completed'},
                   'after_sha256': 'a'*64, 'review_file_sha256': 'a'*64,
                   'after_tree_hash': 'b'*64, 'review_tree_hash': 'b'*64}
        inspection = {'after_hash': 'a'*64, 'after_tree_hash': 'b'*64}
        validate_runtime_receipt(receipt, inspection)
        with self.assertRaises(ValueError):
            validate_runtime_receipt(receipt, inspection | {'after_tree_hash': 'c'*64})
        with self.assertRaises(ValueError):
            validate_runtime_receipt(receipt, inspection | {'after_hash': 'c'*64})
        with self.assertRaises(ValueError):
            validate_runtime_receipt({'status': 'completed'}, {})


if __name__ == '__main__':
    unittest.main()
