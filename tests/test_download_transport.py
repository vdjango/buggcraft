"""Real HTTP downloads must verify bytes before replacing installed files."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/buggcraft'))
from core.downloads import MinecraftDownloader, DownloadCancelled, _DownloadSession, _MirrorHealth
from utils.http_identity import USER_AGENT
import requests


class DownloadTransportTests(unittest.TestCase):
    def test_file_events_report_real_bytes_verification_and_cached_reuse(self):
        events = []
        self.downloader.file_event = events.append
        digest = hashlib.sha1(self.payload).hexdigest()
        self.downloader.fetch(self.url, 'libraries/progress.jar', digest)
        self.assertTrue(any(event['state'] == 'downloading' and event.get('done', 0) > 0
                            and event['total'] == len(self.payload) for event in events))
        self.assertEqual(events[-2]['state'], 'verifying')
        self.assertEqual(events[-1]['state'], 'verified')
        self.assertEqual(events[-1]['done'], len(self.payload))
        self.assertEqual(events[-1]['total'], len(self.payload))
        self.downloader.fetch(self.url, 'libraries/progress.jar', digest)
        self.assertEqual(events[-1]['state'], 'cached')
        self.assertEqual(len(self.requests), 1)

    def test_parallel_file_events_distinguish_same_filename_and_keep_failure_reason(self):
        events = []
        self.downloader.file_event = events.append
        digest = hashlib.sha1(self.payload).hexdigest()
        self.downloader._batch([(self.url, folder + '/same.jar', digest, len(self.payload))
                                for folder in ('libraries', 'mods')], 'parallel fixture')
        completed = [event for event in events if event['state'] == 'verified']
        self.assertEqual(len(completed), 2)
        self.assertNotEqual(completed[0]['key'], completed[1]['key'])
        with patch.object(self.downloader.cancel, 'wait', return_value=False):
            with self.assertRaisesRegex(RuntimeError, '文件校验失败'):
                self.downloader.fetch(self.url, 'broken.jar', '0' * 40, len(self.payload))
        self.assertEqual(events[-1]['state'], 'failed')
        self.assertIn('文件校验失败', events[-1]['error'])
        self.assertFalse((Path(self.temp.name) / 'broken.jar').exists())

    def test_cancelled_file_event_is_terminal_and_partial_file_is_removed(self):
        events = []
        def receive(event):
            events.append(event)
            if event['state'] == 'downloading' and event.get('done', 0) > 0:
                self.downloader.cancel.set()
        self.downloader.file_event = receive
        with self.assertRaises(DownloadCancelled):
            self.downloader.fetch(self.url, 'cancel.jar', hashlib.sha1(self.payload).hexdigest(), len(self.payload))
        self.assertEqual(events[-1]['state'], 'cancelled')
        self.assertFalse(list(Path(self.temp.name).rglob('*.buggcraft-part')))

    def test_parallel_tasks_share_one_verified_target_without_part_file_races(self):
        from concurrent.futures import ThreadPoolExecutor
        second = MinecraftDownloader(self.temp.name, source='官方')
        digest = hashlib.sha1(self.payload).hexdigest()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(downloader.fetch, self.url, 'shared/mod.jar', digest, len(self.payload))
                       for downloader in (self.downloader, second)]
            paths = [future.result(timeout=5) for future in futures]
        self.assertEqual(paths[0], paths[1])
        self.assertEqual(paths[0].read_bytes(), self.payload)
        self.assertEqual(self.requests, ['/artifact'])
        self.assertFalse(list(Path(self.temp.name).rglob('*.buggcraft-part')))

    def setUp(self):
        health = patch('core.downloads._CONTENT_HEALTH', _MirrorHealth())
        health.start()
        self.addCleanup(health.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.payload = bytes(range(256)) * 1024
        self.requests = []
        self.ranges = []
        self.user_agents = []
        self.mode = ''
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                fixture.requests.append(self.path)
                fixture.ranges.append(self.headers.get('Range'))
                fixture.user_agents.append(self.headers.get('User-Agent'))
                if self.path == '/redirect':
                    self.send_response(302)
                    self.send_header('Location', '/artifact')
                    self.end_headers()
                    return
                if self.path in ('/segments', '/ignore-segments', '/bad-segments'):
                    header = self.headers.get('Range')
                    start, end = 0, len(fixture.payload) - 1
                    if header and self.path != '/ignore-segments':
                        start, end = map(int, header[6:].split('-'))
                    if header and getattr(fixture, 'range_barrier', None):
                        fixture.range_barrier.wait(timeout=5)
                    self.send_response(206 if header and self.path != '/ignore-segments' else 200)
                    self.send_header('Accept-Ranges', 'bytes')
                    self.send_header('Content-Length', str(end - start + 1))
                    if header and self.path != '/ignore-segments':
                        reported_start = start + 1 if self.path == '/bad-segments' else start
                        self.send_header('Content-Range', f'bytes {reported_start}-{end}/{len(fixture.payload)}')
                    self.end_headers()
                    try:
                        self.wfile.write(fixture.payload[start:end + 1])
                    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                        pass
                    return
                offset = 0
                if fixture.mode and len(fixture.requests) > 1 and fixture.mode != 'ignore-range':
                    offset = int(self.headers['Range'].split('=')[1].rstrip('-')) if self.headers.get('Range') else 0
                self.send_response(206 if offset else 200)
                if offset:
                    start = 0 if fixture.mode == 'bad-range' else offset
                    self.send_header('Content-Range', f'bytes {start}-{len(fixture.payload)-1}/{len(fixture.payload)}')
                self.send_header('Content-Length', str(len(fixture.payload) - offset))
                self.end_headers()
                if self.path == '/trickle':
                    for offset in range(0, len(fixture.payload), 1024):
                        try:
                            self.wfile.write(fixture.payload[offset:offset + 1024])
                            self.wfile.flush()
                        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                            break
                        time.sleep(0.03)
                    return
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

    def test_public_launcher_identity_survives_redirects_and_range_retries(self):
        release = (Path(__file__).resolve().parents[1] / 'resources/app-version.txt').read_text(encoding='ascii').strip()
        self.assertEqual(USER_AGENT, 'BUGG | ' + release)
        url = self.url.replace('/artifact', '/redirect')
        target = self.downloader.fetch(url, 'redirect.jar', hashlib.sha1(self.payload).hexdigest(), len(self.payload))
        self.assertEqual(target.read_bytes(), self.payload)
        self.assertEqual(self.requests, ['/redirect', '/artifact'])
        self.assertEqual(self.user_agents, [USER_AGENT, USER_AGENT])
        self.requests.clear()
        self.mode = 'resume'
        self.downloader.fetch(self.url, 'retry.jar', hashlib.sha1(self.payload).hexdigest(), len(self.payload))
        self.assertEqual(self.ranges[-2:], [None, 'bytes=65536-'])
        self.assertTrue(all(value == USER_AGENT for value in self.user_agents))

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
                'https://edge.forgecdn.net/files/123/4/a%20b.jar']
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
        # MCIM explicitly excludes mediafilez; retain its authenticated route.
        media = 'https://mediafilez.forgecdn.net/files/123/4/a%20b.jar'
        self.assertEqual(self.downloader.urls(media), [media, media.replace('mediafilez.', 'edge.')])
        self.downloader.content_source = '官方'
        self.assertEqual(self.downloader.urls(urls[0])[0], urls[0])
        self.downloader.source = '官方'
        self.downloader.content_source = 'MCIM'
        self.assertTrue(self.downloader.urls(urls[0])[0].startswith('https://mod.mcimirror.top/'))
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

    def test_unresponsive_mirror_tries_once_then_uses_publisher(self):
        self.downloader.content_source = 'MCIM'
        original = _DownloadSession.get
        calls, statuses = [], []
        self.downloader.status = statuses.append
        def get(session, url, **kwargs):
            calls.append((urlsplit(url).hostname, kwargs['timeout']))
            if urlsplit(url).hostname == 'mod.mcimirror.top':
                raise requests.ReadTimeout('no first byte from mirror')
            return original(session, self.url, **kwargs)
        with patch.object(_DownloadSession, 'get', get):
            for name in ('one.mrpack', 'two.mrpack'):
                result = self.downloader.fetch('https://cdn.modrinth.com/data/' + name, name,
                    hashlib.sha1(self.payload).hexdigest(), len(self.payload))
                self.assertEqual(result.read_bytes(), self.payload)
        self.assertEqual(calls, [('mod.mcimirror.top', (3, 4)), ('cdn.modrinth.com', (8, 30)),
                                 ('cdn.modrinth.com', (8, 30))])
        self.assertTrue(any('切换原站' in value for value in statuses))

    def test_mirror_outage_is_shared_across_independent_download_tasks(self):
        original = _DownloadSession.get
        hosts = []
        def get(session, url, **kwargs):
            hosts.append(urlsplit(url).hostname)
            if hosts[-1] == 'mod.mcimirror.top':
                raise requests.ReadTimeout('mirror unavailable')
            return original(session, self.url, **kwargs)
        with patch.object(_DownloadSession, 'get', get):
            for name in ('first.jar', 'second.jar'):
                downloader = MinecraftDownloader(self.temp.name)
                downloader.content_source = 'MCIM'
                path = downloader.fetch('https://cdn.modrinth.com/data/' + name, name,
                                        hashlib.sha1(self.payload).hexdigest(), len(self.payload))
                self.assertEqual(path.read_bytes(), self.payload)
                downloader._sessions.session.close()
        self.assertEqual(hosts, ['mod.mcimirror.top', 'cdn.modrinth.com', 'cdn.modrinth.com'])

    def test_mirror_html_error_with_success_status_is_rejected_before_streaming(self):
        original = _DownloadSession.get
        html = MagicMock()
        html.__enter__.return_value = html
        html.status_code, html.url = 200, 'https://mod.mcimirror.top/data/test.jar'
        html.headers = {'Content-Type': 'text/html; charset=utf-8'}
        hosts = []
        def get(session, url, **kwargs):
            hosts.append(urlsplit(url).hostname)
            return html if hosts[-1] == 'mod.mcimirror.top' else original(session, self.url, **kwargs)
        self.downloader.content_source = 'MCIM'
        with patch.object(_DownloadSession, 'get', get):
            path = self.downloader.fetch(html.url, 'test.jar', hashlib.sha1(self.payload).hexdigest(), len(self.payload))
        self.assertEqual(path.read_bytes(), self.payload)
        html.iter_content.assert_not_called()
        self.assertEqual(hosts, ['mod.mcimirror.top', 'cdn.modrinth.com'])

    def test_mirror_cooldown_expires_and_allows_a_new_probe(self):
        health = _MirrorHealth()
        with patch('core.downloads.time.monotonic', return_value=100):
            health.pause()
            self.assertTrue(health.blocked())
        with patch('core.downloads.time.monotonic', return_value=161):
            self.assertFalse(health.blocked())

    def large_content(self, endpoint, progress):
        self.payload = bytes(range(256)) * 32768
        original = _DownloadSession.get
        def get(session, url, **kwargs):
            return original(session, self.url.replace('/artifact', endpoint), **kwargs)
        with patch.object(_DownloadSession, 'get', get):
            return self.downloader.fetch('https://cdn.modrinth.com/data/large.zip', 'large.zip',
                hashlib.sha1(self.payload).hexdigest(), len(self.payload),
                sha512=hashlib.sha512(self.payload).hexdigest(), file_progress=progress)

    def test_large_resource_uses_four_concurrent_ranges_and_verifies_joined_bytes(self):
        self.downloader.workers = 8
        self.range_barrier = threading.Barrier(4)
        progress = []
        path = self.large_content('/segments', lambda done, total: progress.append((done, total)))
        self.assertEqual(path.read_bytes(), self.payload)
        self.assertEqual(len(self.requests), 5)
        self.assertCountEqual(self.ranges, [None, 'bytes=0-2097151', 'bytes=2097152-4194303',
                                          'bytes=4194304-6291455', 'bytes=6291456-8388607'])
        self.assertEqual(progress[-1], (len(self.payload), len(self.payload)))
        self.assertFalse(list(Path(self.temp.name).glob('*.buggcraft-part*')))

    def test_single_download_setting_disables_ranges_and_two_limits_segments(self):
        for workers in (1, 2):
            with self.subTest(workers=workers):
                self.downloader.workers = workers
                self.requests.clear()
                self.ranges.clear()
                path = self.large_content('/segments', lambda done, total: None)
                self.assertEqual(path.read_bytes(), self.payload)
                self.assertEqual(len(self.requests), 1 if workers == 1 else 3)
                self.assertEqual(sum(value is not None for value in self.ranges), 0 if workers == 1 else 2)
                self.assertFalse(list(Path(self.temp.name).glob('*.buggcraft-part*')))
                path.unlink()

    def test_ignored_or_invalid_ranges_fall_back_to_complete_original_stream(self):
        for endpoint in ('/ignore-segments', '/bad-segments'):
            with self.subTest(endpoint=endpoint):
                path = self.large_content(endpoint, lambda done, total: None)
                self.assertEqual(path.read_bytes(), self.payload)
                self.assertFalse(list(Path(self.temp.name).glob('*.buggcraft-part*')))
                path.unlink()

    def test_cancel_parallel_resource_preserves_previous_install_and_cleans_parts(self):
        path = Path(self.temp.name) / 'large.zip'
        path.write_bytes(b'previous installation')
        def cancel(done, total):
            self.downloader.cancel.set()
        with self.assertRaises(DownloadCancelled):
            self.large_content('/segments', cancel)
        self.assertEqual(path.read_bytes(), b'previous installation')
        self.assertFalse(list(Path(self.temp.name).glob('*.buggcraft-part*')))

    def test_slow_mirror_switches_with_range_and_verifies_complete_file(self):
        import itertools
        self.downloader.content_source = 'MCIM'
        calls = []
        def get(session, url, **kwargs):
            host = urlsplit(url).hostname
            offset = int(kwargs['headers'].get('Range', 'bytes=0-')[6:-1])
            calls.append((host, offset))
            response = MagicMock()
            response.__enter__.return_value = response
            response.url = url
            response.status_code = 206 if offset else 200
            response.headers = {'Content-Length': str(len(self.payload) - offset)}
            if offset:
                response.headers['Content-Range'] = f'bytes {offset}-{len(self.payload)-1}/{len(self.payload)}'
            response.iter_content.return_value = iter(self.payload[i:i + 16384]
                                                     for i in range(offset, len(self.payload), 16384))
            return response
        ticks = itertools.count()
        with patch.object(_DownloadSession, 'get', get), patch('core.downloads.time.monotonic', side_effect=lambda: next(ticks)):
            result = self.downloader.fetch('https://cdn.modrinth.com/data/slow.mrpack', 'slow.mrpack',
                hashlib.sha1(self.payload).hexdigest(), len(self.payload), sha512=hashlib.sha512(self.payload).hexdigest())
        self.assertEqual(result.read_bytes(), self.payload)
        self.assertEqual(calls, [('mod.mcimirror.top', 0), ('cdn.modrinth.com', 65536)])
        self.assertFalse(list(Path(self.temp.name).glob('*.buggcraft-part')))

    def test_fast_mirror_does_not_start_duplicate_official_download(self):
        self.downloader.content_source = 'MCIM'
        original = _DownloadSession.get
        hosts = []
        def get(session, url, **kwargs):
            hosts.append(urlsplit(url).hostname)
            return original(session, self.url, **kwargs)
        with patch.object(_DownloadSession, 'get', get):
            self.downloader.fetch('https://cdn.modrinth.com/data/fast.zip', 'fast.zip',
                hashlib.sha1(self.payload).hexdigest(), len(self.payload))
        self.assertEqual(hosts, ['mod.mcimirror.top'])

    def test_real_trickle_stream_switches_before_completing_slow_mirror(self):
        self.downloader.content_source = 'MCIM'
        original = _DownloadSession.get
        hosts = []
        self.mode = 'range'
        def get(session, url, **kwargs):
            host = urlsplit(url).hostname
            hosts.append(host)
            address = self.url.replace('/artifact', '/trickle') if host == 'mod.mcimirror.top' else self.url
            return original(session, address, **kwargs)
        started = time.monotonic()
        with patch.object(_DownloadSession, 'get', get):
            result = self.downloader.fetch('https://cdn.modrinth.com/data/trickle.mrpack', 'trickle.mrpack',
                hashlib.sha1(self.payload).hexdigest(), len(self.payload))
        self.assertEqual(result.read_bytes(), self.payload)
        self.assertEqual(hosts, ['mod.mcimirror.top', 'cdn.modrinth.com'])
        self.assertIsNone(self.ranges[0])
        self.assertTrue(self.ranges[1].startswith('bytes='))
        self.assertLess(time.monotonic() - started, 7)

    def test_mirror_urls_from_cached_manifest_recover_original_fallback(self):
        self.downloader.content_source = 'MCIM'
        for path, host in [('/data/project/version/pack.mrpack?x=1', 'cdn.modrinth.com'),
                           ('/files/123/45/pack.zip', 'edge.forgecdn.net')]:
            mirrored = 'https://mod.mcimirror.top' + path
            routed = self.downloader.urls(mirrored)
            self.assertEqual(routed[0], mirrored)
            self.assertEqual(routed[1], 'https://' + host + path)
            self.downloader.content_source = '官方'
            self.assertEqual(self.downloader.urls(mirrored)[0], 'https://' + host + path)
            self.downloader.content_source = 'MCIM'


if __name__ == '__main__':
    unittest.main()
