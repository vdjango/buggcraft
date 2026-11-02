"""Real HTTP fallback, public reads, checkpoint reuse and pack repair."""
import asyncio
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import requests

from hookup.room_cache import RoomCacheClient, host_metadata, publish
from core import client_file_source


class RoomCacheClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_direct_upload_does_not_forward_room_token_and_requires_verified_receipt(self):
        import base64
        from contextlib import nullcontext
        from unittest.mock import Mock
        ticket = dict(id='a'*32,method='PUT',url='https://cloud.example.test/object?signature=limited',
            expires_at=time.time()+300,headers={'Content-Type':'application/octet-stream',
                'Content-Length':str(self.item['size']),
                'x-amz-checksum-sha256':base64.b64encode(bytes.fromhex(self.item['sha256'])).decode()})
        put = Mock(status_code=200)
        receipt = Mock()
        receipt.json.return_value={'files':[dict(id=ticket['id'],state='cached',sha256=self.item['sha256'],size=self.item['size'])]}
        session = Mock()
        session.put.return_value=nullcontext(put)
        grant=dict(url='https://origin.example.test',token='room-secret',expires_at=time.time()+300)
        with patch('hookup.room_cache.requests.Session',return_value=nullcontext(session)), \
                patch.object(self.cache,'authorize',new=AsyncMock(return_value=grant)), \
                patch.object(self.cache,'request',return_value=nullcontext(receipt)) as complete:
            self.assertTrue(await self.cache.upload_direct(ticket,self.item,self.payload))
            headers=session.put.call_args.kwargs['headers']
            self.assertNotIn('Authorization',headers)
            self.assertFalse(session.put.call_args.kwargs['allow_redirects'])
            self.assertEqual(complete.call_args.args[:3],(grant,'POST','/room-cache/uploads/complete'))
            bad=dict(ticket,headers={**ticket['headers'],'x-amz-checksum-sha256':'wrong'})
            self.assertFalse(await self.cache.upload_direct(bad,self.item,self.payload))
            self.assertEqual(session.put.call_count,1)

    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.payload = b'origin verified content\n' * 20000
        self.item = dict(name='example.jar', path='mods/example.jar', size=len(self.payload),
                         sha256=hashlib.sha256(self.payload).hexdigest(), sha1=hashlib.sha1(self.payload).hexdigest())
        self.calls = []
        self.status = 200
        self.redirect_target = 'https://cloud.example.test/cloud/object?signature=test'
        case = self
        class Handler(BaseHTTPRequestHandler):
            def do_PUT(self):
                size = int(self.headers.get('Content-Length', '0'))
                case.upload = (self.path, dict(self.headers), self.rfile.read(size))
                case.endpoint._stopped = True
                self.send_response(200)
                self.send_header('Content-Length', '0')
                self.end_headers()

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
                status = (206 if offset else 200) if self.path.startswith('/cloud/') else (
                    206 if offset and case.status == 200 else case.status)
                self.send_response(status)
                if status == 206:
                    self.send_header('Content-Range', f'bytes {offset}-{len(case.payload)-1}/{len(case.payload)}')
                self.send_header('Content-Length', str(len(case.payload) - offset))
                if status == 307:
                    self.send_header('Location', case.redirect_target)
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

    async def test_expired_object_returns_to_other_sources_without_failure(self):
        self.cache.files[self.item['sha256']] = dict(self.item, action='cached')
        known='https://edge.forgecdn.net/files/1234/567/example.jar'
        self.item['downloads']=[known]
        self.cache.enrich([self.item])
        self.assertEqual(self.item['downloads'],[known])
        self.cache.grant = dict(url='https://origin.example.test', expires_at=9999999999)
        self.status = 404
        self.assertFalse(await self.cache.download(self.item, Path(self.temp.name) / 'content',
                                                  threading.Event(), lambda *_: None))
        self.assertEqual(len(self.calls), 1)

    async def test_cloud_redirect_preserves_signature_range_and_verified_checkpoint(self):
        self.cache.files[self.item['sha256']] = dict(self.item, action='cached')
        self.cache.grant = dict(url='https://origin.example.test', token='host-token', expires_at=9999999999)
        self.status = 307
        target = Path(self.temp.name) / 'content'
        partial = target.with_name('.origin-' + self.item['sha256'] + '.part')
        partial.write_bytes(self.payload[:12345])
        self.assertTrue(await self.cache.download(self.item, target, threading.Event(), lambda *_: None))
        self.assertEqual(target.read_bytes(), self.payload)
        self.assertEqual([call[1] for call in self.calls], [
            '/room-cache/files/' + self.item['sha256'], '/cloud/object?signature=test'])
        self.assertTrue(all(call[2]['Range'] == 'bytes=12345-' for call in self.calls))
        self.assertTrue(all('Authorization' not in call[2] for call in self.calls))
        self.assertFalse(partial.exists())

    async def test_invalid_or_looping_cloud_redirect_falls_back(self):
        self.cache.files[self.item['sha256']] = dict(self.item, action='cached')
        self.cache.grant = dict(url='https://origin.example.test', expires_at=9999999999)
        self.status = 307
        for location in ('http://cloud.example.test/cloud/object',
                         'https://user:password@cloud.example.test/cloud/object',
                         'https://[invalid-host/cloud/object',
                         'https://origin.example.test/room-cache/loop'):
            self.redirect_target = location
            self.calls.clear()
            self.assertFalse(await self.cache.download(self.item, Path(self.temp.name) / 'content',
                                                      threading.Event(), lambda *_: None))
            self.assertLessEqual(len(self.calls), 6)

    async def test_corrupt_cloud_download_preserves_installed_file_and_falls_back(self):
        self.cache.files[self.item['sha256']] = dict(self.item, action='cached')
        self.cache.grant = dict(url='https://origin.example.test', expires_at=9999999999)
        self.status = 307
        self.payload = b'x' * self.item['size']
        target = Path(self.temp.name) / 'content'
        target.write_bytes(b'previous verified file')
        self.assertFalse(await self.cache.download(self.item, target, threading.Event(), lambda *_: None))
        self.assertEqual(target.read_bytes(), b'previous verified file')
        self.assertFalse(target.with_name('.origin-' + self.item['sha256'] + '.part').exists())

    async def test_pack_hash_lookup_is_public_and_ignores_unmatched_size(self):
        original = dict(path=self.item['path'], hashes={'sha1': self.item['sha1']}, size=self.item['size'])
        with patch.object(client_file_source, '_origin', self.base):
            result = await asyncio.to_thread(client_file_source.lookup, [original], threading.Event())
            self.assertEqual(result, {original['path']: self.base + '/room-cache/files/' + self.item['sha256']})
            original['size'] += 1
            self.assertEqual(await asyncio.to_thread(client_file_source.lookup, [original], threading.Event()), {})
        self.assertTrue(all('Authorization' not in call[2] for call in self.calls))

    async def test_pack_repair_accepts_exact_public_mapping_without_a_cached_body(self):
        address='https://edge.forgecdn.net/files/123/456/example.jar'
        payload=json.dumps(dict(protocol='room-content-cache-v1',files=[dict(
            sha1=self.item['sha1'],sha256='',size=self.item['size'],action='redirect',downloads=[address])])).encode()
        class Response:
            def __enter__(self):return self
            def __exit__(self,*_):pass
            def raise_for_status(self):pass
            def iter_content(self,*_):yield payload
        original=dict(path=self.item['path'],hashes={'sha1':self.item['sha1']},size=self.item['size'])
        with patch('core.client_file_source.requests.post',return_value=Response()):
            self.assertEqual(client_file_source.lookup([original],threading.Event()),{original['path']:address})

    async def test_host_sends_only_requested_file_with_visible_progress(self):
        target = Path(self.temp.name) / self.item['path']
        target.parent.mkdir(parents=True)
        target.write_bytes(self.payload)
        events = []
        self.endpoint.role = 'host'
        self.endpoint.room_settings = {'allow_mod_transfer': True}
        self.endpoint.room_info = {'game': {'version': '1.21.1'}}
        self.endpoint.game_directory = self.temp.name
        self.endpoint.session = True
        self.endpoint._stopped = False
        self.endpoint.on_cache_progress = events.append
        grant = {'url': self.base, 'token': 'host-token', 'expires_at': 9999999999}
        real_sleep = asyncio.sleep
        async def fast_sleep(*_):
            await real_sleep(0)
        with patch('hookup.room_cache.client', new=AsyncMock(return_value=self.cache)), \
                patch('hookup.room_cache.host_metadata', return_value=[self.item]), \
                patch('hookup.room_cache.asyncio.sleep', side_effect=fast_sleep), \
                patch.object(self.cache, 'authorize', new=AsyncMock(return_value=grant)), \
                patch.object(self.cache, 'plan', new=AsyncMock(return_value={
                    'state': 'ready', 'upload': [self.item]})):
            await publish(self.endpoint)
        self.assertEqual(self.upload[0], '/room-cache/files/' + self.item['sha256'])
        self.assertEqual(int(self.upload[1]['Content-Length']), len(self.payload))
        self.assertEqual(self.upload[2], self.payload)
        self.assertEqual(events[-1]['state'], 'complete')
        self.assertEqual(events[-1]['bytesDone'], len(self.payload))
        self.assertEqual(events[-1]['summary']['cached'], 1)
        self.assertEqual(events[-1]['summary']['cached_bytes'], len(self.payload))

    async def test_host_hashes_are_reused_and_changed_files_are_rehashed(self):
        from hookup.modpack import manifest
        target = Path(self.temp.name)/self.item['path']
        target.parent.mkdir(parents=True)
        target.write_bytes(self.payload)
        cache = {}
        first = manifest(self.temp.name, include_sha1=True, hash_cache=cache)
        with patch.object(Path, 'open', side_effect=AssertionError('unchanged file was read again')):
            self.assertEqual(manifest(self.temp.name, include_sha1=True, hash_cache=cache), first)
        target.write_bytes(b'x' * len(self.payload))
        changed = manifest(self.temp.name, include_sha1=True, hash_cache=cache)
        self.assertNotEqual(changed[0]['sha256'], first[0]['sha256'])
        self.assertEqual(changed[0]['sha256'], hashlib.sha256(target.read_bytes()).hexdigest())
