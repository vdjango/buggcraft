"""Temporary world loss, network grace and terminal room closure are distinct."""
import asyncio
import unittest
from unittest.mock import patch

import test_game_status as status_fixture

if __package__:
    from . import test_room_chat as fixture
else:
    import test_room_chat as fixture
from hookup.relay import TunnelHost, TunnelClient
from hookup.rooms import discover_local_worlds, request


class RoomLifecycleTests(unittest.IsolatedAsyncioTestCase):
    # Reuse the isolated encrypted relay fixture, not its test methods.
    asyncSetUp = fixture.RoomChatTests.asyncSetUp
    asyncTearDown = fixture.RoomChatTests.asyncTearDown
    wait = fixture.RoomChatTests.wait
    endpoint = fixture.RoomChatTests.endpoint

    async def test_world_temporarily_unavailable_keeps_chat_and_recovers(self):
        async def echo(reader, writer):
            try:
                while data := await reader.read(4096):
                    writer.write(data)
                    await writer.drain()
            except ConnectionError:
                pass  # Status probes may close without consuming echoed packets.
            finally:
                writer.close()
        world = await asyncio.start_server(echo, '127.0.0.1', 0)
        port = world.sockets[0].getsockname()[1]
        host = TunnelHost(self.profile, game_port=port, announce=False)
        self.endpoints.append(host)
        self.events[host] = []
        host.on_chat = self.events[host].append
        self.tasks.append(asyncio.create_task(host.run()))
        await self.wait(lambda: host.chat_process is not None)
        client = await self.endpoint(TunnelClient, host.invite)
        try:
            await self.wait(lambda: client.room_state == 'ready')
            world.close()
            await world.wait_closed()
            await self.wait(lambda: client.room_state == 'waiting')
            self.assertFalse(client._stopped)
            await client.send_chat('等待房主，聊天仍然可用')
            await self.wait(lambda: any(e.get('text') == '等待房主，聊天仍然可用' for e in self.events[host]))
            world = await asyncio.start_server(echo, '127.0.0.1', port)
            await self.wait(lambda: client.room_state == 'ready')
            reader, writer = await asyncio.open_connection('127.0.0.1', client.listen_port)
            writer.write(b'recovered')
            await writer.drain()
            self.assertEqual(await asyncio.wait_for(reader.readexactly(9), 5), b'recovered')
            writer.close()
            await writer.wait_closed()
        finally:
            world.close()
            await world.wait_closed()

    async def test_explicit_close_notifies_three_clients_and_stops_retries(self):
        host = await self.endpoint(TunnelHost)
        clients = [await self.endpoint(TunnelClient, host.invite) for _ in range(3)]
        # A client cannot end somebody else's room.
        with self.assertRaises(ConnectionError):
            await request(clients[0].connection, 'close')
        await host.stop()
        await self.wait(lambda: all(p._stopped for p in clients))
        self.assertNotIn(host.invite.room_id, self.relay.rooms)
        for client in clients:
            self.assertTrue(any(e.get('state') == 'closed' for e in self.events[client]))
        await asyncio.sleep(.15)
        self.assertTrue(all(p.connection is None for p in clients))

    async def test_close_is_detected_during_chat_channel_outage(self):
        host = await self.endpoint(TunnelHost)
        client = await self.endpoint(TunnelClient, host.invite)
        client.chat_task.cancel()
        await asyncio.gather(client.chat_task, return_exceptions=True)
        await host.stop()
        await self.wait(lambda: client._stopped)
        self.assertEqual(client.room_state, 'closed')

    async def test_host_network_loss_preserves_room_until_grace_expires(self):
        host = await self.endpoint(TunnelHost)
        client = await self.endpoint(TunnelClient, host.invite)
        self.relay.host_grace_seconds = .4
        host._stopped = True  # Simulate losing the host without an explicit close request.
        host.connection.close()
        await self.wait(lambda: client.room_state == 'waiting')
        self.assertIn(host.invite.room_id, self.relay.rooms)
        await self.wait(lambda: client._stopped)
        self.assertNotIn(host.invite.room_id, self.relay.rooms)

    async def test_reselect_world_changes_forward_target_without_changing_invite(self):
        async def echo(reader, writer):
            try:
                data = await reader.read(64)
                writer.write(b'new-world:' + data)
                await writer.drain()
            finally:
                writer.close()
        world = await asyncio.start_server(echo, '127.0.0.1', 0)
        self.addAsyncCleanup(world.wait_closed)
        self.addCleanup(world.close)
        port = world.sockets[0].getsockname()[1]
        host = await self.endpoint(TunnelHost)
        client = await self.endpoint(TunnelClient, host.invite)
        old_invite = host.invite.encode()
        with patch('hookup.relay.game_status', return_value={'protocol':772, 'port':port}):
            await host.retarget_world(port)
        reader, writer = await asyncio.open_connection('127.0.0.1', client.listen_port)
        writer.write(b'hello')
        await writer.drain()
        self.assertEqual(await asyncio.wait_for(reader.read(), 5), b'new-world:hello')
        writer.close()
        await writer.wait_closed()
        self.assertEqual(host.invite.encode(), old_invite)

    async def test_disconnected_client_detects_terminal_room_before_retrying(self):
        host = await self.endpoint(TunnelHost)
        client = await self.endpoint(TunnelClient, host.invite)
        client.connection.abort()
        await host.stop()
        await self.wait(lambda: client._stopped)
        self.assertEqual(client.room_state, 'closed')

    async def test_waiting_room_becomes_ready_after_detecting_unadvertised_world(self):
        port = await status_fixture.GameStatusTests.server(self)
        host = await self.endpoint(TunnelHost, game_port=0, room_settings={
            'title': 'Game opened later', 'public': False, 'capacity': 10,
            'game': {'version': '1.21.8', 'protocol': 772, 'loader': 'vanilla'}})
        client = await self.endpoint(TunnelClient, host.invite)
        await self.wait(lambda: client.room_state == 'waiting')
        original_invite = host.invite.encode()
        with patch('hookup.rooms._advertised_world_ports', return_value=set()), \
                patch('hookup.rooms._java_listening_ports', return_value={port}):
            worlds = await discover_local_worlds(seconds=0)
        self.assertEqual([world['port'] for world in worlds], [port])
        await host.retarget_world(worlds[0]['port'])
        await self.wait(lambda: client.room_state == 'ready')
        self.assertEqual(host.game_port, port)
        self.assertEqual(host.invite.encode(), original_invite)
        await client.send_chat('world discovered, room still connected')
        await self.wait(lambda: any(event.get('text') == 'world discovered, room still connected'
                                   for event in self.events[host]))


if __name__ == '__main__':
    unittest.main()
