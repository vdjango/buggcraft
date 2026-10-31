"""Real HTTP downloads must verify bytes before replacing installed files."""
import hashlib
import io
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from zipfile import ZipFile
from unittest.mock import MagicMock, patch
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/buggcraft'))
from core.downloads import MinecraftDownloader, DownloadCancelled, CONTENT_MIRROR, _DownloadSession, _MirrorHealth, use_shared_download_cache
from utils.http_identity import USER_AGENT
import requests


class DownloadTransportTests(unittest.TestCase):
    def test_all_source_failures_reach_ui_with_each_cause_and_no_raw_transport_dump(self):
        from core.downloads import download_error_message, DownloadSourcesExhausted
        hosts = []
        def get(_session, url, **_kwargs):
            host = urlsplit(url).hostname
            hosts.append(host)
            if host == 'mirror.minguncle.cn':
                response = requests.Response()
                response.status_code = 404
                raise requests.HTTPError(response=response)
            raise requests.Timeout('HTTPSConnectionPool raw transport detail')
        downloader = MinecraftDownloader(self.temp.name, source='BMCLAPI', retries=2)
        with patch.object(_DownloadSession, 'get', get):
            with self.assertRaises(DownloadSourcesExhausted) as raised:
                downloader.fetch('https://libraries.minecraft.net/example.jar', 'libraries/example.jar',
                    hashlib.sha1(self.payload).hexdigest(), len(self.payload))
        message = download_error_message(raised.exception)
        self.assertEqual(hosts, ['bmclapi2.bangbang93.com', 'mirror.minguncle.cn', 'libraries.minecraft.net'])
        self.assertIn('BMCLAPI：连接或读取超时', message)
        self.assertIn('MCMirror：文件不存在（404）', message)
        self.assertIn('Mojang：连接或读取超时', message)
        self.assertNotIn('HTTPSConnectionPool', message)

    def test_cancellation_wakes_blocked_https_body_and_preserves_partial_bytes(self):
        from concurrent.futures import ThreadPoolExecutor
        from datetime import datetime, timedelta, timezone
        import ipaddress
        import ssl
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from core.downloads import DownloadCancellation

        key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, 'localhost')])
        now = datetime.now(timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=1))
                .not_valid_after(now + timedelta(hours=1))
                .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), False)
                .sign(key, hashes.SHA256()))
        certificate, private = Path(self.temp.name) / 'cert.pem', Path(self.temp.name) / 'key.pem'
        certificate.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        private.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                             serialization.NoEncryption()))
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certificate, private)
        started, release = threading.Event(), threading.Event()
        payload = self.payload
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload[:len(payload) // 2])
                self.wfile.flush()
                started.set()
                release.wait(5)
                try:
                    self.wfile.write(payload[len(payload) // 2:])
                except OSError:
                    pass
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.downloader.cancel = cancel = DownloadCancellation()
        original_get = _DownloadSession.get
        def get(session, url, **kwargs):
            return original_get(session, url, verify=str(certificate), **kwargs)
        try:
            with patch.object(_DownloadSession, 'get', get), ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self.downloader.fetch, f'https://127.0.0.1:{server.server_port}/artifact',
                                     'tls-resume.jar', hashlib.sha1(payload).hexdigest(), len(payload))
                self.assertTrue(started.wait(3))
                # Wait for actual disk progress before interrupting the TLS body.
                deadline = time.monotonic() + 2
                part = Path(self.temp.name) / 'tls-resume.jar.buggcraft-part'
                while time.monotonic() < deadline and (not part.exists() or not part.stat().st_size):
                    time.sleep(.01)
                before = time.monotonic()
                cancel.set()
                with self.assertRaises(DownloadCancelled):
                    future.result(timeout=1)
                self.assertLess(time.monotonic() - before, 1)
                self.assertTrue(0 < part.stat().st_size < len(payload))
                self.assertTrue(part.with_name(part.name + '.json').is_file())
        finally:
            release.set()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_launch_library_repair_falls_back_and_emits_byte_progress(self):
        from core import loaders
        events, hosts = [], []
        original_get = _DownloadSession.get
        def get(session, url, **kwargs):
            hosts.append(urlsplit(url).hostname)
            if urlsplit(url).hostname == 'bmclapi2.bangbang93.com':
                raise requests.ConnectionError('mirror unavailable')
            return original_get(session, self.url, **kwargs)
        target = Path(self.temp.name) / 'libraries/gson.jar'
        routed = loaders._routed_downloader(
            lambda *a, **kw: self.fail('repair bypassed the verified downloader'), '自动')
        with patch.object(_DownloadSession, 'get', get):
            routed('https://libraries.minecraft.net/gson.jar', target,
                   callback={'fileEvent': events.append}, sha1=hashlib.sha1(self.payload).hexdigest(),
                   minecraft_directory=self.temp.name)
        self.assertEqual(hosts, ['bmclapi2.bangbang93.com', 'mirror.minguncle.cn'])
        self.assertEqual(target.read_bytes(), self.payload)
        self.assertTrue(any(event['state'] == 'downloading' and event.get('done', 0) > 0
                            and event.get('total') == len(self.payload) for event in events))
        self.assertEqual(events[-1]['state'], 'verified')
        self.assertFalse(list(Path(self.temp.name).rglob('*.buggcraft-part*')))

    def test_install_fetches_core_libraries_assets_logging_and_extracts_natives(self):
        native = io.BytesIO()
        with ZipFile(native, 'w') as archive:
            archive.writestr('fixture-native.dll', b'native library fixture')
        asset = b'real HTTP game asset fixture'
        digest = hashlib.sha1(asset).hexdigest()
        index = json.dumps({'objects': {'minecraft/sounds/fixture.ogg':
            {'hash': digest, 'size': len(asset)}}}).encode()
        base = self.url.rsplit('/', 1)[0]
        payloads = {'/client': b'game core fixture', '/library': b'library fixture',
                    '/native': native.getvalue(), '/index': index, '/logging': b'log config fixture',
                    '/asset': asset}
        self.extra_payloads = payloads
        def artifact(endpoint, **extra):
            payload = payloads[endpoint]
            return dict(url=base + endpoint, sha1=hashlib.sha1(payload).hexdigest(), size=len(payload), **extra)
        metadata = {'id': 'component-fixture', 'downloads': {'client': artifact('/client')},
            'libraries': [{'name': 'fixture:library:1', 'downloads': {
                'artifact': artifact('/library', path='fixture/library.jar'),
                'classifiers': {'natives-fixture': artifact('/native', path='fixture/native.jar')}},
                'natives': {self.downloader.system: 'natives-fixture'}}],
            'assetIndex': artifact('/index', id='fixture'),
            'logging': {'client': {'file': artifact('/logging', id='fixture.xml')}}}
        real_urls = self.downloader.urls
        def urls(url):
            if url.startswith('https://resources.download.minecraft.net/'):
                return [base + '/asset']
            return real_urls(url)
        with patch.object(self.downloader, 'urls', side_effect=urls):
            self.downloader.install_metadata('component-fixture', metadata)
        root = Path(self.temp.name)
        for path, payload in [('versions/component-fixture/component-fixture.jar', payloads['/client']),
                ('libraries/fixture/library.jar', payloads['/library']),
                ('assets/log_configs/fixture.xml', payloads['/logging']),
                (f'assets/objects/{digest[:2]}/{digest}', asset),
                ('versions/component-fixture/natives/fixture-native.dll', b'native library fixture')]:
            self.assertEqual((root / path).read_bytes(), payload, path)
        self.assertTrue((root / 'versions/component-fixture/.buggcraft-complete.json').is_file())
        self.assertCountEqual(self.requests, payloads.keys())

    def test_standalone_repair_preserves_existing_loader_core(self):
        from core.downloads import verified_installation
        root = Path(self.temp.name)
        core = root / 'versions/loader-fixture/loader-fixture.jar'
        core.parent.mkdir(parents=True)
        with ZipFile(core, 'w') as archive:
            archive.writestr('META-INF/MANIFEST.MF', 'Manifest-Version: 1.0')
        original = core.read_bytes()
        metadata = {'id': 'loader-fixture', 'downloads': {'client': {
            'url': self.url, 'sha1': hashlib.sha1(self.payload).hexdigest(),
            'size': len(self.payload)}}, 'libraries': []}
        self.downloader.install_metadata('loader-fixture', metadata, preserve_client=True)
        self.assertEqual(core.read_bytes(), original)
        self.assertEqual(self.requests, [])
        self.assertTrue(verified_installation(root, 'loader-fixture'))

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

    def test_cancelled_file_event_is_terminal_and_partial_file_can_resume(self):
        events = []
        def receive(event):
            events.append(event)
            if event['state'] == 'downloading' and event.get('done', 0) > 0:
                self.downloader.cancel.set()
        self.downloader.file_event = receive
        with self.assertRaises(DownloadCancelled):
            self.downloader.fetch(self.url, 'cancel.jar', hashlib.sha1(self.payload).hexdigest(), len(self.payload))
        self.assertEqual(events[-1]['state'], 'cancelled')
        self.assertTrue(list(Path(self.temp.name).rglob('*.buggcraft-part')))
        downloader = MinecraftDownloader(self.temp.name, source='官方')
        try:
            result = downloader.fetch(self.url, 'cancel.jar', hashlib.sha1(self.payload).hexdigest(), len(self.payload))
        finally:
            downloader._sessions.session.close() if getattr(downloader._sessions, 'session', None) else None
        self.assertEqual(result.read_bytes(), self.payload)
        self.assertFalse(list(Path(self.temp.name).rglob('*.buggcraft-part*')))

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

    def test_parallel_isolated_installs_download_shared_libraries_and_assets_once(self):
        from concurrent.futures import ThreadPoolExecutor
        root = Path(self.temp.name)
        digest = hashlib.sha1(self.payload).hexdigest()
        relatives = ('libraries/example/shared.jar', f'assets/objects/{digest[:2]}/{digest}')
        with use_shared_download_cache(root):
            workers = [MinecraftDownloader(root / name, source='官方') for name in ('first', 'second')]
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(worker.fetch, self.url, relative, digest, len(self.payload))
                       for worker in workers for relative in relatives]
            for future in futures:
                self.assertEqual(future.result(timeout=5).read_bytes(), self.payload)
        self.assertEqual(self.requests, ['/artifact', '/artifact'])
        for relative in relatives:
            self.assertEqual((root / relative).read_bytes(), self.payload)
        # Installed resources outlive either workspace and remain reusable.
        self.requests.clear()
        for relative in relatives:
            self.downloader.fetch(self.url, relative, digest, len(self.payload))
        self.assertEqual(self.requests, [])

    def test_shared_cache_checks_hash_before_reusing_cancelled_workspace_file(self):
        root = Path(self.temp.name)
        relative = 'libraries/example/shared.jar'
        with use_shared_download_cache(root):
            worker = MinecraftDownloader(root / 'workspace', source='官方')
        local = worker.inside(relative)
        local.parent.mkdir(parents=True)
        local.write_bytes(b'broken')
        result = worker.fetch(self.url, relative, hashlib.sha1(self.payload).hexdigest(), len(self.payload))
        self.assertEqual(result.read_bytes(), self.payload)
        self.assertEqual((root / relative).read_bytes(), self.payload)
        self.assertEqual(self.requests, ['/artifact'])

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
                if self.path in getattr(fixture, 'extra_payloads', {}):
                    payload = fixture.extra_payloads[self.path]
                    self.send_response(200)
                    self.send_header('Content-Length', str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return
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
                if fixture.mode and (len(fixture.requests) == 1 or fixture.mode == 'persistent'
                                     or fixture.mode == 'six-interruptions' and len(fixture.requests) <= 6):
                    self.wfile.write(fixture.payload[offset:offset + 65536])
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
        events = []
        self.downloader.file_event = events.append
        target = self.downloader.fetch(url, 'redirect.jar', hashlib.sha1(self.payload).hexdigest(), len(self.payload))
        self.assertEqual(target.read_bytes(), self.payload)
        self.assertEqual(self.requests, ['/redirect', '/artifact'])
        self.assertEqual(self.user_agents, [USER_AGENT, USER_AGENT])
        self.assertEqual([event['url'] for event in events if 'url' in event], [url, self.url])
        self.requests.clear()
        self.mode = 'resume'
        self.downloader.fetch(self.url, 'retry.jar', hashlib.sha1(self.payload).hexdigest(), len(self.payload))
        self.assertEqual(self.ranges[-2:], [None, 'bytes=65536-'])
        self.assertTrue(all(value == USER_AGENT for value in self.user_agents))

    def test_download_address_events_hide_query_credentials_without_changing_the_request(self):
        events = []
        self.downloader.file_event = events.append
        url = self.url + '?token=private-test-token&signature=private-test-signature'
        target = self.downloader.fetch(url, 'signed.jar', hashlib.sha1(self.payload).hexdigest(), len(self.payload))
        self.assertEqual(target.read_bytes(), self.payload)
        self.assertEqual(self.requests, [urlsplit(url).path + '?' + urlsplit(url).query])
        self.assertEqual([event['url'] for event in events if 'url' in event], [self.url])
        self.assertNotIn('private-test-', json.dumps(events))

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

    def test_deep_portable_cache_resumes_and_reuses_verified_artifact(self):
        from utils.path_helper import filesystem_path
        import shutil
        relative = Path('deep-cache') / ('portable-cache-' * 7) / ('loader-library-' * 6) / ('checkpoint-' * 5) / 'artifact.jar'
        expected = Path(self.temp.name).resolve() / relative
        self.assertGreater(len(str(expected)), 260)
        self.mode = 'resume'
        digest = hashlib.sha1(self.payload).hexdigest()
        try:
            actual = self.downloader.fetch(self.url, relative, digest, len(self.payload))
            self.assertEqual(actual, expected)
            self.assertEqual(filesystem_path(actual).read_bytes(), self.payload)
            self.assertEqual(self.ranges, [None, 'bytes=65536-'])
            self.downloader.fetch(self.url, relative, digest, len(self.payload))
            self.assertEqual(len(self.requests), 2)
            self.assertFalse(filesystem_path(str(actual) + '.buggcraft-part.json').exists())
        finally:
            shutil.rmtree(filesystem_path(Path(self.temp.name) / 'deep-cache'), ignore_errors=True)

    def test_six_automatic_retries_resume_without_restarting_or_visible_error(self):
        self.payload = bytes(range(256)) * 2048
        self.mode = 'six-interruptions'
        self.downloader.retries = 6
        events = []
        self.downloader.file_event = events.append
        digest = hashlib.sha1(self.payload).hexdigest()
        with patch.object(self.downloader.cancel, 'wait', return_value=False):
            path = self.downloader.fetch(self.url, 'mod.jar', digest, len(self.payload))
        self.assertEqual(path.read_bytes(), self.payload)
        self.assertEqual(self.ranges, [None] + [f'bytes={65536 * i}-' for i in range(1, 7)])
        self.assertEqual(len([event for event in events if event['state'] == 'retrying']), 6)
        self.assertFalse(any(event.get('error') for event in events))
        self.assertEqual(events[-1]['state'], 'verified')
        self.assertFalse(path.with_name(path.name + '.buggcraft-part').exists())
        self.downloader.fetch(self.url, 'mod.jar', digest, len(self.payload))
        self.assertEqual(len(self.requests), 7)

    def test_switching_publisher_on_retry_replaces_url_and_resumes_partial_bytes(self):
        self.payload = bytes(range(256)) * 2048
        self.mode = 'persistent'
        self.downloader.retries = 0
        self.downloader.content_source = 'Modrinth'
        self.downloader.resolve_content_sources = True
        events = []
        self.downloader.file_event = events.append
        sha1 = hashlib.sha1(self.payload).hexdigest()
        modrinth = 'https://cdn.modrinth.com/data/project/versions/version/mod.jar'
        curseforge = 'https://edge.forgecdn.net/files/123/456/mod.jar'
        original = _DownloadSession.get
        requests_to_sources = []
        def get(session, url, **kwargs):
            requests_to_sources.append((urlsplit(url).hostname, kwargs.get('headers', {}).get('Range')))
            return original(session, self.url, **kwargs)
        with patch('core.content_routes.resolve_download_urls', return_value=[modrinth, curseforge]) as resolve, \
             patch.object(_DownloadSession, 'get', get):
            with self.assertRaises(RuntimeError):
                self.downloader.fetch(modrinth, 'mod.jar', sha1, len(self.payload))
            part = Path(self.temp.name) / 'mod.jar.buggcraft-part'
            self.assertEqual(part.stat().st_size, 65536)
            self.mode = None
            self.downloader.content_source = 'CurseForge'
            result = self.downloader.fetch(modrinth, 'mod.jar', sha1, len(self.payload))
        self.assertEqual(result.read_bytes(), self.payload)
        self.assertEqual(requests_to_sources,
                         [('cdn.modrinth.com', None), ('edge.forgecdn.net', 'bytes=65536-')])
        self.assertEqual([call.kwargs['preference'] for call in resolve.call_args_list],
                         ['Modrinth', 'CurseForge'])
        self.assertEqual([event['url'] for event in events if event.get('url') in (modrinth, curseforge)],
                         [modrinth, curseforge])

    def test_auto_measures_all_resolved_publishers_before_downloading(self):
        modrinth = 'https://cdn.modrinth.com/data/project/versions/version/mod.jar'
        curseforge = 'https://edge.forgecdn.net/files/123/456/mod.jar'
        self.downloader.content_source = '自动测速'
        self.downloader.resolve_content_sources = True
        original = _DownloadSession.get
        hosts = []
        def get(session, url, **kwargs):
            hosts.append(urlsplit(url).hostname)
            return original(session, self.url, **kwargs)
        def rank(candidates, preference):
            self.assertIn(curseforge, candidates)
            self.assertIn(modrinth, candidates)
            self.assertTrue(any(urlsplit(url).hostname == 'mod.mcimirror.top' for url in candidates))
            return sorted(candidates, key=lambda url: url != curseforge)
        with patch('core.content_routes.resolve_download_urls', return_value=[modrinth, curseforge]), \
             patch('core.downloads._rank_content_candidates', side_effect=rank) as measured, \
             patch.object(_DownloadSession, 'get', get):
            result = self.downloader.fetch(modrinth, 'mod.jar', hashlib.sha1(self.payload).hexdigest(), len(self.payload))
        measured.assert_called_once()
        self.assertEqual(hosts, ['edge.forgecdn.net'])
        self.assertEqual(result.read_bytes(), self.payload)

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
        media = 'https://mediafilez.forgecdn.net/files/123/4/a%20b.jar?x=1'
        for setting in ('自动测速', 'CurseForge', 'Modrinth', 'MCIM', '官方'):
            with self.subTest(media_source=setting):
                self.downloader.content_source = setting
                self.assertEqual(self.downloader.urls(media), [media])
        self.downloader.content_source = '官方'
        self.assertEqual(self.downloader.urls(urls[0])[0], urls[0])
        self.downloader.source = '官方'
        self.downloader.content_source = 'MCIM'
        self.assertTrue(self.downloader.urls(urls[0])[0].startswith('https://mod.mcimirror.top/'))
        self.downloader.content_source = '自动测速'
        self.assertEqual([urlsplit(url).hostname for url in self.downloader.urls(urls[0])],
                         ['mod.mcimirror.top', 'cdn.modrinth.com'])
        self.assertEqual([urlsplit(url).hostname for url in self.downloader.urls(urls[1])],
                         ['mod.mcimirror.top', 'edge.forgecdn.net', 'mediafilez.forgecdn.net'])
        for url in ('https://cdn.modrinth.com.evil.org/x', 'https://user@cdn.modrinth.com/x',
                    'https://cdn.modrinth.com:444/x', 'https://github.com/a/b/releases/download/x.jar'):
            self.assertEqual(self.downloader.urls(url), [url])

    def test_mcim_first_falls_back_to_publisher_with_existing_partial_bytes(self):
        self.payload = bytes(range(256)) * 2048
        self.mode = 'persistent'
        self.downloader.content_source = 'MCIM'
        self.downloader.retries = 6
        original = _DownloadSession.get
        routes = []
        def get(session, url, **kwargs):
            host = urlsplit(url).hostname
            routes.append(host)
            self.mode = 'persistent' if host == urlsplit(CONTENT_MIRROR).hostname else None
            return original(session, self.url, **kwargs)
        with (patch('core.downloads._rank_content_candidates',
                    side_effect=lambda candidates, _: candidates),
              patch.object(_DownloadSession, 'get', get)):
            with patch.object(self.downloader.cancel, 'wait', return_value=False):
                path = self.downloader.fetch('https://cdn.modrinth.com/data/id/version/mod.jar',
                                             'mod.jar', hashlib.sha1(self.payload).hexdigest(),
                                             len(self.payload))
        self.assertEqual(path.read_bytes(), self.payload)
        self.assertEqual(routes, ['mod.mcimirror.top', 'cdn.modrinth.com'])
        self.assertEqual(self.ranges, [None, 'bytes=65536-'])

    def test_official_only_ignores_cached_mcim_fallbacks(self):
        self.downloader.content_source = '官方'
        mirror = 'https://mod.mcimirror.top/data/id/version/mod.jar'
        original = 'https://cdn.modrinth.com/data/id/version/mod.jar'
        self.assertEqual(self.downloader.urls(mirror), [original])

    def test_cancel_after_partial_download_preserves_checkpoint_and_installed_file(self):
        path = Path(self.temp.name) / 'pack.zip'
        path.write_bytes(b'previous')
        def cancel(done, total):
            self.downloader.cancel.set()
        with self.assertRaises(DownloadCancelled):
            self.downloader.fetch(self.url, 'pack.zip', hashlib.sha1(self.payload).hexdigest(),
                                  len(self.payload), file_progress=cancel)
        self.assertEqual(path.read_bytes(), b'previous')
        self.assertTrue(path.with_name(path.name + '.buggcraft-part').exists())

    def test_new_downloader_resumes_after_all_automatic_attempts_fail(self):
        self.mode = 'persistent'
        digest = hashlib.sha1(self.payload).hexdigest()
        target = Path(self.temp.name) / 'retry.jar'
        with self.assertRaisesRegex(RuntimeError, 'retry.jar'):
            self.downloader.fetch(self.url, target.name, digest, len(self.payload))
        temporary = target.with_name(target.name + '.buggcraft-part')
        offset = temporary.stat().st_size
        self.assertGreater(offset, 0)
        self.assertLess(offset, len(self.payload))
        self.assertFalse(target.exists())
        self.mode = 'resume'
        progress = []
        downloader = MinecraftDownloader(self.temp.name, source='官方')
        try:
            downloader.fetch(self.url, target.name, digest, len(self.payload), file_progress=lambda done, total: progress.append(done))
        finally:
            downloader._sessions.session.close()
        self.assertEqual(self.ranges[-1], f'bytes={offset}-')
        self.assertEqual(progress[0], offset)
        self.assertEqual(target.read_bytes(), self.payload)
        self.assertFalse(list(Path(self.temp.name).rglob('*.buggcraft-part*')))

    def test_response_size_is_saved_for_resume_when_manifest_only_has_hash(self):
        self.mode = 'persistent'
        digest = hashlib.sha1(self.payload).hexdigest()
        with self.assertRaises(RuntimeError):
            self.downloader.fetch(self.url, 'metadata.bin', digest)
        offset = (Path(self.temp.name) / 'metadata.bin.buggcraft-part').stat().st_size
        self.mode = 'resume'
        result = self.downloader.fetch(self.url, 'metadata.bin', digest)
        self.assertEqual(self.ranges[-1], f'bytes={offset}-')
        self.assertEqual(result.read_bytes(), self.payload)

    def test_changed_hash_does_not_append_old_partial_bytes(self):
        self.mode = 'persistent'
        with self.assertRaises(RuntimeError):
            self.downloader.fetch(self.url, 'changed.jar', hashlib.sha1(self.payload).hexdigest(), len(self.payload))
        self.payload = b'new release' * 25000
        self.mode = 'resume'
        result = self.downloader.fetch(self.url, 'changed.jar', hashlib.sha1(self.payload).hexdigest(), len(self.payload))
        self.assertIsNone(self.ranges[-1])
        self.assertEqual(result.read_bytes(), self.payload)

    def test_invalid_metadata_switches_source_and_never_publishes_error_response(self):
        self.extra_payloads = {'/invalid': b'{"error": "temporarily unavailable"}',
                               '/valid': b'{"versions": []}'}
        base = self.url.rsplit('/', 1)[0]
        with patch.object(self.downloader, 'urls', return_value=[base + '/invalid', base + '/valid']):
            value = self.downloader.fetch_json(self.url, 'manifest.json', label='Minecraft 版本列表',
                                               valid=lambda data: isinstance(data.get('versions'), list))
        self.assertEqual(value, {'versions': []})
        self.assertEqual(json.loads((Path(self.temp.name) / 'manifest.json').read_text()), value)
        self.assertIn('/valid', self.requests)

    def test_malformed_metadata_has_actionable_message_and_is_not_cached(self):
        self.extra_payloads = {'/invalid': b'<html>Service unavailable</html>'}
        with self.assertRaisesRegex(RuntimeError, '游戏资源索引不完整或格式错误.*assets.json.*重试') as error:
            self.downloader.fetch_json(self.url.rsplit('/', 1)[0] + '/invalid', 'assets.json', label='游戏资源索引')
        self.assertNotIn('Expecting value', str(error.exception))
        self.assertFalse((Path(self.temp.name) / 'assets.json').exists())
        self.assertFalse(list(Path(self.temp.name).rglob('*.buggcraft-part*')))

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

    def test_cancel_parallel_resource_preserves_previous_install_and_resumes_contiguous_prefix(self):
        path = Path(self.temp.name) / 'large.zip'
        path.write_bytes(b'previous installation')
        def cancel(done, total):
            self.downloader.cancel.set()
        with self.assertRaises(DownloadCancelled):
            self.large_content('/segments', cancel)
        self.assertEqual(path.read_bytes(), b'previous installation')
        temporary = path.with_name(path.name + '.buggcraft-part')
        self.assertTrue(temporary.exists())
        self.assertFalse(list(Path(self.temp.name).glob('*.buggcraft-part.[0-9]')))
        offset = temporary.stat().st_size
        self.mode = 'resume'
        downloader = MinecraftDownloader(self.temp.name, source='官方', workers=1)
        try:
            downloader.fetch(self.url, path.name, hashlib.sha1(self.payload).hexdigest(), len(self.payload),
                             sha512=hashlib.sha512(self.payload).hexdigest())
        finally:
            if getattr(downloader._sessions, 'session', None):
                downloader._sessions.session.close()
        self.assertEqual(path.read_bytes(), self.payload)
        if 0 < offset < len(self.payload):
            self.assertEqual(self.ranges[-1], f'bytes={offset}-')
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
        self.assertEqual([host for host, _ in calls], ['mod.mcimirror.top', 'cdn.modrinth.com'])
        self.assertEqual(calls[0][1], 0)
        self.assertTrue(0 < calls[1][1] < len(self.payload))
        self.assertFalse(list(Path(self.temp.name).glob('*.buggcraft-part')))

    def test_last_available_slow_mirror_finishes_instead_of_reporting_switch_failure(self):
        import itertools
        self.downloader.content_source = 'Modrinth'
        original_get = _DownloadSession.get
        calls = []

        def get(session, url, **kwargs):
            host = urlsplit(url).hostname
            calls.append((host, kwargs['headers'].get('Range')))
            if host == 'cdn.modrinth.com':
                raise requests.Timeout('publisher timed out')
            return original_get(session, self.url, **kwargs)

        # Time advances faster than the stream to exercise low-speed detection.
        ticks = itertools.count()
        with patch.object(_DownloadSession, 'get', get), patch('core.downloads.time.monotonic', side_effect=lambda: next(ticks)):
            result = self.downloader.fetch('https://cdn.modrinth.com/data/last-mirror.jar', 'last-mirror.jar',
                hashlib.sha1(self.payload).hexdigest(), len(self.payload))
        self.assertEqual(result.read_bytes(), self.payload)
        self.assertEqual([host for host, _ in calls], ['cdn.modrinth.com', 'mod.mcimirror.top'])
        self.assertFalse(list(Path(self.temp.name).glob('*.buggcraft-part*')))

    def test_last_available_mirror_retries_transient_failure_and_resumes(self):
        self.downloader.content_source = 'Modrinth'
        self.downloader.retries = 6
        self.mode = 'resume'
        original_get = _DownloadSession.get
        calls = []

        def get(session, url, **kwargs):
            calls.append((urlsplit(url).hostname, kwargs['headers'].get('Range')))
            if calls[-1][0] == 'cdn.modrinth.com':
                raise requests.Timeout('publisher timed out')
            return original_get(session, self.url, **kwargs)

        with patch.object(_DownloadSession, 'get', get):
            result = self.downloader.fetch('https://cdn.modrinth.com/data/retry-mirror.jar', 'retry-mirror.jar',
                hashlib.sha1(self.payload).hexdigest(), len(self.payload))
        self.assertEqual(result.read_bytes(), self.payload)
        self.assertEqual(calls, [('cdn.modrinth.com', None), ('mod.mcimirror.top', None),
                                 ('mod.mcimirror.top', 'bytes=65536-')])

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
