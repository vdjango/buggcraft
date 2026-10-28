"""Failure evidence must identify the stage while keeping signed data private."""
import asyncio
import json
import logging
import os
from pathlib import Path
import re
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from zipfile import ZipFile

from hookup.native_routes import BridgeError, NativeRoutes, REQUEST_TRACE
from hookup.social import operate


class SocialDiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    def profile(self):
        return SimpleNamespace(server_host='node.example', server_port=3333,
                               token='private-access-token')

    async def test_node_failure_logs_stage_and_code_without_request_or_error_body(self):
        bridge = SimpleNamespace(handle=AsyncMock(return_value='private-handle'),
                                 request=AsyncMock(side_effect=BridgeError(-32031, 'private-error-token')))
        with patch('hookup.native_routes.manager', return_value=bridge), \
                self.assertLogs('hookup.social', level='DEBUG') as logs:
            with self.assertRaises(BridgeError):
                await operate(self.profile(), 'invite', 'private-target', invite='private-room-code')
        output = '\n'.join(logs.output)
        self.assertIn('stage=node_request', output)
        self.assertIn('error_code=-32031', output)
        self.assertIn('node_host=node.example', output)
        self.assertEqual(len(set(re.findall(r'trace=([0-9a-f]+)', output))), 1)
        for secret in ('private-access-token', 'private-error-token', 'private-target',
                       'private-room-code', 'private-handle'):
            self.assertNotIn(secret, output)
        self.assertIsNone(REQUEST_TRACE.get())

    async def test_handle_failure_and_invalid_response_are_distinguished(self):
        cases = ((AsyncMock(side_effect=OSError('private-detail')), AsyncMock(), 'node_handle'),
                 (AsyncMock(return_value='handle'), AsyncMock(return_value=[]), 'response'))
        for handle, request, stage in cases:
            with self.subTest(stage=stage), \
                    patch('hookup.native_routes.manager', return_value=SimpleNamespace(handle=handle, request=request)), \
                    self.assertLogs('hookup.social', level='DEBUG') as logs:
                with self.assertRaises((OSError, ValueError)):
                    await operate(self.profile(), 'presence')
                self.assertIn('stage='+stage, '\n'.join(logs.output))
                self.assertNotIn('private-detail', '\n'.join(logs.output))
            self.assertIsNone(REQUEST_TRACE.get())

    async def test_concurrent_social_calls_keep_separate_rpc_traces(self):
        traces = []
        async def request(method, params):
            before = REQUEST_TRACE.get()
            await asyncio.sleep(0)
            self.assertEqual(before, REQUEST_TRACE.get())
            traces.append(before)
            return {'private-response': 'not-in-logs'}
        bridge = SimpleNamespace(handle=AsyncMock(return_value='handle'), request=request)
        with patch('hookup.native_routes.manager', return_value=bridge), \
                self.assertLogs('hookup.social', level='DEBUG') as logs:
            await asyncio.gather(operate(self.profile(), 'presence'), operate(self.profile(), 'presence'))
        self.assertEqual(len(set(traces)), 2)
        self.assertTrue(all(re.fullmatch('[0-9a-f]{12}', trace) for trace in traces))
        self.assertNotIn('not-in-logs', '\n'.join(logs.output))
        self.assertIsNone(REQUEST_TRACE.get())

    async def test_social_cancellation_is_recorded_without_reporting_node_failure(self):
        bridge = SimpleNamespace(handle=AsyncMock(side_effect=asyncio.CancelledError()), request=AsyncMock())
        with patch('hookup.native_routes.manager', return_value=bridge), \
                self.assertLogs('hookup.social', level='DEBUG') as logs:
            with self.assertRaises(asyncio.CancelledError):
                await operate(self.profile(), 'presence')
        self.assertIn('social_request_cancelled', '\n'.join(logs.output))
        self.assertNotIn('social_request_failed', '\n'.join(logs.output))
        self.assertIsNone(REQUEST_TRACE.get())

    async def test_rpc_error_retains_code_and_trace_but_never_signed_payload(self):
        bridge = NativeRoutes()
        bridge.library = SimpleNamespace(exchange=lambda payload: json.dumps({
            'id': json.loads(payload)['id'], 'error': {'code': -32031, 'message': 'private-error'}}).encode())
        token = REQUEST_TRACE.set('social-trace')
        try:
            with self.assertLogs('hookup.native_routes', level='DEBUG') as logs:
                with self.assertRaises(BridgeError):
                    await bridge._request('social.operate', {'event': 'private-signed-event'})
        finally:
            REQUEST_TRACE.reset(token)
        output = '\n'.join(logs.output)
        self.assertIn('trace=social-trace', output)
        self.assertIn('phase=response', output)
        self.assertIn('rpc_id=1', output)
        self.assertIn('error_code=-32031', output)
        self.assertNotIn('private-error', output)
        self.assertNotIn('private-signed-event', output)

    async def test_rpc_queue_delay_is_measured_separately_from_exchange(self):
        bridge = NativeRoutes()
        bridge.library = SimpleNamespace(exchange=lambda payload: json.dumps({
            'id': json.loads(payload)['id'], 'result': {'ok': True}}).encode())
        await bridge.request_lock.acquire()
        with self.assertLogs('hookup.native_routes', level='DEBUG') as logs:
            pending = asyncio.create_task(bridge._request('social.operate', {}))
            try:
                await asyncio.sleep(.04)
            finally:
                bridge.request_lock.release()
            self.assertEqual(await pending, {'ok': True})
        output = '\n'.join(logs.output)
        queued = float(re.search(r'queue_ms=([0-9.]+)', output).group(1))
        self.assertGreaterEqual(queued, 20)
        self.assertIn('native_rpc_complete', output)

    async def test_timeout_logs_reset_and_preserves_original_exception(self):
        bridge = NativeRoutes()
        def exchange(payload):
            raise TimeoutError('private-timeout-detail')
        bridge.library = SimpleNamespace(exchange=exchange)
        bridge.close = AsyncMock()
        with self.assertLogs('hookup.native_routes', level='DEBUG') as logs:
            with self.assertRaises(TimeoutError):
                await bridge._request('social.operate', {'token': 'private-token'})
        bridge.close.assert_awaited_once()
        output = '\n'.join(logs.output)
        self.assertIn('native_bridge_reset', output)
        self.assertIn('phase=bridge_call', output)
        self.assertIn('error=TimeoutError', output)
        self.assertNotIn('private-timeout-detail', output)
        self.assertNotIn('private-token', output)

    async def test_cancelling_queued_call_does_not_reset_another_active_request(self):
        bridge = NativeRoutes()
        bridge.close = AsyncMock()
        await bridge.request_lock.acquire()
        try:
            with self.assertLogs('hookup.native_routes', level='DEBUG') as logs:
                pending = asyncio.create_task(bridge._request('social.operate', {}))
                await asyncio.sleep(0)
                pending.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await pending
            output = '\n'.join(logs.output)
            self.assertIn('native_rpc_cancelled', output)
            self.assertIn('phase=queue', output)
            self.assertNotIn('native_rpc_failed', output)
            bridge.close.assert_not_awaited()
        finally:
            bridge.request_lock.release()

    async def test_real_log_file_and_export_preserve_correlated_failure_evidence(self):
        from utils import diagnostics
        from utils.http_identity import LAUNCHER_VERSION
        bridge = NativeRoutes()
        bridge.library = SimpleNamespace(exchange=lambda payload: json.dumps({
            'id': json.loads(payload)['id'], 'error': {'code': -32031, 'message': 'private-error'}}).encode())
        bridge.handle = AsyncMock(return_value='handle')
        loggers = [logging.getLogger(name) for name in ('hookup.social', 'hookup.native_routes',
            'hookup.native_transport', 'hookup.rooms', 'hookup.network_diagnostics')]
        levels = [logger.level for logger in loggers]
        root = logging.getLogger()
        original_handlers = list(root.handlers)
        try:
            with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ), \
                    patch.object(diagnostics, '_session_file', None), patch.object(diagnostics, '_log_root', None), \
                    patch('utils.diagnostics.atexit.register'), \
                    patch('hookup.native_routes.manager', return_value=bridge), \
                    patch('utils.network_diagnostics.capture_network', return_value={'trace_id': 'test'}):
                try:
                    session = diagnostics.configure_connection_logging(temporary)
                    with self.assertRaises(BridgeError):
                        await operate(self.profile(), 'presence', token='private-payload')
                    archive = diagnostics.export_diagnostics(Path(temporary)/'support.zip', temporary)
                    with ZipFile(archive) as exported:
                        evidence = exported.read('p2p-sessions/'+session.name).decode('utf-8')
                        metadata = json.loads(exported.read('diagnostics.json'))
                    self.assertIn('social_request_start', evidence)
                    self.assertIn('social_request_failed', evidence)
                    self.assertIn('native_rpc_failed', evidence)
                    self.assertEqual(len(set(re.findall(r'trace=([0-9a-f]{12})', evidence))), 1)
                    self.assertIn('error_code=-32031', evidence)
                    self.assertNotIn('private-error', evidence)
                    self.assertNotIn('private-payload', evidence)
                    self.assertEqual(metadata['launcher_version'], LAUNCHER_VERSION)
                    self.assertEqual(metadata['diagnostic_schema'], 2)
                finally:
                    for handler in list(root.handlers):
                        if handler not in original_handlers:
                            root.removeHandler(handler)
                            handler.close()
        finally:
            for logger, level in zip(loggers, levels):
                logger.setLevel(level)
