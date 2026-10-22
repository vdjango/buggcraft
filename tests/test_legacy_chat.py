"""Legacy framing boundaries must stay aligned after non-chat packets."""
import asyncio
import json
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / '.test-tools'), str(ROOT / 'buggcraft/src/buggcraft')]
from hookup.game_chat import plain
from hookup.legacy_chat import LegacyReader, MAX_FIELD, text


class LegacyChatTests(unittest.IsolatedAsyncioTestCase):
    def reader(self, payload):
        stream = asyncio.StreamReader()
        stream.feed_data(payload)
        stream.feed_eof()
        return LegacyReader(stream)

    async def test_conditional_team_and_remove_score_packets_do_not_eat_next_chat(self):
        chat = b'\3' + text(json.dumps({'translate':'chat.type.text', 'using':['OldPlayer', '你好']}))
        packets = [b'\xd1' + text('team') + b'\1',
                   b'\xcf' + text('player') + b'\1',
                   b'\xd1' + text('team') + b'\3' + b'\0\1' + text('player')]
        for prefix in packets:
            with self.subTest(prefix=prefix):
                reader = self.reader(prefix + chat)
                await reader.packet()
                packet_id, fields = await reader.packet()
                self.assertEqual(packet_id, 3)
                self.assertEqual(plain(json.loads(fields['message'])), '<OldPlayer> 你好')

    async def test_negative_or_unbounded_lengths_fail_before_reading(self):
        for body in (struct.pack('>i', -1), struct.pack('>i', MAX_FIELD + 1)):
            with self.subTest(body=body), self.assertRaises(ValueError):
                await self.reader(body).field('byteArray32')
        with self.assertRaises(ValueError):
            await self.reader(b'\xff').field('entityMetadata')

    async def test_truncated_packet_is_explicit(self):
        with self.assertRaises(asyncio.IncompleteReadError):
            await self.reader(b'\3\0\4x').packet()


if __name__ == '__main__':
    unittest.main()
