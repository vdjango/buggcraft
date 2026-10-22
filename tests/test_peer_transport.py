"""Real encrypted peer sockets, relay fallback, stream EOF and room boundaries."""
import asyncio
import secrets
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
