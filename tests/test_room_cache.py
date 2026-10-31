"""Real HTTP fallback, public reads, checkpoint reuse and pack repair."""
import asyncio
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import requests

from hookup.room_cache import RoomCacheClient
from core import client_file_source


class RoomCacheClientTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.payload = b'origin verified content\n' * 20000
        self.item = dict(name='example.jar', path='mods/example.jar', size=len(self.payload),
                         sha256=hashlib.sha256(self.payload).hexdigest(), sha1=hashlib.sha1(self.payload).hexdigest())
        self.calls = []
        self.status = 200
        case = self
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                case.calls.append(('POST', self.path, dict(self.headers), body))
                data = dict(protocol='room-content-cache-v1', files=[dict(case.item, action='cached')])
                payload = json.dumps(data).encode()
                self.send_response(200)
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_GET(self):
                case.calls.append(('GET', self.path, dict(self.headers), None))
                offset = int(self.headers.get('Range', 'bytes=0-')[6:-1])
                self.send_response(206 if offset else case.status)
                if offset:
                    self.send_header('Content-Range', f'bytes {offset}-{len(case.payload)-1}/{len(case.payload)}')
                self.send_header('Content-Length', str(len(case.payload) - offset))
                if case.status == 307:
                    self.send_header('Location', 'https://edge.forgecdn.net/files/1/2/example.jar')
                self.end_headers()
                try:
                    self.wfile.write(case.payload[offset:])
                except (ConnectionError, OSError):
                    pass

            def log_message(self, *_):
                pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f'http://127.0.0.1:{self.server.server_port}'
        self.endpoint = SimpleNamespace(role='client', room_settings={},
            lobby_request=AsyncMock(return_value=dict(protocol='room-content-cache-v1',
                url='https://origin.example.test', expires_at=9999999999)))
        self.cache = RoomCacheClient(self.endpoint)
        self.cache.request = lambda grant, method, path, **kwargs: RoomCacheClient.request(
            dict(grant, url=self.base), method, path, **kwargs)

    async def test_guest_plan_and_download_never_send_authorization(self):
        with patch.object(client_file_source, '_origin', ''):
            await self.cache.plan(wanted=[self.item['sha256']])
            bare = {key: value for key, value in self.item.items() if key != 'sha1'}
            self.cache.enrich([bare])
            self.assertEqual(bare['sha1'], self.item['sha1'])
            target = Path(self.temp.name) / 'content'
            self.assertTrue(await self.cache.download(self.item, target, threading.Event(), lambda *_: None))
        self.assertEqual(target.read_bytes(), self.payload)
        self.assertTrue(all('Authorization' not in call[2] for call in self.calls))
        self.endpoint.lobby_request.assert_awaited_once_with('content_cache_grant')

    async def test_cancel_then_resume_only_remaining_bytes(self):
        self.cache.files[self.item['sha256']] = dict(self.item, action='cached')
        self.cache.grant = dict(url='https://origin.example.test', token='host-token', expires_at=9999999999)
        self.endpoint.role = 'host'
        target = Path(self.temp.name) / 'content'
        cancel = threading.Event()
        with self.assertRaises(InterruptedError):
            await self.cache.download(self.item, target, cancel, lambda *_: cancel.set())
        partial = target.with_name('.origin-' + self.item['sha256'] + '.part')
        offset = partial.stat().st_size
        self.assertGreater(offset, 0)
        self.assertFalse(target.exists())
        cancel.clear()
        self.assertTrue(await self.cache.download(self.item, target, cancel, lambda *_: None))
        self.assertEqual(self.calls[-1][2]['Range'], f'bytes={offset}-')
        self.assertNotIn('Authorization', self.calls[-1][2])
        self.assertEqual(target.read_bytes(), self.payload)
        self.assertFalse(partial.exists())

    async def test_expired_object_redirect_returns_to_other_sources_without_failure(self):
        self.cache.files[self.item['sha256']] = dict(self.item, action='cached')
        self.cache.grant = dict(url='https://origin.example.test', expires_at=9999999999)
        self.status = 307
        self.assertFalse(await self.cache.download(self.item, Path(self.temp.name) / 'content',
                                                  threading.Event(), lambda *_: None))
        self.assertEqual(len(self.calls), 1)  # No automatic external redirect.

    async def test_pack_hash_lookup_is_public_and_ignores_unmatched_size(self):
        original = dict(path=self.item['path'], hashes={'sha1': self.item['sha1']}, size=self.item['size'])
        with patch.object(client_file_source, '_origin', self.base):
            result = await asyncio.to_thread(client_file_source.lookup, [original], threading.Event())
            self.assertEqual(result, {original['path']: self.base + '/room-cache/files/' + self.item['sha256']})
            original['size'] += 1
            self.assertEqual(await asyncio.to_thread(client_file_source.lookup, [original], threading.Event()), {})
        self.assertTrue(all('Authorization' not in call[2] for call in self.calls))
