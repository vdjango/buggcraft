"""Find the local game even when Windows does not deliver its LAN multicast."""
import asyncio
import socket
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import psutil

from hookup import rooms
import test_game_status as status_fixture


class LocalWorldDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    server = status_fixture.GameStatusTests.server

    async def test_real_status_detected_without_any_multicast_advertisement(self):
        port = await self.server()
        with patch.object(rooms, '_advertised_world_ports', AsyncMock(return_value=set())), \
                patch.object(rooms, '_java_listening_ports', return_value={port}):
            worlds = await rooms.discover_local_worlds(seconds=0)
        self.assertEqual([world['port'] for world in worlds], [port])
        self.assertEqual(worlds[0]['protocol'], 772)
        self.assertEqual(worlds[0]['players']['online'], 7)

    async def test_udp_unavailable_still_finds_local_game_and_logs_reason(self):
        port = await self.server()
        original_socket = socket.socket
        def socket_factory(family=socket.AF_INET, kind=socket.SOCK_STREAM, *args, **kwargs):
            if kind == socket.SOCK_DGRAM:
                raise OSError('test: multicast listener unavailable')
            return original_socket(family, kind, *args, **kwargs)
        socket_module = SimpleNamespace(**vars(socket))
        socket_module.socket = socket_factory
        with patch.object(rooms, 'socket', socket_module), \
                patch.object(rooms, '_java_listening_ports', return_value={port}), \
                self.assertLogs('hookup.rooms', level='INFO') as logs:
            worlds = await rooms.discover_local_worlds(seconds=0)
        self.assertEqual([world['port'] for world in worlds], [port])
        self.assertTrue(any('multicast_unavailable' in message for message in logs.output))
        self.assertTrue(any('discovery_world' in message for message in logs.output))

    async def test_combines_sources_without_probing_client_relay_or_duplicate_ports(self):
        async def status(port):
            return {'port': port, 'version': '1.21.8', 'protocol': 772}
        with patch.object(rooms, '_advertised_world_ports', AsyncMock(return_value={23456, 34567})), \
                patch.object(rooms, '_java_listening_ports', return_value={34567, 45678}), \
                patch.object(rooms, 'game_status', side_effect=status) as probe:
            worlds = await rooms.discover_local_worlds(excluded_ports=[23456, 45678], seconds=0)
        self.assertEqual([world['port'] for world in worlds], [34567])
        probe.assert_awaited_once_with(34567)

    async def test_unrelated_java_service_does_not_hide_valid_world(self):
        async def status(port):
            if port == 23456:
                raise ValueError('Not Minecraft')
            return {'port': port, 'version': '1.21.8', 'protocol': 772}
        with patch.object(rooms, '_advertised_world_ports', AsyncMock(return_value=set())), \
                patch.object(rooms, '_java_listening_ports', return_value={23456, 34567}), \
                patch.object(rooms, 'game_status', side_effect=status):
            worlds = await rooms.discover_local_worlds(seconds=0)
        self.assertEqual([world['port'] for world in worlds], [34567])

    async def test_unavailable_process_inspection_preserves_multicast_discovery(self):
        with patch.object(rooms, '_advertised_world_ports', AsyncMock(return_value={34567})), \
                patch.object(rooms, '_java_listening_ports', side_effect=PermissionError), \
                patch.object(rooms, 'game_status', AsyncMock(return_value={'port': 34567})):
            worlds = await rooms.discover_local_worlds(seconds=0)
        self.assertEqual(worlds, [{'port': 34567}])

    async def test_cancelled_multicast_closes_socket(self):
        listener = Mock()
        loop = asyncio.get_running_loop()
        socket_module = SimpleNamespace(**vars(socket))
        socket_module.socket = Mock(return_value=listener)
        with patch.object(rooms, 'socket', socket_module), \
                patch.object(loop, 'sock_recvfrom', AsyncMock(side_effect=asyncio.CancelledError)):
            with self.assertRaises(asyncio.CancelledError):
                await rooms._advertised_world_ports(set(), 3)
        listener.close.assert_called_once_with()


class JavaListenerTests(unittest.TestCase):
    def test_reads_only_java_listening_ports_and_survives_denied_process(self):
        def process(name, ports):
            item = Mock(info={'name': name}, pid=1)
            item.net_connections.return_value = ports
            return item
        def connection(port, state):
            return SimpleNamespace(status=state, laddr=SimpleNamespace(port=port))
        unrelated = process('python.exe', [connection(11111, psutil.CONN_LISTEN)])
        java = process('javaw.exe', [connection(23456, psutil.CONN_LISTEN),
                                    connection(34567, psutil.CONN_ESTABLISHED)])
        denied = process('java.exe', [])
        denied.net_connections.side_effect = psutil.AccessDenied(1)
        other = process('java', [connection(45678, psutil.CONN_LISTEN)])
        with patch.object(psutil, 'process_iter', return_value=[unrelated, java, denied, other]):
            self.assertEqual(rooms._java_listening_ports(), {23456, 45678})
        unrelated.net_connections.assert_not_called()
        java.cmdline.assert_not_called()


if __name__ == '__main__':
    unittest.main()
