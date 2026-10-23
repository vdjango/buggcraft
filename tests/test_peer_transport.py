"""Real encrypted peer sockets, relay fallback, stream EOF and room boundaries."""
import asyncio
import secrets
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from . import test_room_chat as fixture
from hookup.relay import TunnelClient, TunnelHost


class PeerTransportTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixture.RoomChatTests.asyncSetUp
    asyncTearDown = fixture.RoomChatTests.asyncTearDown
    wait = fixture.RoomChatTests.wait
    endpoint = fixture.RoomChatTests.endpoint

    async def exchange(self, client, size=131072):
        payload = secrets.token_bytes(size)
        reader, writer = await asyncio.open_connection('127.0.0.1', client.listen_port)
        try:
            async def send():
                writer.write(payload)
                await writer.drain()
                writer.write_eof()
            sender = asyncio.create_task(send())
            actual = await asyncio.wait_for(reader.readexactly(len(payload)), 30)
            await sender
            self.assertEqual(actual, payload)
            self.assertEqual(await asyncio.wait_for(reader.read(), 5), b'')
        finally:
            writer.close()
            await writer.wait_closed()

    async def world(self):
        async def echo(reader, writer):
            try:
                while data := await reader.read(32768):
                    writer.write(data)
                    await writer.drain()
                if writer.can_write_eof():
                    writer.write_eof()
            except (OSError, asyncio.CancelledError):
                pass
            finally:
                writer.close()
                try:
                    await writer.wait_closed()
                except OSError:
                    pass  # Status probes close before consuming the echo.
        server = await asyncio.start_server(echo, '127.0.0.1', 0)
        self.addAsyncCleanup(server.wait_closed)
        self.addCleanup(server.close)
        return server.sockets[0].getsockname()[1]

    async def test_direct_transfers_megabytes_and_parallel_streams_without_relay_bytes(self):
        host = await self.endpoint(TunnelHost, game_port=await self.world())
        client = await self.endpoint(TunnelClient, host.invite)
        self.assertEqual(client.transport_state, 'p2p')
        # Polling game status may use the path too; no game forward can open
        # on the relay while these real transfers are in progress.
        with patch('tunnel.relay.RoomPeer.connection_requested', side_effect=AssertionError('Relay used')):
            await asyncio.gather(self.exchange(client, 2 * 1024 * 1024), self.exchange(client))
        pc = client.peer_transport.client_pc
        listener = client.listener
        await asyncio.gather(client.stop(), host.stop())
        self.assertEqual(pc.connectionState, 'closed')
        self.assertIsNone(client.peer_transport)
        self.assertIsNone(client.listener)
        self.assertFalse(listener.server.is_serving())

    async def test_opt_out_host_uses_relay_without_peer_address_exchange(self):
        host = await self.endpoint(TunnelHost, game_port=await self.world(), transport_policy='relay')
        client = await self.endpoint(TunnelClient, host.invite)
        self.assertEqual(client.transport_state, 'relay')
        await self.exchange(client)

    @patch('hookup.relay.game_status', new_callable=AsyncMock,
           side_effect=ConnectionError('No background game-status stream'))
    async def test_short_streams_never_reuse_ids_while_resets_are_in_flight(self, status):
        host = await self.endpoint(TunnelHost, game_port=await self.world())
        client = await self.endpoint(TunnelClient, host.invite)
        pc = client.peer_transport.client_pc
        original = pc.createDataChannel
        ids = []
        def record(*args, **kwargs):
            channel = original(*args, **kwargs)
            ids.append(channel.id)
            return channel
        with patch.object(pc, 'createDataChannel', side_effect=record):
            for _ in range(10):
                await asyncio.gather(*(self.exchange(client, 4096) for _ in range(3)))
        self.assertEqual(len(ids), 30)
        self.assertEqual(len(set(ids)), 30)
        self.assertTrue(all(value % 2 == 1 and value > 1 for value in ids))
        self.assertEqual(ids, sorted(ids))
        await self.exchange(client, 2 * 1024 * 1024)

    async def test_exhausted_peer_stream_ids_relay_new_streams(self):
        host = await self.endpoint(TunnelHost, game_port=await self.world())
        client = await self.endpoint(TunnelClient, host.invite)
        client.peer_transport.next_game_channel_id = 65535
        with patch.object(client.peer_transport.client_pc, 'createDataChannel',
                          side_effect=AssertionError('Stream ID reused')):
            await self.exchange(client, 65536)
        self.assertEqual(client.transport_state, 'relay')

    async def test_one_room_mixes_p2p_and_relay_per_visitor(self):
        """A relay-only visitor must not force other room members off P2P."""
        host = await self.endpoint(TunnelHost, game_port=await self.world())
        direct = await self.endpoint(TunnelClient, host.invite)
        relayed = await self.endpoint(TunnelClient, host.invite, transport_policy='relay')
        from hookup.peer import PeerTransport
        with patch.object(PeerTransport, 'create_pc', side_effect=OSError('UDP blocked')):
            fallback = await self.endpoint(TunnelClient, host.invite)
        self.assertEqual(direct.transport_state, 'p2p')
        self.assertEqual(relayed.transport_state, 'relay')
        self.assertEqual(fallback.transport_state, 'relay')
        # Stop status probes so byte accounting measures just game payloads.
        for endpoint in (host, direct, relayed, fallback):
            endpoint.room_task.cancel()
            await asyncio.gather(endpoint.room_task, return_exceptions=True)
        before = self.relay.capacity.bytes
        await self.exchange(direct)
        self.assertEqual(self.relay.capacity.bytes, before)

        from tunnel.relay import RoomPeer
        original = RoomPeer.connection_requested
        observed = []
        async def record_relay(peer, *args):
            observed.append((bool(getattr(peer, 'peer_signal', None)), args[1]))
            return await original(peer, *args)

        with patch.object(RoomPeer, 'connection_requested', new=record_relay):
            await asyncio.gather(self.exchange(direct), self.exchange(relayed), self.exchange(fallback))

        self.assertTrue(any(port == 25565 for _, port in observed))
        self.assertFalse(any(signaled for signaled, _ in observed))
        self.assertGreaterEqual(self.relay.capacity.bytes - before, 4 * 131072)
        self.assertEqual(direct.transport_state, 'p2p')
        self.assertEqual(relayed.transport_state, 'relay')
        await self.exchange(direct, 65536)

    async def test_failed_ice_automatically_uses_relay(self):
        host = await self.endpoint(TunnelHost, game_port=await self.world())
        from hookup.peer import PeerTransport
        with patch.object(PeerTransport, 'create_pc', side_effect=OSError('UDP blocked')):
            client = await self.endpoint(TunnelClient, host.invite)
        self.assertEqual(client.transport_state, 'relay')
        await self.exchange(client)

    async def test_explicit_ice_failure_immediately_falls_back_and_transfers_over_relay(self):
        from hookup.ice import Connection
        host = await self.endpoint(TunnelHost, game_port=await self.world())
        # Real SDP/signaling and local forwarding; connectivity checks report
        # failure instead of waiting for the whole 15-second peer budget.
        with patch.object(Connection, 'connect', new=AsyncMock(side_effect=ConnectionError('UDP denied'))), \
                self.assertLogs('hookup.relay', level='WARNING') as logs:
            client = await asyncio.wait_for(self.endpoint(TunnelClient, host.invite), 5)
        self.assertEqual(client.transport_state, 'relay')
        self.assertTrue(any('reason=ConnectionError stage=ice-connect' in line for line in logs.output))
        await self.exchange(client)

    async def test_unavailable_signal_immediately_falls_back_without_waiting_for_answer(self):
        from hookup.peer import PeerTransport
        host = await self.endpoint(TunnelHost, game_port=await self.world())
        original = PeerTransport.send
        def unavailable(peer, message):
            if message.get('type') == 'answer':
                target = next(p for p in self.relay.peers if p.role == 'client' and p.peer_signal)
                target.peer_signal.send({'type': 'unavailable'})
            else:
                original(peer, message)
        with patch.object(PeerTransport, 'send', new=unavailable), \
                self.assertLogs('hookup.relay', level='WARNING') as logs:
            client = await asyncio.wait_for(self.endpoint(TunnelClient, host.invite), 5)
        self.assertEqual(client.transport_state, 'relay')
        self.assertTrue(any('stage=host-unavailable' in line for line in logs.output))
        await self.exchange(client)

    async def test_closed_signal_immediately_falls_back_while_ssh_stays_usable(self):
        from hookup.peer import PeerTransport
        host = await self.endpoint(TunnelHost, game_port=await self.world())
        original = PeerTransport.send
        def close_signal(peer, message):
            if message.get('type') == 'answer':
                target = next(p for p in self.relay.peers if p.role == 'client' and p.peer_signal)
                target.peer_signal.close()
            else:
                original(peer, message)
        with patch.object(PeerTransport, 'send', new=close_signal), \
                self.assertLogs('hookup', level='WARNING') as logs:
            client = await asyncio.wait_for(self.endpoint(TunnelClient, host.invite), 5)
        self.assertEqual(client.transport_state, 'relay')
        self.assertTrue(any('peer_signal_failed' in line for line in logs.output))
        self.assertTrue(any('peer_fallback' in line and 'stage=waiting-answer' in line for line in logs.output))
        await self.exchange(client)

    async def test_leaving_during_answer_cancels_host_work_and_keeps_room_usable(self):
        from hookup.peer import PeerTransport
        host = await self.endpoint(TunnelHost, game_port=await self.world())
        started, cancelled = asyncio.Event(), asyncio.Event()
        async def pending_answer(peer, message):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        with patch.object(PeerTransport, 'answer', new=pending_answer):
            client = TunnelClient(self.profile, host.invite, listen_port=0, announce=False)
            self.endpoints.append(client)
            self.tasks.append(asyncio.create_task(client.run()))
            await asyncio.wait_for(started.wait(), 3)
            await client.stop()
            await asyncio.wait_for(cancelled.wait(), 1)
        await self.wait(lambda: not host.peer_transport.answer_jobs, timeout=1)
        visitor = await self.endpoint(TunnelClient, host.invite)
        self.assertEqual(visitor.transport_state, 'p2p')
        await self.exchange(visitor, 65536)

    async def test_slow_stun_gathering_does_not_cancel_negotiation(self):
        """Unanswered adapter probes take 5s on each side, before ICE starts."""
        from hookup.peer import PeerTransport
        from aioice.ice import get_host_addresses
        from hookup.ice import usable_addresses

        class Blackhole(asyncio.DatagramProtocol):
            packets = 0

            def datagram_received(self, data, address):
                self.packets += 1

        loop = asyncio.get_running_loop()
        transport, server = await loop.create_datagram_endpoint(
            Blackhole, local_addr=('0.0.0.0', 0))
        self.addCleanup(transport.close)
        address = usable_addresses(get_host_addresses(True, False))[-1]
        profile = SimpleNamespace(server_host=address,
                                  server_port=transport.get_extra_info('sockname')[1])

        async def select_stun(peer):
            peer.stun_profile = profile

        with patch.object(PeerTransport, 'select_stun', new=select_stun):
            host = await self.endpoint(TunnelHost, game_port=await self.world())
            client = TunnelClient(self.profile, host.invite, listen_port=0, announce=False)
            self.endpoints.append(client)
            self.tasks.append(asyncio.create_task(client.run()))
            await self.wait(lambda: client.listener is not None, timeout=20)

        self.assertEqual(client.transport_state, 'p2p')
        self.assertGreater(server.packets, 0)
        with patch('tunnel.relay.RoomPeer.connection_requested', side_effect=AssertionError('Relay used')):
            await self.exchange(client)

    async def test_unanswered_negotiation_times_out_to_relay_without_harming_direct_visitor(self):
        host = await self.endpoint(TunnelHost, game_port=await self.world())
        direct = await self.endpoint(TunnelClient, host.invite)
        from hookup.peer import PeerTransport
        original = PeerTransport.send
        def drop_offer(peer, message):
            if message.get('type') != 'offer':
                original(peer, message)
        # Simulate a signaling path which never returns an ICE answer.
        with patch.object(PeerTransport, 'send', new=drop_offer):
            fallback = await self.endpoint(TunnelClient, host.invite, peer_timeout=.5)
        self.assertEqual(fallback.transport_state, 'relay')
        self.assertEqual(direct.transport_state, 'p2p')
        await asyncio.gather(self.exchange(direct, 65536), self.exchange(fallback, 65536))

    async def test_direct_path_failure_keeps_local_port_and_relays_next_stream(self):
        host = await self.endpoint(TunnelHost, game_port=await self.world())
        client = await self.endpoint(TunnelClient, host.invite)
        self.assertEqual(client.transport_state, 'p2p')
        port = client.listen_port
        await client.peer_transport.client_pc.close()
        self.assertEqual(client.transport_state, 'relay')
        await self.exchange(client)
        self.assertEqual(client.listen_port, port)
