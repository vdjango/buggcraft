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

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/buggcraft'))
from core.downloads import MinecraftDownloader


class DownloadTransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.payload = bytes(range(256)) * 1024
        self.requests = []
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                fixture.requests.append(self.path)
                self.send_response(200)
                self.send_header('Content-Length', str(len(fixture.payload)))
                self.end_headers()
                self.wfile.write(fixture.payload)

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


if __name__ == '__main__':
    unittest.main()
