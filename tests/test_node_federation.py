"""Four real SSH relays: discovery, ownership, payloads and recovery."""
import asyncio
import copy
from pathlib import Path
import secrets
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / '.test-tools'), str(ROOT / 'minecraft-tunnel/src'),
               str(ROOT / 'buggcraft/src/buggcraft')]
import asyncssh
from tunnel.relay import RelayServer
from tunnel.relay import Room
from tunnel.federation import Federation, TTL
from hookup.relay import RelayProfile, TunnelHost, TunnelClient
from hookup.nodes import profile_data, remember, encode_code, decode_code, probe, save_json
from hookup.rooms import list_rooms, resolve_room


class FederationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        async def echo(reader, writer):
            try:
                while data := await reader.read(65536):
                    writer.write(data)
                    await writer.drain()
            except ConnectionError:
                # Failure and reconnection tests deliberately reset game sockets.
                pass
            finally:
                writer.close()
                try:
                    await writer.wait_closed()
                except ConnectionError:
                    pass
        self.world = await asyncio.start_server(echo, '127.0.0.1', 0)
        self.game_port = self.world.sockets[0].getsockname()[1]
        self.relays, self.profiles, self.feds = [], [], []
        self.endpoints, self.tasks, self.messages = [], [], {}
        for label in 'ABCD':
            key = asyncssh.generate_private_key('ssh-ed25519')
            relay = await RelayServer('127.0.0.1', 0, host_key=key,
                                      token=secrets.token_urlsafe(48)).start()
            profile = RelayProfile('127.0.0.1', relay.port, relay.token, key.export_public_key().decode())
            fed = Federation(key, profile_data(profile), network_key=secrets.token_urlsafe(48), name=label)
            fed.relay, relay.federation = relay, fed
            self.relays.append(relay)
            self.profiles.append(profile)
            self.feds.append(fed)
        a, b, c, d = self.feds
        b.join(a.invitation())
        a.join(b.invitation())
        c.join(b.invitation())
        b.join(c.invitation())
        d.join(b.invitation())
        await self.sync(3)

    async def asyncTearDown(self):
        await asyncio.gather(*(e.stop() for e in self.endpoints), return_exceptions=True)
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await asyncio.gather(*(f.close() for f in self.feds))
        await asyncio.gather(*(r.close() for r in self.relays))
        self.world.close()
        await self.world.wait_closed()

    async def wait(self, predicate, timeout=10):
        async with asyncio.timeout(timeout):
            while not predicate():
                await asyncio.sleep(.025)

    async def sync(self, rounds=2, active=None):
        for _ in range(rounds):
            await asyncio.gather(*(f.sync_once() for f in (active or self.feds)))

    async def endpoint(self, cls, profile, invite=None, public=False, require_invite=False):
        endpoint = cls(profile, invite, game_port=self.game_port, listen_port=0, announce=False,
                       room_settings={'title': 'Federated world', 'public': public,
                                      'require_invite': require_invite,
                                      'capacity': 8, 'game': {}} if cls is TunnelHost else None)
        messages = []
        endpoint.on_chat = messages.append
        self.messages[endpoint] = messages
        self.endpoints.append(endpoint)
        self.tasks.append(asyncio.create_task(endpoint.run()))
        await self.wait(lambda: any(e.get('type') == 'ready' for e in messages))
        return endpoint

    async def transfer(self, client):
        reader, writer = await asyncio.open_connection('127.0.0.1', client.listen_port)
        try:
            data = secrets.token_bytes(32768)
            writer.write(data)
            await writer.drain()
            self.assertEqual(await asyncio.wait_for(reader.readexactly(len(data)), 5), data)
        finally:
            writer.close()
            await writer.wait_closed()

    async def test_transitive_discovery_and_owner_routes_data_and_chat(self):
        self.assertEqual([len(f.live()) for f in self.feds], [4] * 4)
        host = await self.endpoint(TunnelHost, self.profiles[0], public=True)
        await self.sync()
        for profile in self.profiles:
            rooms = await list_rooms(profile)
            self.assertEqual([r['id'] for r in rooms['rooms']], [host.invite.room_id])
            resolved = await resolve_room(profile, host.invite.room_id)
            self.assertEqual(resolved['secret'], host.invite.secret)
        client = await self.endpoint(TunnelClient, self.profiles[1], host.invite)
        await self.transfer(client)
        self.assertEqual(client._active_profile, self.profiles[0])
        self.assertFalse(self.relays[1].rooms)
        await client.send_chat('Across nodes')
        await self.wait(lambda: any(e.get('text') == 'Across nodes' for e in self.messages[host]))
        # Repeated background gossip must preserve rooms after admission.
        for fed in self.feds:
            fed.task = asyncio.create_task(fed.run())
        for _ in range(4):
            await asyncio.sleep(2)
            listings = await asyncio.gather(*(list_rooms(p) for p in self.profiles))
            self.assertTrue(all(host.invite.room_id in {r['id'] for r in value['rooms']}
                                for value in listings))

    async def test_private_room_is_unlisted_and_invite_routes_from_d(self):
        host = await self.endpoint(TunnelHost, self.profiles[0])
        await self.sync()
        for profile in self.profiles:
            self.assertEqual((await list_rooms(profile))['rooms'], [])
            with self.assertRaises(ConnectionError):
                await resolve_room(profile, host.invite.room_id)
        client = await self.endpoint(TunnelClient, self.profiles[3], host.invite)
        await self.transfer(client)
        serialized = str(self.feds[1].snapshot())
        self.assertNotIn(host.invite.secret, serialized)
        self.assertNotIn('Federated world', serialized)

    async def test_public_protected_room_is_discoverable_without_disclosing_invite(self):
        host = await self.endpoint(TunnelHost, self.profiles[0], public=True, require_invite=True)
        await self.sync()
        for profile in self.profiles:
            listing = (await list_rooms(profile))['rooms']
            self.assertEqual([room['id'] for room in listing], [host.invite.room_id])
            self.assertTrue(listing[0]['require_invite'])
            result = await resolve_room(profile, host.invite.room_id)
            self.assertTrue(result['room']['require_invite'])
            self.assertNotIn('secret', result)
            self.assertNotIn(host.invite.secret, str(result))
        self.assertNotIn(host.invite.secret, str(self.feds[1].snapshot()))
        client = await self.endpoint(TunnelClient, self.profiles[3], host.invite)
        await self.transfer(client)
        await client.send_chat('Invite verified across nodes')
        await self.wait(lambda: any(e.get('text') == 'Invite verified across nodes'
                                   for e in self.messages[host]))

    async def test_cached_entry_fallback_survives_launcher_restart(self):
        host = await self.endpoint(TunnelHost, self.profiles[0], public=True)
        await self.sync()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'node.json'
            save_json(path, profile_data(self.profiles[1]))
            loaded = RelayProfile.load(path)
            await list_rooms(loaded)
            self.assertTrue(Path(str(path) + '.network.json').is_file())
            await self.relays[1].close()
            restarted = RelayProfile.load(path)
            rooms = await asyncio.wait_for(list_rooms(restarted), 4)
            self.assertEqual(rooms['rooms'][0]['id'], host.invite.room_id)
            client = await self.endpoint(TunnelClient, restarted, host.invite)
            await self.transfer(client)

    async def test_owner_failure_recreates_room_and_clients_reconnect(self):
        host = await self.endpoint(TunnelHost, self.profiles[0], public=True)
        await self.sync()
        remember(self.profiles[0], self.feds[0].topology())
        client = await self.endpoint(TunnelClient, self.profiles[1], host.invite)
        await self.transfer(client)
        await self.relays[0].close()
        await self.wait(lambda: host._active_profile != self.profiles[0] and host.connection
                        and not host.connection.is_closed(), 12)
        # Wait for the real signed lease to expire; never refresh the failed owner.
        async with asyncio.timeout(TTL + 15):
            while client._active_profile == self.profiles[0] or not client.connection or client.connection.is_closed():
                await self.sync(1, self.feds[1:])
                await asyncio.sleep(.25)
        await self.wait(lambda: client.chat_process is not None and not client.chat_process.is_closing(), 10)
        await self.transfer(client)
        self.assertEqual(host._active_profile, client._active_profile)

    async def test_forgery_replay_and_untrusted_network_are_rejected(self):
        a, b, _, d = self.feds
        b.publish()
        record = copy.deepcopy(b.records[b.id])
        forged = copy.deepcopy(record)
        forged['body']['name'] = 'forged'
        old = a.records[b.id]
        a.ingest([forged])
        self.assertEqual(a.records[b.id], old)
        a.ingest([record])
        seen = a.seen[b.id]
        a.ingest([record])
        self.assertEqual(a.seen[b.id], seen)
        a.blocked.add(b.id)
        self.assertNotIn(b.id, a.live())
        self.assertFalse(a.accepts(b.id, b.key))
        d.network_key = secrets.token_urlsafe(48)
        d.publish()
        old = a.records[d.id]
        a.ingest([d.records[d.id]])
        self.assertEqual(a.records[d.id], old)

    async def test_player_code_roundtrip_and_host_identity_pin(self):
        profile = decode_code(encode_code(self.profiles[0]))
        self.assertEqual(await probe(profile), self.profiles[0])
        bad = profile_data(profile)
        bad['server_public_key'] = asyncssh.generate_private_key('ssh-ed25519').export_public_key().decode()
        with self.assertRaises(asyncssh.HostKeyNotVerifiable):
            await probe(RelayProfile(**bad))

    async def test_full_unicode_directory_uses_bounded_pages_without_losing_rooms(self):
        # Non-BMP characters expand twelvefold in the ASCII JSON wire format.
        marker = chr(0x1f30d)
        game = dict(version=marker * 64, loader=marker * 32, loader_version=marker * 64,
                    mods_hash=marker * 64, protocol=772, mods_count=0, mods=[])
        expected = set()
        for index in range(128):
            room_id = format(index, '032x')
            expected.add(room_id)
            self.relays[0].rooms[room_id] = Room(None, port=25565, public=True,
                                                title=marker * 80, game=game)
        await self.sync()
        for profile in self.profiles:
            listing = await list_rooms(profile)
            self.assertEqual({room['id'] for room in listing['rooms']}, expected)


if __name__ == '__main__':
    unittest.main(verbosity=2)
