"""Saved download limits and real HTTP file concurrency."""
import hashlib
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / 'buggcraft'))
from config.downloads import download_concurrency, normalize_concurrency
from config.settings import SettingsManager
from core.content import download_content
from core.downloads import MinecraftDownloader, use_download_budget


class DownloadConcurrencyTests(unittest.TestCase):
    def test_nested_install_keeps_the_outer_task_budget(self):
        with tempfile.TemporaryDirectory() as root, use_download_budget(2) as outer:
            with use_download_budget() as nested:
                self.assertIs(nested, outer)
                self.assertIs(MinecraftDownloader(root).budget, outer)
                self.assertEqual(MinecraftDownloader(root).workers, 2)

    def test_completed_slot_refills_before_slower_files_finish(self):
        with tempfile.TemporaryDirectory() as root:
            downloader = MinecraftDownloader(root, workers=3)
            release_slow = threading.Event()
            replacement_started = threading.Event()

            def fetch(_self, _url, relative, *_args):
                if relative.startswith('slow'):
                    if not release_slow.wait(3):
                        raise AssertionError('slow files were not released')
                elif relative == 'replacement':
                    replacement_started.set()
                return Path(root) / relative

            jobs = [('https://example.test/' + name, name, None, None)
                    for name in ('slow-1', 'slow-2', 'fast', 'replacement')]
            with patch.object(MinecraftDownloader, 'fetch', fetch), ThreadPoolExecutor(max_workers=1) as pool:
                result = pool.submit(downloader._batch, jobs, 'test refill')
                try:
                    self.assertTrue(replacement_started.wait(2), 'an empty slot must refill immediately')
                finally:
                    release_slow.set()
                result.result(timeout=3)

    def test_game_core_libraries_and_assets_start_in_same_pool(self):
        with tempfile.TemporaryDirectory() as root:
            downloader = MinecraftDownloader(root, workers=3)
            payload = b'asset'
            digest = hashlib.sha1(payload).hexdigest()
            index = {'objects': {'sounds/test': {'hash': digest, 'size': len(payload)}}}
            barrier = threading.Barrier(3)
            started = []
            lock = threading.Lock()

            def fetch(instance, _url, relative, *_args, **_kwargs):
                path = instance.inside(relative)
                path.parent.mkdir(parents=True, exist_ok=True)
                if relative.startswith('assets/indexes/'):
                    import json
                    path.write_text(json.dumps(index), encoding='utf-8')
                else:
                    with lock:
                        started.append(relative)
                    barrier.wait(timeout=2)
                    path.write_bytes(payload)
                return path

            metadata = {'id': 'test', 'downloads': {'client': {'url': 'https://game.test/client'}},
                        'libraries': [{'downloads': {'artifact': {
                            'url': 'https://libraries.test/library', 'path': 'example/library.jar'}}}],
                        'assetIndex': {'id': 'test', 'url': 'https://assets.test/index'}}
            with patch.object(MinecraftDownloader, 'fetch', fetch):
                downloader.install_metadata('test', metadata)
            self.assertEqual(len(started), 3)
            self.assertTrue(any(path.startswith('versions/') for path in started))
            self.assertTrue(any(path.startswith('libraries/') for path in started))
            self.assertTrue(any(path.startswith('assets/objects/') for path in started))

    def test_game_and_content_downloaders_share_task_budget(self):
        with tempfile.TemporaryDirectory() as root, use_download_budget(2):
            game = MinecraftDownloader(Path(root) / 'game')
            content = MinecraftDownloader(Path(root) / 'content')
            active = peak = 0
            lock = threading.Lock()

            def fetch(_self, _url, relative, *_args, **_kwargs):
                nonlocal active, peak
                with lock:
                    active += 1
                    peak = max(peak, active)
                try:
                    time.sleep(.04)
                    return Path(root) / relative
                finally:
                    with lock:
                        active -= 1

            jobs = [('https://example.test/' + str(index), str(index), None, None)
                    for index in range(6)]
            with patch.object(MinecraftDownloader, '_fetch', fetch), ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(game._batch, jobs, 'game')
                second = pool.submit(content._batch, jobs, 'content')
                first.result(timeout=5)
                second.result(timeout=5)
            self.assertEqual(peak, 2)
            self.assertEqual(active, 0)

    def test_invalid_and_old_settings_use_safe_defaults_without_instance_override(self):
        with tempfile.TemporaryDirectory() as root:
            settings = SettingsManager(root)
            settings.current_settings.pop('downloads', None)
            self.assertEqual(download_concurrency(settings), 32)
            for raw, expected in ((None, 32), ('broken', 32), (False, 32),
                                  (float('inf'), 32), (0, 1), (-5, 1), ('3', 3), (9999, 64)):
                with self.subTest(raw=raw):
                    self.assertEqual(normalize_concurrency(raw), expected)
            settings.set_setting('minecraft.version.enable', 'test-instance')
            settings.set_setting('minecraft.setting.test-instance.enable', True)
            settings.set_setting('minecraft.setting.test-instance.downloads.concurrency', 64)
            settings.set_setting('downloads.concurrency', 2)
            settings.save_settings()
            reloaded = SettingsManager(root)
            self.assertEqual(download_concurrency(reloaded), 2)
            with patch('config.settings.get_settings_manager', return_value=reloaded):
                first = MinecraftDownloader(Path(root) / 'game')
                self.assertEqual(first.workers, 2)
                reloaded.set_setting('downloads.concurrency', 4)
                self.assertEqual(first.workers, 2)
                self.assertEqual(MinecraftDownloader(Path(root) / 'game').workers, 4)

    def test_saved_limits_bound_real_http_for_game_and_each_resource_kind(self):
        payload = b'verified concurrent resource' * 2048
        sha1 = hashlib.sha1(payload).hexdigest()
        sha512 = hashlib.sha512(payload).hexdigest()
        lock = threading.Lock()
        active = peak = 0
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                nonlocal active, peak
                with lock:
                    active += 1
                    peak = max(active, peak)
                try:
                    time.sleep(.08)
                    self.send_response(200)
                    self.send_header('Content-Length', str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                finally:
                    with lock:
                        active -= 1
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        server.request_queue_size = 64
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = SettingsManager(root / 'config')
            for workers in (1, 2, 4):
                settings.set_setting('downloads.concurrency', workers)
                settings.save_settings()
                settings = SettingsManager(root / 'config')
                for kind, folder in (('game', 'libraries'), ('modpack', 'modpacks'),
                                     ('mod', 'mods'), ('resourcepack', 'resourcepacks'),
                                     ('shader', 'shaderpacks')):
                    with self.subTest(workers=workers, kind=kind):
                        active = peak = 0
                        destination = root / f'{kind}-{workers}'
                        suffix = '.jar' if kind in ('game', 'mod') else '.zip'
                        count = 8 if kind in ('game', 'modpack') else 1
                        files = [dict(filename=f'resource-{index}{suffix}',
                                      url=f'https://cdn.modrinth.com/resource-{index}{suffix}',
                                      hashes=dict(sha1=sha1, sha512=sha512), size=len(payload))
                                 for index in range(count)]
                        with patch('config.settings.get_settings_manager', return_value=settings), \
                                patch.object(MinecraftDownloader, 'urls',
                                             lambda _self, url: [f'http://127.0.0.1:{server.server_port}/' + Path(url).name]):
                            if kind == 'game':
                                downloader = MinecraftDownloader(destination)
                                downloader._batch([(item['url'], folder + '/' + item['filename'],
                                                    sha1, len(payload)) for item in files], 'test libraries')
                            else:
                                # Mods, resource packs and shaders each select one
                                # primary artifact; modpacks may contain many files.
                                download_content(dict(files=files), destination, kind)
                        self.assertEqual(active, 0)
                        self.assertEqual(peak, min(workers, count))
                        self.assertEqual(len(list((destination / folder).iterdir())), count)
                        for item in files:
                            self.assertEqual((destination / folder / item['filename']).read_bytes(), payload)
                        print(f'HTTP {kind} configured={workers} peak={peak} verified={count}/{count}', flush=True)
