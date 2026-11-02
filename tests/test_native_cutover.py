"""Guard the launcher boundary: Python only controls the native subprocess."""
import ast
import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src' / 'buggcraft'))
from hookup.native_transport import TunnelClient, TunnelHost, TunnelService
from hookup.native_routes import MAX_REQUEST_BYTES, fit_room_host_params
from hookup.profiles import RelayProfile, RoomInvite


class TunnelServiceResponsivenessTests(unittest.TestCase):
    def test_loop_initialization_and_close_never_block_the_caller(self):
        started, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        original = asyncio.new_event_loop

        def slow_loop():
            started.set()
            release.wait(2)
            return original()

        with (patch('hookup.native_transport.asyncio.new_event_loop', side_effect=slow_loop),
              patch('hookup.native_routes.close', new_callable=AsyncMock)):
            before = time.monotonic()
            service = TunnelService()
            self.assertLess(time.monotonic() - before, .2)
            self.assertTrue(started.wait(1))
            queued = service.submit(asyncio.sleep(0, result='queued'))
            before = time.monotonic()
            service.close()
            self.assertLess(time.monotonic() - before, .2)
            release.set()
            service.thread.join(2)
            self.assertFalse(service.thread.is_alive())
            self.assertTrue(queued.done())

    def test_submitted_work_completes_and_close_stops_background_loop(self):
        with patch('hookup.native_routes.close', new_callable=AsyncMock):
            service = TunnelService()
            self.assertEqual(service.submit(asyncio.sleep(0, result=42)).result(timeout=2), 42)
            service.close()
            service.thread.join(2)
            self.assertFalse(service.thread.is_alive())


