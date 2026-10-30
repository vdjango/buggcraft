"""Guard the launcher boundary: Python only controls the native subprocess."""
import ast
import asyncio
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src' / 'buggcraft'))
from hookup.native_transport import TunnelClient, TunnelHost
from hookup.profiles import RelayProfile, RoomInvite


class NativeBoundaryTests(unittest.TestCase):
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
        with patch('hookup.native_transport.manager', return_value=routes):
            await endpoint.run()
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
