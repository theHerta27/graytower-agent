import unittest
from unittest.mock import patch
from agent_workbench.code_sandbox import execute_tree, IMAGE

class CleanupTests(unittest.TestCase):
    def test_execution_container_creation_failure_removes_materialized_image(self):
        calls=[]
        def docker(*args,**kwargs):
            calls.append(args)
            if args[:2]==('image','inspect'):return IMAGE.encode()
            if args[0]=='create':
                if '--read-only' in args:raise RuntimeError('creation failed')
                return b'seed'
            if args[0]=='commit':return b'sealed-image'
            return b''
        with patch('agent_workbench.code_sandbox.command',side_effect=docker):
            with self.assertRaises(RuntimeError):execute_tree({'files':{}})
        self.assertIn(('image','rm','sealed-image'),calls)
        self.assertIn(('rm','-f','seed'),calls)
