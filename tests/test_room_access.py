"""Room visibility and invitation enforcement over actual encrypted connections."""
import asyncio
import json
import os
from pathlib import Path
import secrets
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / '.test-tools'), str(ROOT / 'minecraft-tunnel/src'),
               str(ROOT / 'buggcraft/src/buggcraft')]
import asyncssh
from tunnel.directory import RoomControlSession
from tunnel.relay import RelayServer
from hookup.relay import RelayProfile, RoomInvite, TunnelHost, TunnelClient
from hookup.rooms import list_rooms, resolve_room, request


class AccessFixture:
    async def asyncSetUp(self):
        async def echo(reader, writer):
            try:
                while data := await reader.read(65536):
                    writer.write(data)
                    await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()
        self.world = await asyncio.start_server(echo, '127.0.0.1', 0)
        self.port = self.world.sockets[0].getsockname()[1]
        self.endpoints, self.tasks = [], []

    async def asyncTearDown(self):
        await asyncio.gather(*(e.stop() for e in self.endpoints), return_exceptions=True)
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.world.close()
        await self.world.wait_closed()

    async def endpoint(self, cls, invite=None, **options):
        ready = asyncio.Event()
        endpoint = cls(self.profile, invite, game_port=self.port, listen_port=0,
                       announce=False, **options)
        endpoint.on_status = lambda state, detail: ready.set() if state == 'online' else None
        self.endpoints.append(endpoint)
        task = asyncio.create_task(endpoint.run())
        self.tasks.append(task)
        waiter = asyncio.create_task(ready.wait())
        try:
            done, _ = await asyncio.wait([task, waiter], timeout=15,
                                         return_when=asyncio.FIRST_COMPLETED)
            if task in done:
                await task
            self.assertTrue(ready.is_set(), 'Endpoint did not become ready')
        finally:
            waiter.cancel()
            await asyncio.gather(waiter, return_exceptions=True)
        return endpoint


class AccessRoundtrip:
    async def test_ten_rounds_three_access_modes_three_clients_and_data_integrity(self):
        for turn in range(10):
            public, required = ((True, False), (True, True), (False, True))[turn % 3]
            with self.subTest(round=turn, public=public, require_invite=required):
                host = await self.endpoint(TunnelHost, room_settings={
                    'title':'Access verification', 'public':public, 'require_invite':required,
                    'capacity':8, 'game':{'version':'1.21.8'}})
                listing = (await list_rooms(self.profile))['rooms']
                own = [room for room in listing if room['id'] == host.invite.room_id]
                self.assertEqual(len(own), int(public))
                if public:
                    self.assertEqual(own[0]['require_invite'], required)
                    resolved = await resolve_room(self.profile, host.invite.room_id)
                    self.assertEqual('secret' in resolved, not required)
                    if required:
                        self.assertNotIn(host.invite.secret, str(resolved))
                        invite = host.invite
                    else:
                        invite = RoomInvite(resolved['secret'])
                else:
                    with self.assertRaises(ConnectionError):
                        await resolve_room(self.profile, host.invite.room_id)
                    invite = host.invite
                clients = [await self.endpoint(TunnelClient, invite) for _ in range(3)]
                try:
                    for client in clients:
                        reader, writer = await asyncio.open_connection('127.0.0.1', client.listen_port)
                        try:
                            payload = secrets.token_bytes(65536)
                            writer.write(payload)
                            await writer.drain()
                            self.assertEqual(await asyncio.wait_for(reader.readexactly(len(payload)), 10), payload)
                        finally:
                            writer.close()
                            await writer.wait_closed()
                finally:
                    await host.stop()
                    async with asyncio.timeout(10):
                        while not all(client._stopped for client in clients):
                            await asyncio.sleep(.025)
                    await asyncio.gather(*(client.stop() for client in clients))
                listing = (await list_rooms(self.profile))['rooms']
                self.assertNotIn(host.invite.room_id, {room['id'] for room in listing})


class RoomAccessTests(AccessRoundtrip, AccessFixture, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        key = asyncssh.generate_private_key('ssh-ed25519')
        self.relay = await RelayServer('127.0.0.1', 0, host_key=key,
                                      token=secrets.token_urlsafe(48)).start()
        self.profile = RelayProfile('127.0.0.1', self.relay.port, self.relay.token,
                                    key.export_public_key().decode())

    async def asyncTearDown(self):
        await super().asyncTearDown()
        await self.relay.close()

    async def test_older_node_cannot_silently_publish_a_protected_room(self):
        dispatch = RoomControlSession.dispatch
        def old_node(session, payload):
            if payload.get('op') == 'ping':
                return {'version':1, 'rooms':0, 'max_streams':512}
            return dispatch(session, payload)
        with patch.object(RoomControlSession, 'dispatch', old_node):
            with self.assertRaisesRegex(ValueError, '不支持公开房间的邀请码保护'):
                await self.endpoint(TunnelHost, room_settings={'public':True, 'require_invite':True})
        self.assertEqual((await list_rooms(self.profile))['rooms'], [])

    async def test_invalid_configuration_is_rejected_without_dropping_invite_protection(self):
        host = await self.endpoint(TunnelHost, room_settings={'public':True, 'require_invite':True})
        for value in ('false', 0, None):
            with self.subTest(value=value), self.assertRaises(ConnectionError):
                await request(host.connection, 'configure', public=True, require_invite=value)
        resolved = await resolve_room(self.profile, host.invite.room_id)
        self.assertTrue(resolved['room']['require_invite'])
        self.assertNotIn('secret', resolved)

    async def test_directory_credentials_do_not_admit_a_client_to_a_protected_room(self):
        host = await self.endpoint(TunnelHost, room_settings={'public':True, 'require_invite':True})
        wrong_secret = secrets.token_urlsafe(32)
        # Knowing the publicly listed room ID and the node's player token is insufficient.
        with self.assertRaises(asyncssh.PermissionDenied):
            await asyncssh.connect(self.profile.server_host, self.profile.server_port,
                username=f'client:{host.invite.room_id}',
                password=json.dumps({'token':self.profile.token, 'secret':wrong_secret}),
                known_hosts=self.profile.known_hosts(), client_keys=[], agent_path=None,
                preferred_auth=['password'], encoding=None)


@unittest.skipUnless(os.environ.get('BUGGCRAFT_ACCESS_PROFILE'), 'Opt-in authorized remote-node test')
class RemoteRoomAccessTests(AccessRoundtrip, AccessFixture, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.profile = RelayProfile.load(os.environ['BUGGCRAFT_ACCESS_PROFILE'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
