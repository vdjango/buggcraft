"""Exercise the bridge process with real SSH, ICE, and game TCP sockets."""
import asyncio
import json
import os
from pathlib import Path
import secrets
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
NODE = Path(os.environ.get('BUGGCRAFT_NODE_SOURCE', ROOT.parent / 'minecraft-tunnel'))
sys.path[:0] = [str(ROOT / 'src/buggcraft'), str(NODE / 'src')]

import asyncssh
from hookup.nodes import encode_code
from hookup.relay import RelayProfile
from tunnel.relay import RelayServer


class ProcessCases:
    packaged = False

    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='bridge integration space ')
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        key = asyncssh.generate_private_key('ssh-ed25519')
        self.relay = await RelayServer('127.0.0.1', 0, host_key=key,
                                      token=secrets.token_urlsafe(48)).start()
        self.addAsyncCleanup(self.relay.close)
        self.profile = RelayProfile('127.0.0.1', self.relay.port, self.relay.token,
                                    key.export_public_key().decode())
        async def echo(reader, writer):
            try:
                while chunk := await reader.read(65536):
                    writer.write(chunk)
                    await writer.drain()
                if writer.can_write_eof():
                    writer.write_eof()
            except (ConnectionError, asyncio.CancelledError):
                pass
            finally:
                writer.close()
                try:
                    await writer.wait_closed()
                except ConnectionError:
                    pass
        self.game = await asyncio.start_server(echo, '127.0.0.1', 0)
        self.addAsyncCleanup(self.game.wait_closed)
        self.addCleanup(self.game.close)
        self.game_port = self.game.sockets[0].getsockname()[1]

    async def process(self):
        env = dict(os.environ)
        for name in ('PYTHONPATH', 'PYTHONHOME', 'QT_PLUGIN_PATH', 'VIRTUAL_ENV'):
            env.pop(name, None)
        if self.packaged:
            original = Path(os.environ['BUGGCRAFT_BRIDGE_EXECUTABLE']).resolve()
            copied = self.directory / 'portable component'
            if not copied.exists():
                shutil.copytree(original.parent, copied, symlinks=True)
            command = [str(copied / original.name)]
            env['PATH'] = str(Path(os.environ['WINDIR']) / 'System32') if os.name == 'nt' else '/usr/bin:/bin'
        else:
            env['PYTHONPATH'] = str(ROOT / 'src/buggcraft')
            command = [sys.executable, str(ROOT / 'packaging/bridge_entry.py')]
        process = await asyncio.create_subprocess_exec(*command, cwd=self.directory, env=env,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        # Always drain stderr so diagnostics cannot block the protocol pipe.
        errors = asyncio.create_task(process.stderr.read())
        process.bridge_errors = errors
        async def cleanup():
            if process.returncode is None:
                process.stdin.close()
                try:
                    await asyncio.wait_for(process.wait(), 15)
                except TimeoutError:
                    process.kill()
                    await process.wait()
            stderr = await errors
            self.assertNotIn(self.profile.token.encode(), stderr)
        self.addAsyncCleanup(cleanup)
        return process

    async def call(self, process, method, params=None, identifier=1):
        process.stdin.write((json.dumps({'jsonrpc': '2.0', 'id': identifier,
                              'method': method, 'params': params or {}}) + '\n').encode())
        await process.stdin.drain()
        raw = await asyncio.wait_for(process.stdout.readline(), 30)
        if not raw:
            stderr = await asyncio.wait_for(asyncio.shield(process.bridge_errors), 5)
            details = stderr.decode('utf-8', 'replace').replace(self.profile.token, '[redacted]')
            self.fail('Bridge exited before sending a response: ' + details[-3000:])
        reply = json.loads(raw)
        self.assertEqual(reply['id'], identifier)
        self.assertEqual(reply['jsonrpc'], '2.0')
        return reply

    async def node(self, process):
        init = (await self.call(process, 'bridge.initialize', {'protocol': 1}))['result']
        self.assertIn('room.join', init['methods'])
        self.assertEqual(init['build']['protocol'], 1)
        if self.packaged:
            self.assertRegex(init['build']['commit'], r'^[0-9a-f]{40}$')
        added = (await self.call(process, 'node.add', {'code': encode_code(self.profile)}))['result']
        self.assertEqual(added['identity'], 'anonymous')
        return added['node']

    async def exchange(self, joined):
        host, port = joined['address'].rsplit(':', 1)
        self.assertEqual(host, '127.0.0.1')
        reader, writer = await asyncio.open_connection(host, int(port))
        data = secrets.token_bytes(1024 * 1024)
        async def send():
            writer.write(data)
            await writer.drain()
            writer.write_eof()
        sender = asyncio.create_task(send())
        try:
            self.assertEqual(await asyncio.wait_for(reader.readexactly(len(data)), 30), data)
            await sender
            self.assertEqual(await asyncio.wait_for(reader.read(), 8), b'')
        finally:
            sender.cancel()
            await asyncio.gather(sender, return_exceptions=True)
            writer.close()
            await writer.wait_closed()

    async def test_two_processes_p2p_and_relay_mix_and_cleanup(self):
        host_process, guest_process = await self.process(), await self.process()
        host_node, guest_node = await self.node(host_process), await self.node(guest_process)
        host = (await self.call(host_process, 'room.host', {'node': host_node,
                                  'game_port': self.game_port}))['result']
        direct = (await self.call(guest_process, 'room.join', {'node': guest_node,
                                  'invite': host['invite'], 'transport': 'auto'}))['result']
        relay = (await self.call(guest_process, 'room.join', {'node': guest_node,
                                  'invite': host['invite'], 'transport': 'relay'}))['result']
        self.assertEqual(direct['transport'], 'p2p')
        self.assertEqual(relay['transport'], 'relay')
        await asyncio.gather(self.exchange(direct), self.exchange(relay))
        sessions = (await self.call(guest_process, 'session.list'))['result']['sessions']
        self.assertEqual({s['transport'] for s in sessions}, {'p2p', 'relay'})
        for joined in (direct, relay):
            self.assertTrue((await self.call(guest_process, 'room.close',
                             {'session': joined['session']}))['result']['closed'])
            with self.assertRaises(OSError):
                await asyncio.open_connection('127.0.0.1', int(joined['address'].rsplit(':', 1)[1]))
        host_process.stdin.close()
        await asyncio.wait_for(host_process.wait(), 15)
        self.assertEqual(host_process.returncode, 0)
        self.assertNotIn(host['room'], self.relay.rooms)

    async def test_auto_falls_back_when_host_only_supports_relay(self):
        process = await self.process()
        node = await self.node(process)
        host = (await self.call(process, 'room.host', {'node': node,
            'game_port': self.game_port, 'transport': 'relay'}))['result']
        joined = (await self.call(process, 'room.join', {'node': node,
                                   'invite': host['invite'], 'transport': 'auto'}))['result']
        self.assertEqual(joined['transport'], 'relay')
        await self.exchange(joined)

    async def test_pinned_key_failure_does_not_echo_credentials(self):
        process = await self.process()
        wrong = RelayProfile(self.profile.server_host, self.profile.server_port, self.profile.token,
                             asyncssh.generate_private_key('ssh-ed25519').export_public_key().decode())
        reply = await self.call(process, 'node.add', {'code': encode_code(wrong)})
        self.assertEqual(reply['error']['code'], -32000)
        self.assertNotIn(self.profile.token, json.dumps(reply))

    async def test_protocol_errors_notifications_and_unterminated_limit(self):
        process = await self.process()
        process.stdin.write(b'{broken\n')
        reply = json.loads(await asyncio.wait_for(process.stdout.readline(), 10))
        self.assertEqual(reply['error']['code'], -32700)
        self.assertIsNone(reply['id'])
        reply = await self.call(process, 'bridge.initialize', {'protocol': 2})
        self.assertEqual(reply['error']['code'], -32602)
        process.stdin.write(b'{"jsonrpc":"2.0","method":"bridge.initialize"}\n')
        reply = await self.call(process, 'session.list', identifier='after-notification')
        self.assertEqual(reply['result']['sessions'], [])
        process.stdin.write(b'x' * 8193)
        await process.stdin.drain()
        reply = json.loads(await asyncio.wait_for(process.stdout.readline(), 5))
        self.assertEqual(reply['error']['code'], -32600)
        await asyncio.wait_for(process.wait(), 10)
        self.assertEqual(process.returncode, 0)


class BridgeSourceTests(ProcessCases, unittest.IsolatedAsyncioTestCase):
    pass


@unittest.skipUnless(os.environ.get('BUGGCRAFT_BRIDGE_EXECUTABLE'), 'Set BUGGCRAFT_BRIDGE_EXECUTABLE for binary acceptance')
class BridgeBinaryTests(ProcessCases, unittest.IsolatedAsyncioTestCase):
    packaged = True
