"""Game chat integration against an isolated, loopback-only vanilla 1.21.8 world.

Uses the previously downloaded server and independent Mineflayer clients. No
public relay, credentials, player saves or account service is accessed.
"""
import asyncio
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / '.test-tools'), str(ROOT / 'minecraft-tunnel/src'),
               str(ROOT / 'buggcraft/src/buggcraft')]
import asyncssh
from tunnel.relay import RelayServer
from hookup.relay import RelayProfile, TunnelHost, TunnelClient

SERVER = ROOT / 'multiplayer-tests/game-server/server.jar'
FIXTURE = Path(__file__).with_name('fixtures') / 'chat_players.cjs'


@unittest.skipUnless(SERVER.exists() and shutil.which('java') and shutil.which('node')
                     and (ROOT / 'multiplayer-tests/node_modules/mineflayer').exists(),
                     'Local Java 21, server 1.21.8 and Mineflayer fixtures required')
class RealGameChatTests(unittest.IsolatedAsyncioTestCase):
    async def wait(self, condition, timeout=20):
        async with asyncio.timeout(timeout):
            while not condition():
                await asyncio.sleep(.03)

    async def asyncSetUp(self):
        self.endpoints, self.tasks, self.events, self.game_events = [], [], {}, []
        self.players = self.server = self.relay = None
        self.temporary = tempfile.TemporaryDirectory(prefix='room-chat-', dir=ROOT / 'multiplayer-tests')
        self.work = Path(self.temporary.name)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            self.port = sock.getsockname()[1]
        (self.work / 'eula.txt').write_text('eula=true\n')
        (self.work / 'server.properties').write_text(
            f'server-ip=127.0.0.1\nserver-port={self.port}\nonline-mode=false\n'
            'enforce-secure-profile=false\nmax-players=10\nview-distance=2\n'
            'simulation-distance=2\nlevel-type=minecraft:flat\ngamemode=creative\n'
            'difficulty=peaceful\nspawn-protection=0\nplayer-idle-timeout=0\n'
            'enable-rcon=false\nenable-query=false\nnetwork-compression-threshold=256\n')
        self.console = (self.work / 'console.log').open('wb')
        self.addAsyncCleanup(self.cleanup)
        if getattr(self, 'integrated_port', None):
            from hookup.rooms import game_status
            self.port = self.integrated_port
            self.assertEqual((await game_status(self.port))['protocol'], 772)
        else:
            self.server = await asyncio.create_subprocess_exec(
                'java', '-Xms512M', '-Xmx3G', '-jar', str(SERVER), 'nogui',
                cwd=self.work, stdin=asyncio.subprocess.PIPE, stdout=self.console,
                stderr=asyncio.subprocess.STDOUT)
            await self.wait(lambda: b'Done (' in (self.work / 'console.log').read_bytes()
                            or self.server.returncode is not None, 90)
            self.assertIsNone(self.server.returncode, (self.work / 'console.log').read_text(errors='replace'))
        profile_path = os.environ.get('BUGGCRAFT_LAN_RELAY_PROFILE') if getattr(self, 'integrated_port', None) else None
        if profile_path:
            self.profile = RelayProfile.load(profile_path)
        else:
            key = asyncssh.generate_private_key('ssh-ed25519')
            self.relay = await RelayServer('127.0.0.1', 0, host_key=key, token=secrets.token_urlsafe(48)).start()
            self.profile = RelayProfile('127.0.0.1', self.relay.port, self.relay.token,
                                        key.export_public_key().decode())

    async def cleanup(self):
        if self.players and self.players.returncode is None:
            self.players.stdin.write(b'{"op":"close"}\n')
            try:
                await asyncio.wait_for(self.players.wait(), 8)
            except asyncio.TimeoutError:
                self.players.kill()
                await self.players.wait()
        await asyncio.gather(*(p.stop() for p in self.endpoints), return_exceptions=True)
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        if self.relay:
            await self.relay.close()
        if self.server and self.server.returncode is None:
            self.server.stdin.write(b'stop\n')
            try:
                await asyncio.wait_for(self.server.wait(), 20)
            except asyncio.TimeoutError:
                self.server.kill()
                await self.server.wait()
        self.console.close()
        shutil.copyfile(self.work / 'console.log', ROOT / 'multiplayer-tests' /
                        getattr(self, 'console_artifact', 'chat-game-console.log'))
        self.temporary.cleanup()

    async def endpoint(self, cls, invite=None, **options):
        endpoint = cls(self.profile, invite, listen_port=0, announce=False, **options)
        endpoint.chat_name = '大厅玩家' + str(len(self.endpoints))
        self.events[endpoint] = []
        endpoint.on_chat = self.events[endpoint].append
        self.endpoints.append(endpoint)
        self.tasks.append(asyncio.create_task(endpoint.run()))
        await self.wait(lambda: any(e.get('type') == 'ready' for e in self.events[endpoint]))
        return endpoint

    async def read_players(self):
        while line := await self.players.stdout.readline():
            self.game_events.append(json.loads(line))

    async def test_disabled_sync_has_four_real_roles_and_no_extra_virtual_player(self):
        from hookup.rooms import game_status
        host = await self.endpoint(TunnelHost, game_port=self.port, room_settings={
            'title':'Lobby only integration', 'public':False, 'capacity':10,
            'game':{'version':'1.21.8', 'protocol':772, 'loader':'vanilla'}})
        clients = [await self.endpoint(TunnelClient, host.invite) for _ in range(3)]
        self.assertEqual((await game_status(self.port))['players']['online'], 0)
        self.players = await asyncio.create_subprocess_exec(
            'node', str(FIXTURE), str(self.port), *(str(p.listen_port) for p in clients),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE)
        self.tasks.append(asyncio.create_task(self.read_players()))
        await self.wait(lambda: sum(e['type'] == 'spawn' for e in self.game_events) == 4, 40)
        self.assertEqual((await game_status(self.port))['players']['online'], 4)
        for turn in range(10):
            text = f'lobby-only-{turn}'
            await [host, *clients][turn % 4].send_chat(text)
            await self.wait(lambda: all(any(e.get('text') == text for e in self.events[p])
                                       for p in [host, *clients]))
        self.players.stdin.write(b'{"op":"chat","index":0,"text":"game-only-check"}\n')
        await self.players.stdin.drain()
        await self.wait(lambda: all(any(e['type'] == 'message' and e['index'] == i
            and 'game-only-check' in e['text'] for e in self.game_events) for i in range(4)))
        await host.retarget_world(self.port)
        await asyncio.sleep(1)
        self.assertEqual((await game_status(self.port))['players']['online'], 4)
        self.assertIsNone(host.bridge_task)
        self.assertFalse(any(e['type'] == 'message' and 'lobby-only-' in e['text']
                             for e in self.game_events))
        self.assertFalse(any(e.get('source') == 'game' for p in [host, *clients]
                             for e in self.events[p]))
        self.assertFalse([e for e in self.game_events if e['type'] in ('error', 'kicked')])
        (ROOT / 'multiplayer-tests/chat-disabled-game-result.json').write_text(json.dumps({
            'version':'1.21.8', 'gamePlayers':4, 'virtualPlayers':0, 'lobbyRounds':10,
            'worldRetarget':True, 'result':'passed', 'network':'loopback'}, indent=2), encoding='utf8')

    async def test_p2p_game_counts_do_not_depend_on_relay_streams_or_lobby_members(self):
        from hookup.rooms import game_status
        host = await self.endpoint(TunnelHost, game_port=self.port)
        clients = [await self.endpoint(TunnelClient, host.invite) for _ in range(3)]
        self.assertTrue(all(client.transport_state == 'p2p' for client in clients))
        self.players = await asyncio.create_subprocess_exec(
            'node', str(FIXTURE), str(self.port), *(str(client.listen_port) for client in clients),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE)
        self.tasks.append(asyncio.create_task(self.read_players()))
        await self.wait(lambda: sum(event['type'] == 'spawn' for event in self.game_events) == 4, 40)
        room = self.relay.rooms[host.invite.room_id]
        await self.wait(lambda: room.game_players == 4, 10)
        self.assertEqual(self.relay.capacity.members(host.invite.room_id), 4)
        self.assertEqual(len(self.relay.streams), 0)
        self.assertEqual(self.relay.capacity.bytes, 0)
        self.server.stdin.write(b'kick ChatTest3 Counting fixture\n')
        await self.server.stdin.drain()
        await self.wait(lambda: room.game_players == 3, 10)
        self.assertEqual((await game_status(self.port))['players']['online'], 3)
        # The launcher remains in the room even after its game player leaves.
        self.assertEqual(self.relay.capacity.members(host.invite.room_id), 4)
        self.assertEqual(len(self.relay.streams), 0)
        await clients[-1].stop()
        await self.wait(lambda: self.relay.capacity.members(host.invite.room_id) == 3)
        self.assertEqual(room.game_players, 3)
        await host.stop()
        await self.wait(lambda: host.invite.room_id not in self.relay.rooms)

    async def test_host_three_clients_ten_rounds_bidirectional_chat_and_rejoin(self):
        host = await self.endpoint(TunnelHost, game_port=self.port,
            game_chat_enabled=True, game_chat_name='LobbyBridge', room_settings={
            'title':'Local chat integration', 'public':False, 'capacity':10,
            'game':{'version':'1.21.8', 'protocol':772, 'loader':'vanilla'}})
        clients = [await self.endpoint(TunnelClient, host.invite) for _ in range(3)]
        await self.wait(lambda: host.bridge and host.bridge.ready, 30)
        self.assertEqual(host.bridge.name, 'LobbyBridge')
        self.players = await asyncio.create_subprocess_exec(
            'node', str(FIXTURE), str(self.port), *(str(p.listen_port) for p in clients),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE)
        self.tasks.append(asyncio.create_task(self.read_players()))
        await self.wait(lambda: sum(e['type'] == 'spawn' for e in self.game_events) == 4, 40)
        for turn in range(10):
            text = f'大厅到游戏 {turn} 😀'
            await [host, *clients][turn % 4].send_chat(text)
            await self.wait(lambda: all(any(e['type'] == 'message' and e['index'] == i
                and text in e['text'] for e in self.game_events) for i in range(4)))
            game_text = f'game-to-lobby-{turn}'
            self.players.stdin.write((json.dumps({'op':'chat', 'index':turn % 4,
                                                 'text':game_text}) + '\n').encode())
            await self.players.stdin.drain()
            await self.wait(lambda: all(any(e.get('source') == 'game' and e.get('text') == game_text
                for e in self.events[p]) for p in [host, *clients]))
            for endpoint in [host, *clients]:
                messages = [e for e in self.events[endpoint] if e.get('text') == game_text]
                self.assertEqual(len(messages), 1)
                self.assertEqual(messages[0]['sender'], 'ChatTest' + str(turn % 4))
            await asyncio.sleep(.7)
        # Chat-channel rejoin must preserve game sessions and not replay into the game.
        before = len([e for e in self.game_events if e['type'] == 'message'])
        ready = sum(e.get('type') == 'ready' for e in self.events[clients[0]])
        clients[0].chat_process.close()
        await self.wait(lambda: sum(e.get('type') == 'ready' for e in self.events[clients[0]]) > ready)
        await asyncio.sleep(16)  # exercise real server keepalive while clients remain in world
        await clients[0].send_chat('after-reconnect')
        await self.wait(lambda: all(any(e['type'] == 'message' and e['index'] == i
            and 'after-reconnect' in e['text'] for e in self.game_events) for i in range(4)))
        self.assertTrue(host.bridge.ready)
        self.assertGreater(len(self.game_events), before)
        self.assertFalse([e for e in self.game_events if e['type'] in ('error', 'kicked')])
        result = {'version':'1.21.8', 'protocol':772, 'rounds':10, 'gamePlayers':4,
                  'clientTunnels':3, 'directions':['lobby-to-game','game-to-lobby'],
                  'chatReconnect':True, 'keepalive':True, 'result':'passed', 'network':'loopback'}
        (ROOT / 'multiplayer-tests/chat-game-result.json').write_text(
            json.dumps(result, indent=2), encoding='utf8')


if __name__ == '__main__':
    unittest.main(verbosity=2)