class NativeBoundaryTests(unittest.TestCase):
    def test_room_host_previews_are_trimmed_to_the_native_request_limit(self):
        game = {
            'version': '1.20.1', 'loader': 'forge', 'loader_version': '47.4.0',
            'mods_count': 212, 'mods_hash': 'a' * 64,
            'mods': [{'name': f'mod-{index}.jar', 'sha256': 'b' * 64, 'size': 1000}
                     for index in range(24)],
            'resources_count': 24, 'resources_hash': 'c' * 64,
            'resources': [{'name': f'resource-{index}.zip',
                           'path': 'resourcepacks/' + ('x' * 220) + f'{index}.zip',
                           'sha256': 'd' * 64, 'size': 1000}
                          for index in range(24)],
        }
        params = {'node': 'node', 'transport': 'auto', 'compression': 'auto',
                  'announce': True, 'chat_name': 'Player',
                  'settings': {'capacity': 100, 'game': game}}

        fitted = fit_room_host_params(params)
        payload = (json.dumps({'jsonrpc': '2.0', 'id': 99999999999999999999,
                               'method': 'room.host', 'params': fitted},
                              separators=(',', ':'), ensure_ascii=False) + '\n').encode('utf-8')
        fitted_game = fitted['settings']['game']
        self.assertGreater(len(json.dumps({'settings': {'game': game}}, ensure_ascii=False)),
                           len(json.dumps({'settings': {'game': fitted_game}}, ensure_ascii=False)))
        self.assertLessEqual(len(payload), MAX_REQUEST_BYTES)
        self.assertEqual(len(fitted_game['mods']), 24)
        self.assertLess(len(fitted_game['resources']), 24)
        self.assertEqual(fitted_game['mods_count'], 212)
        self.assertEqual(fitted_game['resources_count'], 24)
        self.assertEqual(fitted_game['mods_hash'], 'a' * 64)
        self.assertEqual(fitted_game['resources_hash'], 'c' * 64)
        self.assertEqual(len(game['resources']), 24)

    def test_runtime_has_no_python_multiplayer_network_implementation(self):
        forbidden = {'asyncssh', 'socket', 'aioice', 'aiortc', 'zstandard', 'cryptography'}
        for file in (ROOT / 'src' / 'buggcraft' / 'hookup').rglob('*.py'):
            tree = ast.parse(file.read_text(encoding='utf-8'))
            imports = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.extend(alias.name.split('.')[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.append(node.module.split('.')[0])
            # Launcher device login signs approval challenges; it does not
            # implement the retired Python multiplayer transport.
            disallowed = forbidden - {'cryptography'} if file.name == 'device_login.py' else forbidden
            self.assertFalse(disallowed.intersection(imports), file.name)
        for module in ('hookup.relay', 'hookup.host', 'hookup.client', 'tunnel'):
            self.assertIsNone(importlib.util.find_spec(module), module)

    def test_tests_and_tools_do_not_reintroduce_the_retired_python_stack(self):
        forbidden = {'tunnel', 'asyncssh', 'aioice', 'aiortc', 'hookup._rtc',
                     'hookup.peer', 'hookup.ice', 'hookup.game_chat', 'hookup.legacy_chat',
                     'hookup.relay', 'hookup.host', 'hookup.client'}
        for folder in ('tests', 'scripts'):
            for file in (ROOT / folder).rglob('*.py'):
                tree = ast.parse(file.read_text(encoding='utf-8-sig'))
                for node in ast.walk(tree):
                    imports = ([alias.name for alias in node.names] if isinstance(node, ast.Import)
                               else [node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
                    for name in imports:
                        self.assertFalse(any(name == old or name.startswith(old + '.')
                                             for old in forbidden), f'{file.name}: {name}')
        self.assertFalse(any((ROOT / 'compatibility').rglob('*.py')))


class NativeEndpointTests(unittest.IsolatedAsyncioTestCase):
    def profile(self):
        return RelayProfile('127.0.0.1', 3333, 'x' * 48, 'ssh-ed25519 AAAA')

    async def test_game_latency_keeps_zero_and_replaces_stale_measurements(self):
        for endpoint in (TunnelHost(self.profile()), TunnelClient(self.profile(), RoomInvite.create())):
            for value, expected in ((0, 0), (57, 57), (None, None), (-1, None), (True, None)):
                endpoint._apply_event({'type': 'latency', 'latency_ms': value, 'state': 'ready'})
                self.assertEqual(endpoint.room_info['latency_ms'], expected)

    async def test_host_parameters_and_native_termination_reach_ui(self):
        routes = SimpleNamespace(handle=AsyncMock(return_value='node'), request=AsyncMock(side_effect=[
            {'session': 'native-session', 'invite': RoomInvite.create().encode(), 'info': {}, 'transport': 'relay'},
            {'events': [{'type': 'bridge', 'status': 'backup selected'}]},
            {'sessions': [{'session': 'native-session', 'state': 'stopped', 'reason': 'room-closed'}]},
        ]))
        endpoint = TunnelHost(self.profile(), game_port=0, game_directory='instance',
            game_chat_enabled=True, game_chat_name='LobbyBridge')
        endpoint.chat_name = 'Alice'
        states = []
        endpoint.on_status = lambda state, reason: states.append(state)
        with patch('hookup.native_transport.manager', return_value=routes), \
                patch('hookup.native_transport.fit_room_host_params',
                      wraps=fit_room_host_params) as fit_params:
            await endpoint.run()
        fit_params.assert_called_once()
        method, params = routes.request.await_args_list[0].args
        self.assertEqual(method, 'room.host')
        self.assertEqual(params['game_chat_name'], 'LobbyBridge')
        self.assertEqual(params['game_directory'], 'instance')
        self.assertEqual(params['chat_name'], 'Alice')
        self.assertEqual(states, ['online', 'closed'])
        self.assertEqual(endpoint.bridge_status, 'backup selected')

    async def test_manifest_pagination_and_cancel_always_release_native_transfer(self):
        endpoint = TunnelClient(self.profile(), RoomInvite.create())
        endpoint.session = 'session'
        endpoint._routes = SimpleNamespace(request=AsyncMock(side_effect=[
            {'transfer': 't', 'state': 'opening'},
            {'transfer': 't', 'state': 'complete', 'items': [{'name': 'a.jar'}], 'total': 2, 'offset': 0},
            {'transfer': 't', 'state': 'complete', 'items': [{'name': 'b.jar'}], 'total': 2, 'offset': 1},
            {'cancelled': True}]))
        self.assertEqual(await endpoint.mod_manifest(), [{'name': 'a.jar'}, {'name': 'b.jar'}])
        self.assertEqual(endpoint._routes.request.await_args.args[0], 'mods.cancel')

    async def test_manifest_forward_failure_uses_only_a_complete_verified_room_preview(self):
        from hookup.modpack import manifest_hash
        item = {'name': 'example.jar', 'size': 3, 'sha256': 'a' * 64}
        endpoint = TunnelClient(self.profile(), RoomInvite.create())
        endpoint.session = 'session'
        endpoint._routes = SimpleNamespace(request=AsyncMock(side_effect=ConnectionError('Mod forwarding unavailable')))
        endpoint.room_info = {'game': {'mods_count': 1, 'mods_hash': manifest_hash([item]), 'mods': [item]}}
        with patch('hookup.native_transport.asyncio.sleep', new=AsyncMock()):
            self.assertEqual(await endpoint.mod_manifest(), [item])
        self.assertEqual(endpoint._routes.request.await_count, 2)
        endpoint.room_info['game']['mods_count'] = 2
        with patch('hookup.native_transport.asyncio.sleep', new=AsyncMock()):
            with self.assertRaisesRegex(ConnectionError, '请房主重新创建房间') as error:
                await endpoint.mod_manifest()
        self.assertNotIn('Mod forwarding unavailable', str(error.exception))

    async def test_mod_downloads_respect_native_transfer_limit_and_retry_busy_host(self):
        endpoint = TunnelClient(self.profile(), RoomInvite.create())
        endpoint.session = 'session'
        endpoint._transport = 'p2p'
        active = peak = 0
        serial = 0
        async def request(method, _params):
            nonlocal active, peak, serial
            if method == 'mods.fetch':
                serial += 1
                active += 1
                peak = max(peak, active)
                await asyncio.sleep(.01)
                return {'transfer': str(serial), 'state': 'complete'}
            self.assertEqual(method, 'mods.cancel')
            await asyncio.sleep(.01)
            active -= 1
            return {'cancelled': True}
        endpoint._routes = SimpleNamespace(request=AsyncMock(side_effect=request))
        await asyncio.gather(*(endpoint.download_mod({'name': str(i) + '.jar'}, str(i), None,
                                                     lambda *_: None) for i in range(36)))
        self.assertEqual(active, 0)
        self.assertEqual(peak, 12)

        endpoint._routes.request = AsyncMock(side_effect=[
            ConnectionError('Mod transfer limit reached'),
            {'transfer': 'done', 'state': 'complete'}, {'cancelled': True}])
        with patch('hookup.native_transport.asyncio.sleep', new=AsyncMock()):
            await endpoint.download_mod({'name': 'later.jar'}, 'later.jar', None, lambda *_: None)
        self.assertEqual(endpoint._routes.request.await_count, 3)

    async def test_process_loss_is_reported_and_does_not_fake_a_reconnect(self):
        routes = SimpleNamespace(handle=AsyncMock(return_value='node'), request=AsyncMock(side_effect=[
            {'session': 'native-session', 'address': '127.0.0.1:12345'}, ConnectionError('gone')]))
        endpoint = TunnelClient(self.profile(), RoomInvite.create())
        states = []
        endpoint.on_status = lambda state, reason: states.append(state)
        with patch('hookup.native_transport.manager', return_value=routes):
            await endpoint.run()
        self.assertEqual(states, ['online', 'error'])
        self.assertIsNone(endpoint.connection)
