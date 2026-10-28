"""Launcher glue for C++ bridge route decisions and failure handling."""
import asyncio
import hashlib
import json
import secrets
import os
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
from tests.native_fixtures import ssh_public_key
from hookup.nodes import profile_data, remember
from hookup.profiles import RelayProfile
from hookup.native_routes import BridgeError, NativeRoutes, startup_error


class NativeRoutesTests(unittest.IsolatedAsyncioTestCase):
    async def test_storage_failures_reach_launcher_without_forwarding_arbitrary_stderr(self):
        process = SimpleNamespace(stderr=SimpleNamespace(readline=AsyncMock(side_effect=[
            b'bridge journal write failed (4); game forwarding continues\n',
            b'bridge journal cleanup failed (5); game forwarding continues\r\n',
            b'private-credential-or-SDP-must-not-be-forwarded\n', b''])))
        with self.assertLogs('hookup.native_routes', level='WARNING') as logs:
            await NativeRoutes()._drain_stderr(process)
        self.assertEqual(len(logs.output), 2)
        self.assertIn('operation=write failures=4', logs.output[0])
        self.assertIn('operation=cleanup failures=5', logs.output[1])
        self.assertNotIn('private', str(logs.output))

    async def test_diagnostic_export_never_starts_or_interrupts_a_busy_bridge(self):
        from hookup.native_routes import diagnostic_snapshot
        loop = asyncio.get_running_loop()
        manager = NativeRoutes()
        manager.library = Mock()
        manager._request = AsyncMock(return_value={'flushed': True, 'pending_events': 0})
        with patch('hookup.native_routes._managers', {}), \
                patch('hookup.native_routes.manager') as create:
            self.assertEqual((await diagnostic_snapshot())['status'], 'not_running')
            create.assert_not_called()
        with patch('hookup.native_routes._managers', {loop: manager}):
            self.assertEqual((await diagnostic_snapshot())['status'], 'unsupported')
            manager._request.assert_not_awaited()
            manager.diagnostic_support = True
            await manager.request_lock.acquire()
            try:
                self.assertEqual((await diagnostic_snapshot())['status'], 'busy')
                manager._request.assert_not_awaited()
                manager.library.close.assert_not_called()
            finally:
                manager.request_lock.release()
            result = await diagnostic_snapshot()
            self.assertEqual(result['status'], 'collected')
            self.assertTrue(result['flushed'])
            manager._request.assert_awaited_once_with('bridge.diagnostics', {})

    def setUp(self):
        self.key = ssh_public_key()
        self.a = RelayProfile('a.example', 3333, secrets.token_urlsafe(48), self.key)
        self.b = RelayProfile('b.example', 3333, secrets.token_urlsafe(48), self.key)
        remember(self.a, [profile_data(self.b)])
        self.identity = hashlib.sha256(json.dumps(profile_data(self.a), sort_keys=True).encode()).digest()

    async def test_missing_binary_fails_without_python_network_fallback(self):
        manager = NativeRoutes()
        with patch('hookup.native_routes.library_path', return_value=None), \
                patch('hookup.native_routes.executable', return_value=None) as find:
            with self.assertRaises(ConnectionError):
                await manager.choose(self.a)
            find.assert_called_once()

    async def test_empty_refresh_preserves_previous_pinned_backup(self):
        from hookup.nodes import candidates
        remember(self.a, [])
        self.assertEqual(candidates(self.a), [self.a, self.b])

    async def test_os_denied_execution_fails_without_disclosing_credentials(self):
        manager = NativeRoutes()
        with patch('hookup.native_routes.library_path', return_value=None), \
                patch('hookup.native_routes.executable', return_value='native-test-binary'), \
                patch('asyncio.create_subprocess_exec', new=AsyncMock(side_effect=OSError(4551, 'Application control'))):
            with self.assertLogs('hookup.native_routes', level='WARNING') as logs:
                with self.assertRaises(ConnectionError):
                    await manager.choose(self.a)
            self.assertNotIn(self.a.token, str(logs.output))
            self.assertIsNone(manager.process)

    async def test_auto_prefers_library_without_starting_executable(self):
        manager = NativeRoutes()
        library = Mock()
        manager._request = AsyncMock(return_value={'methods': [
            'node.add', 'node.selected', 'node.request', 'room.host', 'room.join',
            'room.close', 'room.configure', 'room.retarget', 'game.status', 'game.discover',
            'session.events', 'session.list', 'mods.manifest', 'mods.fetch', 'mods.status',
            'mods.cancel', 'social.operate']})
        with patch.dict(os.environ, {}, clear=True), \
                patch('hookup.native_routes.library_path', return_value='absolute-library'), \
                patch('hookup.native_routes.load_library', return_value=library), \
                patch('asyncio.create_subprocess_exec', new=AsyncMock()) as spawn:
            await manager.ensure()
            self.assertIs(manager.library, library)
            spawn.assert_not_called()
            await manager.close()
            library.close.assert_called_once()

    async def test_library_load_failure_is_reported_without_trying_executable(self):
        manager = NativeRoutes()
        with patch.dict(os.environ, {'BUGGCRAFT_BRIDGE_MODE': 'library'}), \
                patch('hookup.native_routes.library_path', return_value='absolute-library'), \
                patch('hookup.native_routes.load_library', side_effect=OSError(126, 'dependency missing')), \
                patch('asyncio.create_subprocess_exec', new=AsyncMock()) as spawn:
            with self.assertRaisesRegex(ConnectionError, '依赖库缺失'):
                await manager.choose(self.a)
            spawn.assert_not_called()

    def test_startup_errors_distinguish_dependencies_policy_and_architecture(self):
        for code, expected in ((126, '依赖库缺失'), (4551, 'Windows 应用控制'),
                               (577, 'Windows 应用控制'), (193, '架构不匹配'),
                               (5, '访问被拒绝')):
            error = OSError('sensitive path or token must not be logged')
            error.winerror = code
            with self.subTest(code=code), self.assertLogs('hookup.native_routes') as logs:
                self.assertIn(expected, str(startup_error(error, 'library')))
            self.assertIn('code=' + str(code), str(logs.output))
            self.assertNotIn(str(error), str(logs.output))

    def test_missing_dependency_is_not_reported_as_a_windows_block(self):
        with self.assertLogs('hookup.native_routes'):
            message = str(startup_error(FileNotFoundError('dependency'), 'library'))
        self.assertIn('依赖库缺失', message)
        self.assertNotIn('阻止', message)

    async def test_native_choice_is_cached_and_delivers_one_short_tip(self):
        manager = NativeRoutes()
        manager.process = SimpleNamespace(returncode=None)
        manager.handles[self.identity] = 'opaque-handle'
        tip = Mock()
        object.__setattr__(self.a, '_route_notice', tip)
        manager._request = AsyncMock(side_effect=[dict(profile=profile_data(self.b), backups=[profile_data(self.a)]),
            dict(events=[dict(type='node_route_changed', node='opaque-handle', to='Node B', reason='unavailable')])])
        self.assertEqual(await manager.choose(self.a), [self.b, self.a])
        self.assertEqual(await manager.choose(self.a), [self.b, self.a])
        tip.assert_called_once_with('Node B')
        self.assertEqual(manager._request.await_count, 2)

    async def test_failed_connection_invalidates_cache_and_notifies_native_selector(self):
        manager = NativeRoutes()
        manager.process = SimpleNamespace(returncode=None)
        manager.handles[self.identity] = 'opaque-handle'
        manager.cached[self.identity] = (0, [self.b, self.a])
        manager._request = AsyncMock(return_value={'recorded': True})
        await manager.failed(self.a, self.b)
        self.assertNotIn(self.identity, manager.cached)
        manager._request.assert_awaited_once_with('node.failed', dict(node='opaque-handle', profile=profile_data(self.b)))

    async def test_node_error_keeps_shared_bridge_and_other_node_handles(self):
        for method in ('node.add', 'node.selected'):
            with self.subTest(method=method):
                manager = NativeRoutes()
                manager.library = Mock()
                if method == 'node.selected':
                    manager.handles[self.identity] = 'opaque-handle'
                manager.handles[b'other-node'] = 'active-room-node'
                manager._request = AsyncMock(side_effect=BridgeError(-32000, 'No reachable node'))
                with self.assertRaises(BridgeError):
                    await manager.choose(self.a)
                manager.library.close.assert_not_called()
                self.assertEqual(manager.handles[b'other-node'], 'active-room-node')

    async def test_cancelled_route_waiting_for_rpc_keeps_active_bridge(self):
        manager = NativeRoutes()
        library = manager.library = Mock()
        manager.handles[self.identity] = 'opaque-handle'
        await manager.request_lock.acquire()
        try:
            pending = asyncio.create_task(manager.choose(self.a))
            await asyncio.sleep(0)
            pending.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await pending
            self.assertIs(manager.library, library)
            library.close.assert_not_called()
            self.assertEqual(manager.handles[self.identity], 'opaque-handle')
        finally:
            manager.request_lock.release()

    async def test_bad_route_result_does_not_close_other_rooms(self):
        manager = NativeRoutes()
        library = manager.library = Mock()
        manager.handles[self.identity] = 'opaque-handle'
        manager._request = AsyncMock(return_value={'profile': {'invalid': True}})
        with self.assertRaises(ConnectionError):
            await manager.choose(self.a)
        self.assertIs(manager.library, library)
        library.close.assert_not_called()

    async def test_broken_rpc_response_still_closes_shared_bridge(self):
        manager = NativeRoutes()
        library = manager.library = Mock()
        manager.handles[self.identity] = 'opaque-handle'
        library.exchange.return_value = b'{invalid-json'
        with self.assertRaisesRegex(ConnectionError, 'invalid JSON'):
            await manager.choose(self.a)
        self.assertIsNone(manager.library)
        self.assertEqual(manager.handles, {})
        library.close.assert_called_once()
