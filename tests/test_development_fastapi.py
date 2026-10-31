"""API migration contracts; all model calls remain mocked or disabled."""
import unittest
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from unittest.mock import patch

from starlette.testclient import TestClient
import test_development_checks as fixtures
from agent_workbench.development.web import create_app
from agent_workbench.development.service import DevelopmentTask as RealTask


class FastAPIContracts(unittest.TestCase):
    def setUp(self):
        fixtures.DevelopmentCheckTests.setUp(self)
        self.app = create_app(self.root / 'api')
        self.client = TestClient(self.app, base_url='http://127.0.0.1:18790')
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def create(self):
        response = self.client.post('/api/development/tasks', json={
            'project': str(self.root / 'source'), 'request': '修复资源输入',
        })
        self.assertEqual(response.status_code, 200, response.text)
        return '/api/development/tasks/' + response.json()['task_id']

    def test_native_fastapi_app_and_documented_typed_operations(self):
        self.assertEqual(type(self.app).__module__, 'fastapi.applications')
        response = self.client.get('/openapi.json')
        self.assertEqual(response.status_code, 200)
        schema = response.json()
        for suffix in ('', '/run', '/resume', '/check', '/edit', '/memories', '/knowledge',
                       '/delivery-prepare', '/delivery-approve', '/archive'):
            path = '/api/development/tasks' + ('/{task_id}' + suffix if suffix else '')
            operation = schema['paths'][path]['post']
            self.assertTrue(operation['requestBody']['content']['application/json']['schema'])
        self.assertIn('TaskCreate', schema['components']['schemas'])
        self.assertFalse(schema['components']['schemas']['TaskCreate']['additionalProperties'])

    def test_docs_are_read_only_and_origin_checks_still_apply(self):
        with patch('agent_workbench.development.service.ToolModel') as model:
            self.assertEqual(self.client.get('/docs').status_code, 200)
            self.assertEqual(self.client.get('/openapi.json').status_code, 200)
            model.assert_not_called()
        self.assertEqual(self.client.get('/docs', headers={'Origin': 'https://evil.invalid'}).status_code, 403)

    def test_invalid_creation_is_rejected_before_side_effects_without_echo(self):
        for payload in ({}, [], {'project': 42, 'request': 'x'},
                        {'project': 'x', 'request': ''}, {'project': 'x', 'request': 42},
                        {'project': 'x', 'request': 'x', 'token': 'PRIVATE-INPUT-SENTINEL'}):
            with self.subTest(payload=payload), patch('agent_workbench.development.web.DevelopmentTask.create') as create:
                response = self.client.post('/api/development/tasks', json=payload)
                self.assertEqual(response.status_code, 422)
                self.assertIsInstance(response.json()['error'], str)
                self.assertNotIn('PRIVATE-INPUT-SENTINEL', response.text)
                create.assert_not_called()

    def test_authorization_never_coerces_strings_or_numbers_to_booleans(self):
        prefix = self.create()
        with patch('agent_workbench.development.web.Workbench.start') as start:
            for consent in ('true', 1, None, False):
                response = self.client.post(prefix + '/run', json={
                    'run_id': 'unused', 'scope_sha256': 'unused',
                    'accept_data': consent, 'accept_cost': True,
                })
                self.assertEqual(response.status_code, 422, response.text)
                self.assertIn('error', response.json())
            start.assert_not_called()

    def test_invalid_nested_operations_and_edit_types_are_rejected(self):
        prefix = self.create()
        for suffix, payload in (
            ('/memories', {'action': 'delete', 'id': 'x', 'content': 'unexpected'}),
            ('/knowledge', {'action': 'delete', 'id': 'x', 'status': 'confirmed'}),
            ('/edit', {'operation_id': 'x', 'path': 'x.py', 'expected_sha256': 'x', 'content': 42}),
        ):
            response = self.client.post(prefix + suffix, json=payload)
            self.assertEqual(response.status_code, 422)
            self.assertIn('error', response.json())

    def test_malformed_oversized_and_streamed_bodies_keep_bounded_errors(self):
        for body in (b'{', b'x' * 1_100_001):
            response = self.client.post('/api/development/tasks', content=body,
                                        headers={'content-type': 'application/json'})
            self.assertEqual(response.status_code, 422)
            self.assertIn('error', response.json())
            self.assertLess(len(response.content), 1000)
        chunks = (b'x' * 550_001 for _ in range(2))
        response = self.client.post('/api/development/tasks', content=chunks,
                                    headers={'content-type': 'application/json'})
        self.assertEqual(response.status_code, 422)
        self.assertIn('error', response.json())

    def test_unknown_post_stays_404(self):
        response = self.client.post(self.create() + '/not-an-operation', json={})
        self.assertEqual(response.status_code, 404)
        self.assertIsInstance(response.json()['error'], str)

    def test_concurrent_first_read_and_check_share_one_live_task(self):
        prefix = self.create()
        workbench = self.app.state.workbench
        workbench.cache.clear()
        entered = threading.Event()
        release = threading.Event()
        started = threading.Event()
        made = []
        counter_lock = threading.Lock()

        def construct(*args, **kwargs):
            with counter_lock:
                number = len(made)
                made.append(None)
            task = RealTask(*args, **kwargs)
            task.jobs.launcher = lambda request: None
            made[number] = task
            if number == 0:
                entered.set()
                if not release.wait(20):
                    raise AssertionError('concurrent request did not release initializer')
            return task

        def check():
            started.set()
            return self.client.post(prefix + '/check', json={'check_set': 'rules'})

        with patch('agent_workbench.development.web.DevelopmentTask', side_effect=construct):
            with ThreadPoolExecutor(2) as pool:
                first = pool.submit(self.client.get, prefix + '/memories')
                try:
                    self.assertTrue(entered.wait(10))
                    second = pool.submit(check)
                    self.assertTrue(started.wait(10))
                    # A correct cache blocks the second initializer; a broken
                    # cache completes this check using another live instance.
                    try:
                        second.result(timeout=1)
                    except TimeoutError:
                        pass
                finally:
                    release.set()
                first_response = first.result(20)
                checked = second.result(20)
                self.assertEqual(checked.status_code, 200, checked.text)
            self.assertEqual(len(made), 1, 'two live instances lose the running-check registry')
            self.assertEqual(first_response.status_code, 200, first_response.text)
            current = self.client.get(prefix).json()
            self.assertEqual(current['checks'][0]['status'], 'running')
