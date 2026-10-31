"""Real HTTP fallback preserves pack URLs, exact bytes, and hash validation."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch
from core.downloads import MinecraftDownloader, DownloadSourcesExhausted


class PackDownloadFallbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.hits = []
        self.payload = b'exact original mod bytes'
        hits, payload = self.hits, self.payload
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                hits.append(self.path)
                if self.path == '/unavailable.jar':
                    self.send_error(404)
                    return
                body = b'wrong version' if self.path == '/wrong.jar' else payload
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.base = f'http://127.0.0.1:{server.server_port}'
        self.downloader = MinecraftDownloader(self.temp.name, retries=0)
        self.downloader.preserve_content_order = True
        self.downloader.fallback_content_sources = True

    def fetch(self, url):
        return self.downloader.fetch(self.base + url, 'mods/original.jar',
            hashlib.sha1(self.payload).hexdigest(), len(self.payload))

    def test_working_pack_address_never_resolves_or_downloads_alternatives(self):
        with patch('core.content_routes.resolve_download_urls') as resolve:
            path = self.fetch('/original.jar')
        resolve.assert_not_called()
        self.assertEqual(Path(path).read_bytes(), self.payload)
        self.assertEqual(self.hits, ['/original.jar'])

    def test_failed_original_uses_settings_fallback_once_and_reuses_verified_file(self):
        with patch('core.content_routes.resolve_download_urls', return_value=[
                self.base + '/unavailable.jar', self.base + '/fallback.jar']) as resolve:
            path = self.fetch('/unavailable.jar')
            self.fetch('/unavailable.jar')
        resolve.assert_called_once()
        self.assertEqual(self.hits, ['/unavailable.jar', '/fallback.jar'])
        self.assertEqual(Path(path).read_bytes(), self.payload)

    def test_fallback_cannot_replace_required_mod_with_wrong_bytes(self):
        with patch('core.content_routes.resolve_download_urls', return_value=[self.base + '/wrong.jar']):
            with self.assertRaises(DownloadSourcesExhausted):
                self.fetch('/unavailable.jar')
        self.assertFalse((Path(self.temp.name) / 'mods/original.jar').exists())
