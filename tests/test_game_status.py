"""Minecraft status/pong measurements must preserve counts when pong is absent."""
import asyncio
import json
import unittest

from hookup.rooms import game_status, read_varint, varint


class GameStatusTests(unittest.IsolatedAsyncioTestCase):
    async def server(self, *, status_delay=0, pong_delay=0, pong='valid', status=None):
        self.writers = []
        self.handshakes = 0
        async def handle(reader, writer):
            self.writers.append(writer)
            try:
                handshake = await reader.readexactly(await read_varint(reader))
                self.assertEqual(handshake[0], 0)
                self.handshakes += 1
                self.assertEqual(await reader.readexactly(2), b'\x01\x00')
                await asyncio.sleep(status_delay)
                body = json.dumps(status if status is not None else dict(
                    version=dict(name='1.21.8', protocol=772), players=dict(online=7, max=20))).encode()
                packet = b'\x00' + varint(len(body)) + body
                writer.write(varint(len(packet)) + packet)
                await writer.drain()
                self.assertEqual(await reader.readexactly(2), b'\x09\x01')
                nonce = await reader.readexactly(8)
                if pong == 'absent':
                    await reader.read()
                else:
                    await asyncio.sleep(pong_delay)
                    writer.write(b'\x09\x01' + (nonce if pong == 'valid' else bytes(8)))
                    await writer.drain()
            except (ConnectionError, asyncio.IncompleteReadError):
                pass
            finally:
                writer.close()
        server = await asyncio.start_server(handle, '127.0.0.1', 0)
        async def cleanup():
            server.close()
            await server.wait_closed()
            for writer in self.writers:
                writer.close()
            await asyncio.gather(*(w.wait_closed() for w in self.writers), return_exceptions=True)
        self.addAsyncCleanup(cleanup)
        return server.sockets[0].getsockname()[1]

    async def test_latency_measures_matching_game_pong_after_status(self):
        port = await self.server(status_delay=.15, pong_delay=.04)
        info = await game_status(port, timeout=2)
        self.assertEqual(info['players'], dict(online=7, max=20))
        self.assertEqual(info['version'], '1.21.8')
        self.assertGreaterEqual(info['latency_ms'], 30)
        self.assertLess(info['latency_ms'], 140)  # Status and handshake delay are excluded.

    async def test_missing_pong_keeps_slow_but_valid_status_without_legacy_retry(self):
        port = await self.server(status_delay=.38, pong='absent')
        info = await game_status(port, timeout=1)
        self.assertEqual(info['players']['online'], 7)
        self.assertIsNone(info['latency_ms'])
        self.assertEqual(self.handshakes, 1)

    async def test_wrong_pong_is_not_reported_as_latency(self):
        port = await self.server(pong='wrong')
        info = await game_status(port, timeout=1)
        self.assertEqual(info['protocol'], 772)
        self.assertIsNone(info['latency_ms'])

    async def test_missing_players_remain_unknown(self):
        port = await self.server(status=dict(version=dict(name='private', protocol=772)))
        info = await game_status(port, timeout=1)
        self.assertEqual(info['players'], {})


if __name__ == '__main__':
    unittest.main()
