"""Real HTTP downloads must verify bytes before replacing installed files."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/buggcraft'))
from core.downloads import MinecraftDownloader, DownloadCancelled, _DownloadSession
import requests


class DownloadTransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.payload = bytes(range(256)) * 1024
        self.requests = []
        self.ranges = []
        self.mode = ''
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                fixture.requests.append(self.path)
                fixture.ranges.append(self.headers.get('Range'))
                offset = 0
                if fixture.mode and len(fixture.requests) > 1 and fixture.mode != 'ignore-range':
                    offset = int(self.headers['Range'].split('=')[1].rstrip('-')) if self.headers.get('Range') else 0
                self.send_response(206 if offset else 200)
                if offset:
                    start = 0 if fixture.mode == 'bad-range' else offset
                    self.send_header('Content-Range', f'bytes {start}-{len(fixture.payload)-1}/{len(fixture.payload)}')
                self.send_header('Content-Length', str(len(fixture.payload) - offset))
                self.end_headers()
                if fixture.mode and len(fixture.requests) == 1:
                    self.wfile.write(fixture.payload[:65536])
                    self.close_connection = True
                else:
                    self.wfile.write(fixture.payload[offset:])

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)
        self.proxy = patch.dict(os.environ, {'NO_PROXY': '127.0.0.1', 'no_proxy': '127.0.0.1'})
        self.proxy.start()
        self.addCleanup(self.proxy.stop)
        self.downloader = MinecraftDownloader(self.temp.name, source='官方')
        self.addCleanup(self.close_session)
        self.url = f'http://127.0.0.1:{self.server.server_port}/artifact'

    def close_session(self):
        session = getattr(self.downloader._sessions, 'session', None)
        if session:
            session.close()

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)

    def test_download_verified_cache_and_corrupt_cache_repair(self):
        digest = hashlib.sha1(self.payload).hexdigest()
        path = self.downloader.fetch(self.url, 'libraries/test.jar', digest, len(self.payload))
        self.assertEqual(path.read_bytes(), self.payload)
        self.assertEqual(self.requests, ['/artifact'])
        self.assertEqual(self.downloader.fetch(self.url, 'libraries/test.jar', digest), path)
        self.assertEqual(len(self.requests), 1)
        path.write_bytes(b'corrupt local copy')
        self.downloader.fetch(self.url, 'libraries/test.jar', digest, len(self.payload))
        self.assertEqual(path.read_bytes(), self.payload)
        self.assertEqual(len(self.requests), 2)

    def test_rejected_hash_never_replaces_existing_file_and_removes_partial(self):
        path = Path(self.temp.name) / 'existing.jar'
        path.write_bytes(b'previous installed file')
        with self.assertRaises(RuntimeError):
            self.downloader.fetch(self.url, 'existing.jar', '0' * 40, len(self.payload))
        self.assertEqual(len(self.requests), 3)
        self.assertEqual(path.read_bytes(), b'previous installed file')
        self.assertFalse(path.with_name(path.name + '.buggcraft-part').exists())

    def test_path_escape_is_rejected_before_any_network_request(self):
        with self.assertRaises(ValueError):
            self.downloader.fetch(self.url, '../outside.jar')
        self.assertEqual(self.requests, [])

    def test_interrupted_transfer_resumes_and_verifies_both_hashes(self):
        self.mode = 'resume'
        progress = []
        path = self.downloader.fetch(self.url, 'pack.mrpack', hashlib.sha1(self.payload).hexdigest(),
            len(self.payload), sha512=hashlib.sha512(self.payload).hexdigest(),
            file_progress=lambda done, total: progress.append((done, total)))
        self.assertEqual(path.read_bytes(), self.payload)
        self.assertEqual(self.ranges, [None, 'bytes=65536-'])
        self.assertEqual(progress[-1], (len(self.payload), len(self.payload)))
        self.assertFalse(path.with_name(path.name + '.buggcraft-part').exists())

    def test_server_ignoring_range_restarts_without_duplicating_bytes(self):
        self.mode = 'ignore-range'
        path = self.downloader.fetch(self.url, 'pack.zip', hashlib.sha1(self.payload).hexdigest(), len(self.payload))
        self.assertEqual(path.read_bytes(), self.payload)
        self.assertEqual(self.ranges, [None, 'bytes=65536-'])

    def test_incorrect_range_is_discarded_before_clean_retry(self):
        self.mode = 'bad-range'
        path = self.downloader.fetch(self.url, 'pack.zip', hashlib.sha1(self.payload).hexdigest(), len(self.payload))
        self.assertEqual(path.read_bytes(), self.payload)
        self.assertEqual(self.ranges, [None, 'bytes=65536-', None])

    def test_sha512_failure_preserves_previous_file_even_when_sha1_matches(self):
        path = Path(self.temp.name) / 'pack.zip'
        path.write_bytes(b'previous')
        with self.assertRaisesRegex(RuntimeError, '校验失败'):
            self.downloader.fetch(self.url, 'pack.zip', hashlib.sha1(self.payload).hexdigest(),
                                  len(self.payload), sha512='0' * 128)
        self.assertEqual(path.read_bytes(), b'previous')
        self.assertFalse(path.with_name(path.name + '.buggcraft-part').exists())

    def test_content_routing_honors_setting_and_preserves_encoded_path(self):
        urls = ['https://cdn.modrinth.com/data/id/version/a%2Bb.jar?x=1',
                'https://edge.forgecdn.net/files/123/4/a%20b.jar',
                'https://mediafilez.forgecdn.net/files/123/4/a%20b.jar']
        for setting in ('自动', 'BMCLAPI', '自动（官方优先，失败切换镜像）'):
            self.downloader.source = setting
            for url in urls:
                routed = self.downloader.urls(url)
                self.assertTrue(routed[0].startswith('https://mod.mcimirror.top/'))
                self.assertIn(url, routed)
                self.assertEqual(urlsplit(routed[0]).path, urlsplit(url).path)
        self.downloader.source = '官方'
        for url in urls:
            self.assertEqual(self.downloader.urls(url)[0], url)
        self.downloader.source = 'BMCLAPI'
        for url in ('https://cdn.modrinth.com.evil.org/x', 'https://user@cdn.modrinth.com/x',
                    'https://cdn.modrinth.com:444/x', 'https://github.com/a/b/releases/download/x.jar'):
            self.assertEqual(self.downloader.urls(url), [url])

    def test_cancel_after_partial_download_removes_partial_and_preserves_installed_file(self):
        path = Path(self.temp.name) / 'pack.zip'
        path.write_bytes(b'previous')
        def cancel(done, total):
            self.downloader.cancel.set()
        with self.assertRaises(DownloadCancelled):
            self.downloader.fetch(self.url, 'pack.zip', hashlib.sha1(self.payload).hexdigest(),
                                  len(self.payload), file_progress=cancel)
        self.assertEqual(path.read_bytes(), b'previous')
        self.assertFalse(path.with_name(path.name + '.buggcraft-part').exists())

    def test_rejected_mirror_falls_back_once_and_cools_down_for_later_files(self):
        self.downloader.source = 'BMCLAPI'
        original = _DownloadSession.get
        hosts = []
        def get(session, url, **kwargs):
            hosts.append(urlsplit(url).hostname)
            if urlsplit(url).hostname == 'mod.mcimirror.top':
                response = requests.Response()
                response.status_code = 567
                response.url = url
                raise requests.HTTPError('mirror refused', response=response)
            return original(session, self.url, **kwargs)
        with patch.object(_DownloadSession, 'get', get):
            for name in ('one.zip', 'two.zip'):
                self.downloader.fetch('https://cdn.modrinth.com/data/' + name, name,
                                      hashlib.sha1(self.payload).hexdigest(), len(self.payload))
        self.assertEqual(hosts, ['mod.mcimirror.top', 'cdn.modrinth.com', 'cdn.modrinth.com'])


if __name__ == '__main__':
    unittest.main()
