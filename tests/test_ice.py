"""Address policy preserves reachable peers without publishing invalid IPs."""
import asyncio
import socket
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/buggcraft'))
from aioice import Candidate
from hookup.ice import Connection, stun_route, usable_addresses


class IceAddressTests(unittest.TestCase):
    def test_down_and_link_local_addresses_are_excluded_but_up_virtual_paths_remain(self):
        stats = {name: SimpleNamespace(isup=up) for name, up in (
            ('WLAN', True), ('VMware VMnet1', True), ('VPN', False))}
        addresses = {
            'WLAN': [SimpleNamespace(address='192.168.2.6'),
                     SimpleNamespace(address='2001:db8::6')],
            'VMware VMnet1': [SimpleNamespace(address='192.168.8.1')],
            'VPN': [SimpleNamespace(address='18.11.10.1')],
        }
        with patch('hookup.ice.psutil.net_if_stats', return_value=stats), \
                patch('hookup.ice.psutil.net_if_addrs', return_value=addresses):
            self.assertEqual(usable_addresses([
                '18.11.10.1', '169.254.68.115', '127.0.0.1', '::1',
                'fe80::1', '0.0.0.0', '224.0.0.1', '192.168.8.1',
                '192.168.2.6', '2001:db8::6', '10.1.2.3']),
                ['192.168.8.1', '192.168.2.6', '2001:db8::6', '10.1.2.3'])

    def test_missing_interface_status_keeps_valid_addresses(self):
        with patch('hookup.ice.psutil.net_if_stats', side_effect=OSError('Unavailable')):
            self.assertEqual(usable_addresses(['192.168.2.6', '169.254.1.1', '2001:db8::6']),
                             ['192.168.2.6', '2001:db8::6'])

    def test_shared_address_is_kept_if_any_interface_is_up(self):
        entries = [SimpleNamespace(address='10.1.2.3', family=socket.AF_INET)]
        with patch('hookup.ice.psutil.net_if_stats', return_value={
                'old': SimpleNamespace(isup=False), 'new': SimpleNamespace(isup=True)}), \
                patch('hookup.ice.psutil.net_if_addrs', return_value={'old': entries, 'new': entries}):
            self.assertEqual(usable_addresses(['10.1.2.3']), ['10.1.2.3'])


class IceGatheringTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Loopback aliases model two independently bound interfaces with real
        # UDP sockets; address validation is exercised separately above.
        policy = patch('hookup.ice.usable_addresses', side_effect=list)
        policy.start()
        self.addCleanup(policy.stop)
        priority = patch('hookup.ice.PRIMARY_STUN_WAIT', .02)
        priority.start()
        self.addCleanup(priority.stop)
        self.connection = Connection(False, stun_server=('127.0.0.1', 9))
        self.addresses = ['127.0.0.1', '127.0.0.2']

    async def asyncTearDown(self):
        await asyncio.wait_for(self.connection.close(), 2)

    def mapping(self, protocol):
        local = protocol.local_candidate
        return Candidate('mapped', local.component, 'udp', 1, '198.51.100.1', local.port,
                         'srflx', related_address=local.host, related_port=local.port), None

    async def gather(self, timeout=.3):
        return await self.connection.get_component_candidates(1, self.addresses, timeout=timeout)

    def assert_hosts(self, candidates):
        self.assertEqual([c.host for c in candidates if c.type == 'host'], self.addresses)

    async def test_working_route_only_probes_primary_and_keeps_other_lan_candidates(self):
        with patch('hookup.ice.stun_route', new=AsyncMock(return_value=(('127.0.0.1', 9), '127.0.0.1'))), \
                patch('hookup.ice.server_reflexive_candidate', new=AsyncMock(side_effect=lambda p, s: self.mapping(p))) as query, \
                self.assertLogs('hookup.ice', level='INFO') as logs:
            candidates = await self.gather()
        self.assert_hosts(candidates)
        self.assertEqual(query.await_count, 1)
        self.assertEqual(query.await_args.args[0].local_candidate.host, '127.0.0.1')
        self.assertEqual(len([c for c in candidates if c.type == 'srflx']), 1)
        self.assertTrue(any('policy=route-first' in line for line in logs.output))

    async def test_primary_error_probes_other_interface_and_keeps_every_host(self):
        probed = []
        async def query(protocol, server):
            probed.append(protocol.local_candidate.host)
            if protocol.local_candidate.host == '127.0.0.1':
                raise OSError('Route changed')
            return self.mapping(protocol)
        with patch('hookup.ice.stun_route', new=AsyncMock(return_value=(('127.0.0.1', 9), '127.0.0.1'))), \
                patch('hookup.ice.server_reflexive_candidate', new=query), \
                self.assertLogs('hookup.ice', level='INFO') as logs:
            candidates = await self.gather()
        self.assert_hosts(candidates)
        self.assertEqual(probed, self.addresses)
        self.assertEqual(candidates[-1].related_address, '127.0.0.2')
        self.assertTrue(any('reason=primary-failed' in line for line in logs.output))

    async def test_slow_primary_does_not_hold_up_other_interface_and_is_reaped(self):
        cancelled = asyncio.Event()
        async def query(protocol, server):
            if protocol.local_candidate.host == '127.0.0.1':
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()
            return self.mapping(protocol)
        with patch('hookup.ice.stun_route', new=AsyncMock(return_value=(('127.0.0.1', 9), '127.0.0.1'))), \
                patch('hookup.ice.server_reflexive_candidate', new=query), \
                self.assertLogs('hookup.ice', level='INFO') as logs:
            candidates = await self.gather()
        self.assert_hosts(candidates)
        self.assertTrue(cancelled.is_set())
        self.assertEqual(candidates[-1].related_address, '127.0.0.2')
        self.assertTrue(any('reason=primary-slow' in line for line in logs.output))
        self.assertTrue(any('reason=mapping-found' in line for line in logs.output))

    async def test_unknown_or_unbound_route_tries_all_interfaces(self):
        for result in (OSError('No route information'), (('127.0.0.1', 9), '127.0.0.3')):
            with self.subTest(route=result):
                route = AsyncMock(side_effect=result) if isinstance(result, OSError) else AsyncMock(return_value=result)
                with patch('hookup.ice.stun_route', new=route), \
                        patch('hookup.ice.server_reflexive_candidate', new=AsyncMock(side_effect=lambda p, s: self.mapping(p))) as query, \
                        self.assertLogs('hookup.ice', level='INFO') as logs:
                    candidates = await self.gather()
                self.assert_hosts(candidates)
                self.assertEqual(query.await_count, 2)
                self.assertTrue(any('result=fallback-all' in line for line in logs.output))

    async def test_slow_primary_can_still_succeed_after_fallback_starts(self):
        fallback_started, fallback_cancelled = asyncio.Event(), asyncio.Event()
        async def query(protocol, server):
            if protocol.local_candidate.host == '127.0.0.1':
                await fallback_started.wait()
                return self.mapping(protocol)
            fallback_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                fallback_cancelled.set()
        with patch('hookup.ice.stun_route', new=AsyncMock(return_value=(('127.0.0.1', 9), '127.0.0.1'))), \
                patch('hookup.ice.server_reflexive_candidate', new=query):
            candidates = await self.gather()
        self.assert_hosts(candidates)
        self.assertEqual(candidates[-1].related_address, '127.0.0.1')
        self.assertTrue(fallback_cancelled.is_set())

    async def test_interface_lost_during_bind_does_not_discard_other_candidates(self):
        self.addresses = ['192.0.2.254', '127.0.0.1']
        self.connection.stun_server = None
        with self.assertLogs('hookup.ice', level='INFO') as logs:
            candidates = await self.gather()
        self.assertEqual([c.host for c in candidates], ['127.0.0.1'])
        self.assertTrue(any('ice_host_bind' in line and '192.0.2.254' in line for line in logs.output))

    async def test_no_usable_socket_reports_failure_without_waiting_for_stun(self):
        self.addresses = ['192.0.2.254']
        with self.assertLogs('hookup.ice', level='INFO') as logs, \
                patch('hookup.ice.stun_route', new=AsyncMock()) as route:
            with self.assertRaisesRegex(ConnectionError, 'No usable ICE sockets'):
                await self.gather()
        route.assert_not_called()
        self.assertFalse(self.connection._protocols)
        self.assertTrue(any('result=gather-failed' in line for line in logs.output))

    async def blackhole(self):
        class Blackhole(asyncio.DatagramProtocol):
            def __init__(self):
                self.sources = set()

            def datagram_received(self, data, address):
                self.sources.add(address[0])

        transport, server = await asyncio.get_running_loop().create_datagram_endpoint(
            Blackhole, local_addr=('127.0.0.1', 0))
        self.addCleanup(transport.close)
        self.connection.stun_server = ('127.0.0.1', transport.get_extra_info('sockname')[1])
        return server

    async def test_all_stun_blocked_retains_lan_candidates_and_cleans_transactions(self):
        server = await self.blackhole()
        with self.assertLogs('hookup.ice', level='INFO') as logs:
            candidates = await self.gather(timeout=.15)
        self.assert_hosts(candidates)
        self.assertEqual(len(candidates), 2)
        self.assertEqual(server.sources, set(self.addresses))
        self.assertTrue(all(not p.transactions for p in self.connection._protocols))
        self.assertTrue(any('result=stun-timeout' in line for line in logs.output))

    async def test_cancelling_gather_reaps_stun_transactions_and_closes_every_socket(self):
        server = await self.blackhole()
        task = asyncio.create_task(self.gather(timeout=1))
        async with asyncio.timeout(1):
            while not server.sources:
                await asyncio.sleep(.005)
        protocols = list(self.connection._protocols)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(all(not p.transactions for p in protocols))
        await self.connection.close()
        self.assertFalse(self.connection._protocols)
        self.assertTrue(all(p.transport.is_closing() for p in protocols))

    async def test_route_lookup_hang_stays_within_gather_budget_and_keeps_hosts(self):
        cancelled = asyncio.Event()
        async def route(server):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        with patch('hookup.ice.stun_route', new=route):
            candidates = await asyncio.wait_for(self.gather(timeout=.03), .5)
        self.assert_hosts(candidates)
        self.assertTrue(cancelled.is_set())

    async def test_no_stun_uses_lan_without_route_lookup(self):
        self.connection.stun_server = None
        with patch('hookup.ice.stun_route', new=AsyncMock()) as route:
            candidates = await self.gather()
        self.assert_hosts(candidates)
        route.assert_not_called()

    @unittest.skipUnless(socket.has_ipv6, 'IPv6 sockets unavailable')
    async def test_ipv6_hosts_remain_available_without_ipv4_stun(self):
        self.addresses = ['::1']
        with patch('hookup.ice.stun_route', new=AsyncMock()) as route:
            candidates = await self.gather()
        self.assert_hosts(candidates)
        route.assert_not_called()

    async def test_os_route_lookup_pins_resolved_target_without_transmitting(self):
        target, source = await stun_route(('localhost', 3478))
        self.assertEqual(target, ('127.0.0.1', 3478))
        self.assertEqual(source, '127.0.0.1')
