"""Local HTTP data for UI tests; the production downloader/importer stays real."""
from __future__ import annotations

import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
from pathlib import Path
from threading import Thread
from urllib.parse import urlsplit
import zipfile


def archive_bytes(files):
    stream = BytesIO()
    with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return stream.getvalue()


class ClientUiFixtures:
    """Route only fixture URLs to loopback, with real streaming and hashes.

    These small artifacts validate installation behavior, not Minecraft itself.
    A real Minecraft installation can separately be supplied to the UI runner.
    """

    ORIGIN = 'https://ui.buggcraft.test'

    def __init__(self, output):
        self.requests = []
        self.failures = set()
        # Optional per-file barriers let UI cases observe real streaming,
        # cancel/retry and parallel tasks without replacing their workers.
        self.pauses = {}
        self.truncations = set()
        self.pack = archive_bytes({
            'modrinth.index.json': json.dumps({
                'formatVersion': 1, 'game': 'minecraft', 'versionId': '1.0.0',
                'name': 'UI Fixture Pack', 'files': [],
                'dependencies': {'minecraft': '1.21.8'},
            }),
            'overrides/config/ui-acceptance.json': '{"installedBy":"real importer"}',
        })
        self.payloads = {
            'ui-fixture-mod.jar': archive_bytes({'fabric.mod.json': json.dumps({
                'schemaVersion': 1, 'id': 'ui_fixture', 'version': '1.0.0',
                'name': 'UI Test Fixture', 'environment': '*',
            })}),
            'ui-fixture-resourcepack.zip': archive_bytes({'pack.mcmeta': json.dumps({
                'pack': {'pack_format': 64, 'description': 'UI test resource pack'},
            })}),
            'ui-fixture-shader.zip': archive_bytes({'shaders/ui-test.txt': 'UI download fixture'}),
            'ui-fixture-modpack.mrpack': self.pack,
            'client.jar': archive_bytes({'META-INF/MANIFEST.MF': 'Manifest-Version: 1.0\n'}),
        }
        self.metadata = {
            'id': '1.21.8', 'type': 'release', 'mainClass': 'net.minecraft.client.main.Main',
            'releaseTime': '2026-01-01T00:00:00Z', 'libraries': [],
            'arguments': {'game': [], 'jvm': []},
            'downloads': {'client': self.file('client.jar')},
        }
        self.payloads['1.21.8.json'] = json.dumps(self.metadata).encode()
        self.payloads['manifest.json'] = json.dumps({'versions': [dict(
            id='1.21.8', type='release', releaseTime='2026-01-01T00:00:00Z',
            **self.file('1.21.8.json'))]}).encode()
        self.pack_path = Path(output) / 'fixture.mrpack'
        self.pack_path.write_bytes(self.pack)
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                name = urlsplit(self.path).path.lstrip('/')
                fixture.requests.append({'file': name, 'time': __import__('time').time()})
                if name in fixture.failures or name not in fixture.payloads:
                    self.send_error(404, 'UI fixture unavailable')
                    return
                payload = fixture.payloads[name]
                self.send_response(200)
                self.send_header('Content-Length', str(len(payload)))
                self.send_header('Content-Type', 'application/octet-stream')
                self.end_headers()
                barrier = fixture.pauses.get(name)
                try:
                    if name in fixture.truncations:
                        self.wfile.write(payload[:max(1, len(payload) // 2)])
                        self.wfile.flush()
                        self.close_connection = True
                    elif barrier:
                        started, release = barrier
                        split = max(1, len(payload) // 2)
                        self.wfile.write(payload[:split])
                        self.wfile.flush()
                        started.set()
                        release.wait(15)
                        self.wfile.write(payload[split:])
                    else:
                        self.wfile.write(payload)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    # Canceling a real client request may close this socket.
                    pass

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = Thread(target=self.server.serve_forever, name='client-ui-fixtures', daemon=True)
        self.thread.start()

    def file(self, name):
        payload = self.payloads[name]
        return dict(url=self.ORIGIN + '/' + name, filename=name, primary=True,
                    size=len(payload), sha1=hashlib.sha1(payload).hexdigest(),
                    hashes={'sha1': hashlib.sha1(payload).hexdigest(),
                            'sha512': hashlib.sha512(payload).hexdigest()})

    def route(self, downloader, url):
        from core.downloads import MANIFEST_URL
        if url == MANIFEST_URL:
            name = 'manifest.json'
        elif url.startswith(self.ORIGIN + '/'):
            name = urlsplit(url).path.lstrip('/')
        else:
            raise AssertionError('Isolated UI replay attempted a non-fixture download: ' + url)
        return ['http://127.0.0.1:%d/%s' % (self.server.server_port, name)]

    def version(self, kind):
        name = next(name for name in self.payloads if name.startswith('ui-fixture-' + kind + '.'))
        return dict(id='ui-fixture-' + kind, project_id='ui-fixture-' + kind,
                    name='UI Fixture 1.0', version_number='1.0.0', filename=name,
                    file_size=len(self.payloads[name]), game_versions=['1.21.8'],
                    loaders=[], files=[self.file(name)])

    def close(self):
        for _started, release in self.pauses.values():
            release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
