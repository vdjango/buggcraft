"""Real encrypted room chat: isolation, identity, history, rate and lifecycle."""
import asyncio
import json
from pathlib import Path
import secrets
import sys
import unittest
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / '.test-tools'), str(ROOT / 'minecraft-tunnel/src'),
               str(ROOT / 'buggcraft/src/buggcraft')]
import asyncssh
from tunnel.relay import RelayServer
from hookup.relay import RelayProfile, TunnelHost, TunnelClient
from hookup.rooms import connect_directory
from hookup.chat_validation import chat_text, bridge_player_name


class ChatValidationTests(unittest.TestCase):
    def test_virtual_player_name_is_ascii_english_and_bounded(self):
        for name in ('BuggChat', 'Lobby_01', 'Abc', 'A' * 16):
            self.assertEqual(bridge_player_name(name), name)
        for name in ('', 'Ab', 'A' * 17, '123', '聊天助手', 'Bugg玩家',
                     'ＢuggChat', 'Bugg Chat', 'BuggChat\n', None):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, '英文字母'):
                bridge_player_name(name)

    def test_plain_text_unicode_and_utf16_limit(self):
        self.assertEqual(chat_text('  你好 😀  '), '你好 😀')
        self.assertEqual(chat_text('😀' * 128), '😀' * 128)
        for text in ('', ' ', 'a\nb', 'a\x00b', '§c红色', '😀' * 129, 'a' * 257, None):
            with self.subTest(text=repr(text)[:40]), self.assertRaises(ValueError):
                chat_text(text)


class RoomChatTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        key = asyncssh.generate_private_key('ssh-ed25519')
        self.relay = await RelayServer('127.0.0.1', 0, host_key=key, token=secrets.token_urlsafe(48)).start()
        self.profile = RelayProfile('127.0.0.1', self.relay.port, self.relay.token,
                                    key.export_public_key().decode())
        self.endpoints, self.tasks = [], []
        self.events = {}

    async def asyncTearDown(self):
        await asyncio.gather(*(e.stop() for e in self.endpoints), return_exceptions=True)
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await self.relay.close()

    async def wait(self, condition, timeout=10):
        async with asyncio.timeout(timeout):
            while not condition():
                await asyncio.sleep(.01)

    async def endpoint(self, cls, invite=None, **options):
        endpoint = cls(self.profile, invite, listen_port=0, announce=False, **options)
        messages = []
        endpoint.chat_name = '好友' + str(len(self.endpoints))
        endpoint.on_chat = messages.append
        self.events[endpoint] = messages
        self.endpoints.append(endpoint)
        self.tasks.append(asyncio.create_task(endpoint.run()))
        await self.wait(lambda: any(e.get('type') == 'ready' for e in messages))
        return endpoint

    async def test_disabled_bridge_preserves_lobby_chat_across_reconnect_and_world_reopen(self):
        with patch('hookup.game_chat.GameChatBridge') as bridge:
            host = await self.endpoint(TunnelHost, game_port=0, room_settings={
                'title':'Lobby only', 'public':False, 'capacity':10,
                'game':{'version':'1.21.8', 'protocol':772, 'loader':'vanilla'}})
            client = await self.endpoint(TunnelClient, host.invite)
            await self.wait(lambda: any('未开启' in e.get('status', '') for e in self.events[client]))
            for sender, text in ((host, 'host lobby only'), (client, 'client lobby only')):
                await sender.send_chat(text)
                await self.wait(lambda: all(any(e.get('text') == text for e in self.events[p])
                                           for p in (host, client)))
            previous = host.connection
            previous.close()
            await self.wait(lambda: host.connection is not previous and host.connection
                            and not host.connection.is_closed() and host.chat_process, 15)
            await self.wait(lambda: any(e.get('replay') for e in self.events[host]))
            with patch('hookup.relay.game_status', new=AsyncMock(return_value={'protocol':772})):
                await host.retarget_world(51234)
            await client.send_chat('after world reopen')
            await self.wait(lambda: any(e.get('text') == 'after world reopen' for e in self.events[host]))
            self.assertFalse(host.game_chat_enabled)
            self.assertIsNone(host.bridge_task)
            self.assertTrue(host.bridge_queue.empty())
            bridge.assert_not_called()

    async def test_three_clients_receive_once_and_other_room_is_isolated(self):
        host = await self.endpoint(TunnelHost)
        clients = [await self.endpoint(TunnelClient, host.invite) for _ in range(3)]
        other = await self.endpoint(TunnelHost)
        for endpoint in [host, *clients]:
            await endpoint.send_chat('你好 😀 ' + endpoint.chat_name)
        await self.wait(lambda: all(sum(e.get('type') == 'message' for e in self.events[p]) == 4
                                   for p in [host, *clients]))
        for endpoint in [host, *clients]:
            messages = [e for e in self.events[endpoint] if e.get('type') == 'message']
            self.assertEqual(len({e['id'] for e in messages}), 4)
            self.assertEqual({e['sender'] for e in messages}, {p.chat_name for p in [host, *clients]})
        self.assertFalse(any(e.get('type') == 'message' for e in self.events[other]))

    async def test_reconnect_replays_history_and_cannot_forge_game_or_sender(self):
        host = await self.endpoint(TunnelHost)
        client = await self.endpoint(TunnelClient, host.invite)
        await host.send_chat('first')
        await self.wait(lambda: any(e.get('text') == 'first' for e in self.events[client]))
        await client.chat_write({'op':'game', 'name':'FakeAdmin', 'text':'forged'})
        await self.wait(lambda: any(e.get('type') == 'error' for e in self.events[client]))
        self.assertFalse(any(e.get('text') == 'forged' for e in self.events[host]))
        await client.chat_write({'op':'send', 'name':'FakeAdmin', 'text':'real'})
        await self.wait(lambda: any(e.get('text') == 'real' for e in self.events[host]))
        real = next(e for e in self.events[host] if e.get('text') == 'real')
        self.assertEqual(real['sender'], client.chat_name)
        previous = sum(e.get('type') == 'ready' for e in self.events[client])
        client.chat_process.close()
        await self.wait(lambda: sum(e.get('type') == 'ready' for e in self.events[client]) > previous)
        await self.wait(lambda: any(e.get('text') == 'first' and e.get('replay') for e in self.events[client]))
        history = self.relay.rooms[host.invite.room_id].chat_history
        self.assertEqual(len(history), 2)
        self.assertLessEqual(history.maxlen, 200)

    async def test_chat_account_comes_from_authentication_not_message_or_game_name(self):
        account = 'a' * 32 + '.' + 'b' * 32
        personal_token = secrets.token_urlsafe(48)
        self.relay.account_authenticate = lambda token: account if token == personal_token else None
        host = await self.endpoint(TunnelHost)
        self.profile = RelayProfile(self.profile.server_host, self.profile.server_port,
                                    personal_token, self.profile.server_public_key)
        client = await self.endpoint(TunnelClient, host.invite)
        await client.chat_write({'op': 'send', 'text': 'authenticated', 'account': 'forged'})
        await host.chat_write({'op': 'send', 'text': 'anonymous', 'account': account})
        await host.chat_write({'op': 'game', 'name': client.chat_name, 'text': 'game-player', 'account': account})
        await self.wait(lambda: len([e for e in self.events[client] if e.get('type') == 'message']) == 3)
        messages = {e['text']: e for e in self.events[client] if e.get('type') == 'message'}
        self.assertEqual(messages['authenticated']['account'], account)
        self.assertIsNone(messages['anonymous']['account'])
        self.assertIsNone(messages['game-player']['account'])

    async def test_directory_and_oversize_rate_limits_and_close(self):
        host = await self.endpoint(TunnelHost)
        client = await self.endpoint(TunnelClient, host.invite)
        async with await connect_directory(self.profile) as connection:
            with self.assertRaises(asyncssh.ChannelOpenError):
                await connection.create_process(subsystem='buggcraft-chat-v1')
        for _ in range(15):
            await client.chat_write({'op':'send', 'text':'rate'})
        await self.wait(lambda: any('发送过快' in e.get('error', '') for e in self.events[client]))
        self.assertLessEqual(len(self.relay.rooms[host.invite.room_id].chat_history), 10)
        process = client.chat_process
        process.stdin.write(b'x' * 5000)
        await self.wait(lambda: process.exit_status is not None or client.chat_process is not process)
        await host.stop()
        await self.wait(lambda: not self.relay.rooms)
        self.assertFalse(self.relay.rooms)

    async def test_rate_rejection_is_acknowledged_and_pending_sends_are_released(self):
        host = await self.endpoint(TunnelHost)
        client = await self.endpoint(TunnelClient, host.invite)
        # Includes the initial identity handshake in the per-peer rate limit.
        for i in range(9):
            await client.send_chat('accepted ' + str(i))
        with self.assertRaisesRegex(ValueError, '发送过快'):
            await client.send_chat('rejected')
        self.assertEqual(client.chat_pending, {})
        self.assertFalse(any(e.get('text') == 'rejected' for e in self.events[host]))
        self.assertFalse(any('request' in e for e in self.events[client]))


if __name__ == '__main__':
    unittest.main(verbosity=2)
