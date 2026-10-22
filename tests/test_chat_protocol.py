"""Game protocol boundaries, lossless Unicode and acknowledgement behavior."""
import asyncio
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import AsyncMock, patch
import uuid
import zlib

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / '.test-tools'), str(ROOT / 'buggcraft/src/buggcraft')]
from hookup.game_chat import Cursor, GameChatBridge, MAX_PACKET, string
from hookup.rooms import varint


class ChatProtocolTests(unittest.IsolatedAsyncioTestCase):
    def bridge(self):
        self.messages, self.states = [], []
        async def message(name, text):
            self.messages.append((name, text))
        bridge = GameChatBridge(25565, 772, message, lambda *s: self.states.append(s))
        bridge.state = 'play'
        return bridge

    def test_generated_profiles_cover_every_released_java_version_from_1_6_4(self):
        import json
        profiles_path = ROOT / 'buggcraft/src/buggcraft/hookup/chat_protocols.json'
        profiles = json.loads(profiles_path.read_text(encoding='utf8'))
        # Keep this small publisher-manifest snapshot in the test tree, so the
        # unit test also runs on clean checkouts without downloaded game jars.
        manifest = json.loads((Path(__file__).parent / 'fixtures/java_releases.json').read_text(encoding='utf8'))
        releases = {version for profile in profiles.values() for version in profile.get('releases', [])}
        releases.add('1.6.4')  # The legacy protocol profile is kept in legacy_packets.json.
        ordered = manifest['releases']
        self.assertEqual(ordered[0], manifest['latest'])
        self.assertEqual(ordered[-1], '1.6.4')
        missing = [version for version in ordered if version not in releases]
        self.assertEqual(missing, [])
        for protocol, profile in profiles.items():
            with self.subTest(protocol=protocol):
                self.assertIn('keep_alive', profile['play_toClient'])
                self.assertIn('keep_alive', profile['play_toServer'])
                self.assertTrue({'chat', 'player_chat', 'system_chat'} & profile['play_toClient'].keys())
                self.assertTrue({'chat', 'chat_message'} & profile['play_toServer'].keys())

    def player_packet(self, bridge, *, sender=None, signature=None, filtered=0, chat_type=1):
        name = 'TestPlayer'.encode()
        return Cursor(b'\0' + (sender or uuid.uuid4()).bytes + b'\0'
            + (b'\1' + signature if signature else b'\0') + string('hello')
            + bytes(16) + b'\0\0' + varint(filtered) + varint(chat_type)
            + b'\x08' + struct.pack('>H', len(name)) + name)

    async def test_maximum_unicode_message_is_split_without_loss_or_oversize(self):
        bridge = self.bridge()
        bridge.ready = True
        bridge.send = AsyncMock()
        text = '😀' * 128
        with patch('hookup.game_chat.asyncio.sleep', new=AsyncMock()):
            await bridge.send_message('大厅玩家', text)
        chunks = []
        for call in bridge.send.await_args_list:
            message = Cursor(call.args[1]).text()
            self.assertLessEqual(len(message.encode('utf-16-le')), 512)
            self.assertTrue(message.startswith('[大厅] 大厅玩家: '))
            chunks.append(message.split(': ', 1)[1])
        self.assertGreater(len(chunks), 1)
        self.assertEqual(''.join(chunks), text)

    async def test_filtered_and_own_game_messages_are_not_relayed(self):
        bridge = self.bridge()
        await bridge.player_chat(self.player_packet(bridge, filtered=1))
        await bridge.player_chat(self.player_packet(bridge, sender=bridge.uuid))
        self.assertEqual(self.messages, [])
        await bridge.player_chat(self.player_packet(bridge))
        self.assertEqual(self.messages, [('TestPlayer', 'hello')])

    async def test_signed_chat_acknowledgements_and_memory_remain_bounded(self):
        bridge = self.bridge()
        bridge.send = AsyncMock()
        for i in range(65):
            signature = i.to_bytes(256, 'big')
            await bridge.player_chat(self.player_packet(bridge, signature=signature))
        self.assertEqual(len(bridge.signatures), 20)
        self.assertEqual(len(bridge.seen_signatures), 20)
        self.assertEqual(bridge.signed_pending, 0)
        bridge.send.assert_awaited_once()
        name, payload = bridge.send.await_args.args
        self.assertEqual(name, 'message_acknowledgement')
        self.assertEqual(Cursor(payload).integer(), 65)

    async def test_private_team_and_inline_chat_types_are_not_published_to_room(self):
        bridge = self.bridge()
        for chat_type in (0, 2, 3, 4, 5, 6, 7):
            with self.subTest(chat_type=chat_type):
                await bridge.player_chat(self.player_packet(bridge, chat_type=chat_type))
                self.assertEqual(self.messages, [])
        await bridge.player_chat(self.player_packet(bridge, chat_type=1))
        self.assertEqual(self.messages, [('TestPlayer', 'hello')])

    async def test_compressed_packets_reject_bombs_truncation_and_wrong_sizes(self):
        bridge = self.bridge()
        bridge.compression = 256
        body = b'x' * 1024
        for declared, compressed in ((MAX_PACKET + 1, zlib.compress(body)),
                (3, zlib.compress(body)), (len(body), zlib.compress(body)[:-2])):
            with self.subTest(declared=declared):
                packet = varint(declared) + compressed
                bridge.reader = asyncio.StreamReader()
                bridge.reader.feed_data(varint(len(packet)) + packet)
                bridge.reader.feed_eof()
                with self.assertRaises(ValueError):
                    await bridge.read()

    async def test_unknown_game_packets_do_not_abort_supported_handshake(self):
        bridge = self.bridge()
        bridge.state = 'login'
        reader = asyncio.StreamReader()
        # Unknown ordinary packet, then a deliberately truncated encryption request.
        reader.feed_data(b'\x01\x7f\x01\x01')
        writer = type('Writer', (), {'write': lambda *a: None, 'close': lambda *a: None,
            'drain': AsyncMock(), 'wait_closed': AsyncMock()})()
        with patch('hookup.game_chat.asyncio.open_connection', new=AsyncMock(return_value=(reader, writer))):
            await bridge.run()
        self.assertTrue(bridge.permanent_error)
        self.assertIn('协议无法识别', self.states[-1][1])

    async def test_encryption_handshake_and_stream_state_cover_protocol_changes(self):
        from cryptography.hazmat.primitives.asymmetric import rsa, padding
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms
        from cryptography.hazmat.decrepit.ciphers.modes import CFB8
        key = rsa.generate_private_key(public_exponent=65537, key_size=1024)
        public = key.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
        token = b'test'
        for protocol in (5, 47, 759, 760, 761, 772):
            with self.subTest(protocol=protocol):
                bridge = GameChatBridge(25565, protocol, AsyncMock(), lambda *s: None)
                packets = []
                bridge.send = AsyncMock(side_effect=lambda name, data: packets.append((name, data)))
                await bridge.encryption(Cursor(string('') + varint(len(public)) + public + varint(4) + token + b'\1'))
                self.assertEqual(packets[0][0], 'encryption_begin')
                reply = Cursor(packets[0][1])
                secret = key.decrypt(reply.take(reply.integer()), padding.PKCS1v15())
                if 759 <= protocol <= 760:
                    self.assertEqual(reply.take(1), b'\1')
                self.assertEqual(key.decrypt(reply.take(reply.integer()), padding.PKCS1v15()), token)
                cipher = Cipher(algorithms.AES(secret), CFB8(secret))
                raw = b'\1\0'
                bridge.reader = asyncio.StreamReader()
                bridge.reader.feed_data(cipher.encryptor().update(raw))
                name, cursor = await bridge.read()
                self.assertEqual(name, 'disconnect')
                self.assertEqual(cursor.pos, len(cursor.data))

    async def test_teleport_confirmation_handles_26_3_position_and_relative_rotation(self):
        for protocol in (772, 776, 777):
            with self.subTest(protocol=protocol):
                bridge = GameChatBridge(25565, protocol, AsyncMock(), lambda *s: None)
                bridge.state = 'play'
                bridge.send = AsyncMock()
                bridge.position, bridge.rotation = (10., 64., 20.), (90., 10.)
                payload = (varint(7) + struct.pack('>ddddddffI',
                    2., 70., 3., 0., 0., 0., 5., 30., 1 | 4 | 8))
                await bridge.position_packet(Cursor(payload))
                self.assertEqual(bridge.position, (12., 70., 23.))
                self.assertEqual(bridge.rotation, (95., 30.))
                reply = bridge.send.await_args_list[0].args
                self.assertEqual(reply[0], 'teleport_confirm')
                expected = varint(7)
                if protocol == 777:
                    expected += struct.pack('>dddff', 12., 70., 23., 95., 30.)
                self.assertEqual(reply[1], expected)
                self.assertTrue(bridge.ready)
                if protocol >= 776:
                    names = [call.args[0] for call in bridge.send.await_args_list]
                    self.assertEqual(names[names.index('position') + 1], 'client_tick_end')

    async def test_legacy_ping_sentinel_resolves_only_exact_known_release(self):
        from hookup.rooms import game_status
        for version, expected in (('26.3', 777), ('26.2', 776), ('unknown-future', 127)):
            async def respond(reader, writer):
                try:
                    if await reader.readexactly(1) == b'\xfe':
                        reply = '\0'.join(('\u00a71', '127', version, 'Test world', '1', '10')).encode('utf-16-be')
                        writer.write(b'\xff' + struct.pack('>H', len(reply) // 2) + reply)
                        await writer.drain()
                finally:
                    writer.close()
                    await writer.wait_closed()
            with self.subTest(version=version):
                async with await asyncio.start_server(respond, '127.0.0.1', 0) as server:
                    port = server.sockets[0].getsockname()[1]
                    result = await game_status(port)
                    self.assertEqual(result['protocol'], expected)

    def test_unsupported_protocol_and_malformed_nbt_fail_explicitly(self):
        with self.assertRaises(ValueError):
            GameChatBridge(25565, 999999, None, None)
        for packet in (b'\x09\x08' + struct.pack('>i', 5000), b'\x08\xff\xffx', b'\xff'):
            with self.subTest(packet=packet), self.assertRaises(ValueError):
                Cursor(packet).nbt()

    def test_custom_identity_is_stable_across_reconnect_and_legacy_protocol(self):
        for protocol in (78, 772):
            first = GameChatBridge(25565, protocol, None, None, name='LobbyBridge')
            second = GameChatBridge(25565, protocol, None, None, name='LobbyBridge')
            self.assertEqual(first.name, 'LobbyBridge')
            self.assertEqual(first.uuid, second.uuid)
            with self.assertRaisesRegex(ValueError, '英文字母'):
                GameChatBridge(25565, protocol, None, None, name='聊天助手')


if __name__ == '__main__':
    unittest.main()
