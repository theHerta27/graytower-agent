"""Actual A2A HTTP/SQLite integration; callback is a fixture, no model or game."""
import asyncio
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import httpx
from google.protobuf.json_format import ParseDict
from google.protobuf.struct_pb2 import Value
from a2a.client import ClientConfig, create_client
from a2a.types import CancelTaskRequest, GetTaskRequest, ListTasksRequest, Message, Part, Role, SendMessageRequest
from a2a.utils.errors import InvalidParamsError, TaskNotCancelableError, UnsupportedOperationError

from agent_workbench.domain._shared import Artifacts
from agent_workbench.jobs import JobStore
from agent_workbench.protocol import VerificationFailedError, delegate, local_verifier


class ProductA2ATests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = JobStore(self.root)
        self.manifest = Artifacts(self.root / 'artifacts').put({
            'schema_version': 'candidate-manifest-v1', 'kind': 'numeric_config',
            'profile': 'trusted-combat-numeric-v1', 'author': 'config'}, 'candidate-manifest-v1')['sha256']
        self.report = {'schema_version': 'qa-report-v1', 'request_id': 'qa-1',
                       'manifest_hash': self.manifest, 'verdict': 'INCONCLUSIVE',
                       'summary': 'fixture only; no game/model', 'charged_battles': 0}

    def payload(self, **changes):
        value = {'request_id': 'qa-1', 'manifest_hash': self.manifest, 'goal': 'check numeric change',
                 'max_battles': 4, 'kind': 'numeric_config', 'profile': 'trusted-combat-numeric-v1'}
        value.update(changes)
        return value

    async def fixture(self, request_id):
        self.assertEqual(request_id, 'qa-1')
        return self.report

    async def raw_send(self, base, payload, task_id=''):
        async with httpx.AsyncClient(trust_env=False, timeout=10) as http:
            client = await create_client(base, client_config=ClientConfig(streaming=False, httpx_client=http))
            message = Message(message_id=str(uuid.uuid4()), role=Role.ROLE_USER,
                              task_id=task_id, parts=[Part(data=ParseDict(payload, Value()))])
            return [event async for event in client.send_message(SendMessageRequest(message=message))]

    async def test_unconfirmed_request_is_rejected_before_receipt_or_execution(self):
        async with local_verifier(self.root, self.fixture) as base:
            with self.assertRaises(InvalidParamsError):
                await delegate(base, 'qa-1', self.manifest, 'check numeric change', 4)
        with self.assertRaises(KeyError):
            self.store.get('qa-1')

    async def test_completed_inconclusive_receipt_survives_server_reopen_with_new_task(self):
        self.store.confirm(self.manifest)
        async with local_verifier(self.root, self.fixture) as base:
            first = await delegate(base, 'qa-1', self.manifest, 'check numeric change', 4)
        self.assertEqual(first['task_state'], 'TASK_STATE_COMPLETED')
        self.assertEqual(first['report'], self.report)
        self.assertEqual(JobStore(self.root).get('qa-1')['report'], self.report)

        async def forbidden(_):
            raise AssertionError('completed receipt must not execute again')

        async with local_verifier(self.root, forbidden) as base:
            async with httpx.AsyncClient(trust_env=False) as http:
                client = await create_client(base, client_config=ClientConfig(streaming=False, httpx_client=http))
                old = await client.get_task(GetTaskRequest(id=first['task_id']))
                self.assertEqual(old.id, first['task_id'])
            second = await delegate(base, 'qa-1', self.manifest, 'check numeric change', 4)
        self.assertNotEqual(first['task_id'], second['task_id'])
        self.assertEqual(second['report'], first['report'])
        self.assertEqual(JobStore(self.root).get('qa-1')['charged_battles'], 0)

    async def test_changed_immutable_payload_rejected_without_altering_completed_receipt(self):
        self.store.confirm(self.manifest)
        async with local_verifier(self.root, self.fixture) as base:
            await delegate(base, 'qa-1', self.manifest, 'check numeric change', 4)
            with self.assertRaises(InvalidParamsError):
                await delegate(base, 'qa-1', self.manifest, 'replace the goal', 4)
        self.assertEqual(self.store.get('qa-1')['goal'], 'check numeric change')
        self.assertEqual(self.store.get('qa-1')['report'], self.report)

    async def test_unsupported_kind_and_budget_shape_rejected_before_admission(self):
        self.store.confirm(self.manifest)
        async with local_verifier(self.root, self.fixture) as base:
            with self.assertRaises(UnsupportedOperationError):
                await self.raw_send(base, self.payload(kind='code'))
            with self.assertRaises(InvalidParamsError):
                await self.raw_send(base, self.payload(max_battles=True))
            code_manifest = Artifacts(self.root / 'artifacts').put({
                'schema_version': 'candidate-manifest-v1', 'kind': 'code',
                'profile': 'trusted-combat-numeric-v1'}, 'candidate-manifest-v1')['sha256']
            self.store.confirm(code_manifest)
            with self.assertRaises(UnsupportedOperationError):
                await delegate(base, 'qa-1', code_manifest, 'check numeric change', 4)
        with self.assertRaises(KeyError):
            self.store.get('qa-1')

    async def test_execution_exception_is_failed_not_completed_or_pass(self):
        self.store.confirm(self.manifest)

        async def fail(_):
            raise RuntimeError('fixture worker unavailable')

        async with local_verifier(self.root, fail) as base:
            with self.assertRaises(VerificationFailedError) as caught:
                await delegate(base, 'qa-1', self.manifest, 'check numeric change', 4)
            self.assertEqual(caught.exception.task_state, 'TASK_STATE_FAILED')
            self.assertIn('RuntimeError', str(caught.exception))
        self.assertIsNone(self.store.get('qa-1')['report'])

    async def test_delivered_business_fail_is_completed_not_execution_failure(self):
        self.store.confirm(self.manifest)
        self.report['verdict'] = 'FAIL'  # Protocol fixture, not a game quality claim.
        self.report['summary'] = 'fixture reports a deterministic failed check'
        async with local_verifier(self.root, self.fixture) as base:
            result = await delegate(base, 'qa-1', self.manifest, 'check numeric change', 4)
        self.assertEqual(result['task_state'], 'TASK_STATE_COMPLETED')
        self.assertEqual(result['report']['verdict'], 'FAIL')

    async def test_v1_does_not_deliver_callback_pass_as_small_sample_success(self):
        self.store.confirm(self.manifest)
        self.report['verdict'] = 'PASS'
        async with local_verifier(self.root, self.fixture) as base:
            with self.assertRaises(VerificationFailedError) as caught:
                await delegate(base, 'qa-1', self.manifest, 'check numeric change', 4)
        self.assertEqual(caught.exception.task_state, 'TASK_STATE_FAILED')
        self.assertIsNone(self.store.get('qa-1')['report'])

    async def test_cancel_rejected_without_interrupting_live_callback(self):
        self.store.confirm(self.manifest)
        started, release = asyncio.Event(), asyncio.Event()

        async def slow(request_id):
            started.set()
            await release.wait()
            return self.report

        async with local_verifier(self.root, slow) as base:
            pending = asyncio.create_task(delegate(base, 'qa-1', self.manifest, 'check numeric change', 4))
            try:
                await asyncio.wait_for(started.wait(), 5)
                async with httpx.AsyncClient(trust_env=False) as http:
                    client = await create_client(base, client_config=ClientConfig(streaming=False, httpx_client=http))
                    tasks = await client.list_tasks(ListTasksRequest())
                    self.assertEqual(len(tasks.tasks), 1)
                    with self.assertRaises(TaskNotCancelableError):
                        await client.cancel_task(CancelTaskRequest(id=tasks.tasks[0].id))
                self.assertFalse(pending.done())
            finally:
                release.set()
            result = await pending
            self.assertEqual(result['task_state'], 'TASK_STATE_COMPLETED')

    async def test_product_refuses_append_and_remote_client_urls(self):
        self.store.confirm(self.manifest)
        async with local_verifier(self.root, self.fixture) as base:
            result = await delegate(base, 'qa-1', self.manifest, 'check numeric change', 4)
            with self.assertRaises(UnsupportedOperationError):
                await self.raw_send(base, self.payload(), task_id=result['task_id'])
        await asyncio.sleep(.05)
        dispatchers = [task for task in asyncio.all_tasks()
                       if 'EventQueueSource._dispatch_loop' in str(task.get_coro())]
        self.assertEqual(dispatchers, [], 'Product admission must not enter the known SDK terminal-start leak')
        with self.assertRaises(ValueError):
            await delegate('http://example.com', 'qa-1', self.manifest, 'goal', 4)

    async def test_card_cannot_redirect_verification_payload_outside_local_origin(self):
        # Only the network is replaced: the real official Card resolver/client
        # and product delegate run. This fixture cannot make external requests.
        for advertised in ('http://example.com/a2a/jsonrpc', 'http://127.0.0.1:54322/a2a/jsonrpc'):
            with self.subTest(advertised=advertised):
                contacted = []

                def fixture_transport(request):
                    contacted.append(str(request.url))
                    if request.url.path == '/.well-known/agent-card.json':
                        return httpx.Response(200, json={
                            'name': 'Untrusted fixture card', 'version': '1', 'capabilities': {},
                            'supportedInterfaces': [{'protocolBinding': 'JSONRPC', 'protocolVersion': '1.0',
                                                     'url': advertised}],
                            'defaultInputModes': ['application/json'], 'defaultOutputModes': ['application/json'],
                            'skills': []})
                    return httpx.Response(500, text='outbound attempt intercepted by test')

                client = httpx.AsyncClient(transport=httpx.MockTransport(fixture_transport), trust_env=False)
                caught = None
                with patch('agent_workbench.protocol.httpx.AsyncClient', return_value=client):
                    try:
                        await delegate('http://127.0.0.1:54321', 'qa-1', self.manifest, 'goal', 4)
                    except Exception as exc:
                        caught = exc
                self.assertEqual(contacted, ['http://127.0.0.1:54321/.well-known/agent-card.json'],
                                 'Card-declared endpoint must be checked before sending any payload')
                self.assertIsInstance(caught, ValueError)


if __name__ == '__main__':
    unittest.main()
