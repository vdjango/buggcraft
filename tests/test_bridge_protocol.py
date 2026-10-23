"""Published stdio API tested through a real child process and game sockets."""
import asyncio
import json
import os
import secrets
import sys
import unittest
from types import SimpleNamespace

from . import test_room_chat as fixture
from . import test_peer_transport as peer_fixture
from hookup.nodes import encode_code
from hookup.relay import RelayProfile


class BridgeProtocolTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixture.RoomChatTests.asyncSetUp
    asyncTearDown = fixture.RoomChatTests.asyncTearDown
    world = peer_fixture.PeerTransportTests.world
    exchange = peer_fixture.PeerTransportTests.exchange

    async def process(self):
        environment = dict(os.environ, PYTHONPATH=os.pathsep.join(sys.path))
        process = await asyncio.create_subprocess_exec(sys.executable, '-X', 'utf8',
            '-m', 'hookup', 'bridge', stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=environment)
        async def cleanup():
            if process.returncode is None:
                process.stdin.close()
                try:
                    await asyncio.wait_for(process.wait(), 10)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
        self.addAsyncCleanup(cleanup)
        return process

    async def call(self, process, method, params=None, identifier=1):
        process.stdin.write((json.dumps({'jsonrpc': '2.0', 'id': identifier,
            'method': method, 'params': params or {}}) + '\n').encode())
        await process.stdin.drain()
        line = await asyncio.wait_for(process.stdout.readline(), 22)
        self.assertTrue(line, 'Bridge exited without a response')
        response = json.loads(line)
        self.assertEqual(response['jsonrpc'], '2.0')
        self.assertEqual(response['id'], identifier)
        return response

    async def test_import_host_join_transfer_close_and_eof_release_resources(self):
        process = await self.process()
        response = await self.call(process, 'bridge.initialize', {'protocol': 1})
        self.assertIn('room.join', response['result']['methods'])
        response = await self.call(process, 'node.add', {'code': encode_code(self.profile)})
        node = response['result']['node']
        self.assertEqual(response['result']['identity'], 'anonymous')
        hosted = (await self.call(process, 'room.host', {'node': node,
                  'game_port': await self.world(), 'transport': 'relay'}))['result']
        self.assertIn(hosted['room'], self.relay.rooms)
        joined = (await self.call(process, 'room.join', {'node': node,
                  'invite': hosted['invite']}))['result']
        address, port = joined['address'].rsplit(':', 1)
        self.assertEqual(address, '127.0.0.1')
        await self.exchange(SimpleNamespace(listen_port=int(port)), 64 * 1024)
        sessions = (await self.call(process, 'session.list'))['result']['sessions']
        self.assertEqual({s['session'] for s in sessions}, {hosted['session'], joined['session']})
        self.assertEqual((await self.call(process, 'node.remove', {'node': node}))['error']['code'], -32009)
        self.assertTrue((await self.call(process, 'room.close', {'session': joined['session']}))['result']['closed'])
        with self.assertRaises(OSError):
            await asyncio.open_connection('127.0.0.1', int(port))
        process.stdin.close()
        await asyncio.wait_for(process.wait(), 10)
        self.assertEqual(process.returncode, 0, (await process.stderr.read()).decode())
        self.assertNotIn(hosted['room'], self.relay.rooms)

    async def test_errors_notifications_limits_and_no_credential_echo(self):
        process = await self.process()
        process.stdin.write(b'{broken\n')
        response = json.loads(await asyncio.wait_for(process.stdout.readline(), 3))
        self.assertEqual(response['error']['code'], -32700)
        self.assertIsNone(response['id'])
        for method, params, expected in [('missing.method', {}, -32601),
                ('bridge.initialize', {'protocol': 2}, -32602),
                ('node.add', {'code': 'private-credential-value'}, -32602),
                ('room.join', {'node': []}, -32602)]:
            response = await self.call(process, method, params)
            self.assertEqual(response['error']['code'], expected)
            self.assertNotIn('private-credential-value', json.dumps(response))
        # JSON-RPC notifications do not generate replies or shift request IDs.
        process.stdin.write(b'{"jsonrpc":"2.0","method":"bridge.initialize"}\n')
        response = await self.call(process, 'bridge.initialize', identifier='after-notification')
        self.assertEqual(response['id'], 'after-notification')
        process.stdin.write(b'x' * 8193)  # no newline: bounded before allocation
        await process.stdin.drain()
        response = json.loads(await asyncio.wait_for(process.stdout.readline(), 3))
        self.assertEqual(response['error']['code'], -32600)
        await asyncio.wait_for(process.wait(), 5)
        self.assertEqual(process.returncode, 0)

    async def test_standard_api_supports_mixed_room_without_launcher_punching_logic(self):
        process = await self.process()
        await self.call(process, 'bridge.initialize', {'protocol':1})
        node = (await self.call(process, 'node.add', {'code':encode_code(self.profile)}))['result']['node']
        host = (await self.call(process, 'room.host', {'node':node,
            'game_port':await self.world()}))['result']
        direct = (await self.call(process, 'room.join', {'node':node,
            'invite':host['invite'], 'transport':'auto'}))['result']
        relayed = (await self.call(process, 'room.join', {'node':node,
            'invite':host['invite'], 'transport':'relay'}))['result']
        self.assertEqual(host['transport'], 'auto')
        self.assertEqual(direct['transport'], 'p2p')
        self.assertEqual(relayed['transport'], 'relay')
        await asyncio.gather(*(self.exchange(SimpleNamespace(
            listen_port=int(result['address'].rsplit(':',1)[1])), 65536)
            for result in (direct, relayed)))
        sessions = (await self.call(process, 'session.list'))['result']['sessions']
        self.assertEqual({s['transport'] for s in sessions if s['role']=='client'}, {'p2p','relay'})
        for result in (direct, relayed, host):
            response = await self.call(process, 'room.close', {'session':result['session']})
            self.assertTrue(response['result']['closed'])

    async def test_wrong_pinned_key_is_rejected(self):
        import asyncssh
        wrong = RelayProfile(self.profile.server_host, self.profile.server_port,
                            self.profile.token,
                            asyncssh.generate_private_key('ssh-ed25519').export_public_key().decode())
        process = await self.process()
        response = await self.call(process, 'node.add', {'code': encode_code(wrong)})
        self.assertEqual(response['error']['code'], -32030)
        self.assertNotIn(self.profile.token, json.dumps(response))


if __name__ == '__main__':
    unittest.main(verbosity=2)
