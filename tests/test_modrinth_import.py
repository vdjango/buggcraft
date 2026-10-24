"""MRPACK imports use the same transactional path as CurseForge packs."""
import copy
import hashlib
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

from core.modpacks import CurseForgeClient, ModpackImporter, inspect_pack
from core.downloads import _DownloadSession


class ModrinthImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.game = self.root / 'game'
        self.archive = self.root / 'pack.mrpack'
        self.payload = b'verified modrinth mod fixture'
        self.manifest = dict(formatVersion=1, game='minecraft', name='MRPACK fixture', versionId='1.0',
            dependencies={'minecraft': '1.20.1', 'fabric-loader': '0.16.10'}, files=[self.file('mods/example.jar')])

    def file(self, path, **kwargs):
        return dict(path=path, fileSize=len(self.payload),
                    hashes={name: hashlib.new(name, self.payload).hexdigest() for name in ('sha1', 'sha512')},
                    downloads=['https://cdn.modrinth.com/fixture/' + path], **kwargs)

    def pack(self, extra=None):
        with zipfile.ZipFile(self.archive, 'w') as archive:
            archive.writestr('modrinth.index.json', json.dumps(self.manifest))
            for name, value in (extra or {}).items():
                archive.writestr(name, value)

    def loader(self, *args, **kwargs):
        for identity, parent in (('1.20.1', None), ('fabric-fixture', '1.20.1')):
            directory = self.game / 'versions' / identity
            directory.mkdir(parents=True, exist_ok=True)
            metadata = dict(id=identity)
            if parent:
                metadata['inheritsFrom'] = parent
            (directory / (identity + '.json')).write_text(json.dumps(metadata))
        (self.game / 'versions/1.20.1/1.20.1.jar').write_bytes(b'client fixture')
        return 'fabric-fixture'

    def server(self):
        payload, hits = self.payload, []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                hits.append(self.path)
                self.send_response(404 if 'broken' in self.path else 200)
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        original_get = _DownloadSession.get
        def local_get(session, url, **kwargs):
            self.assertTrue(url.startswith(('https://mod.mcimirror.top/fixture/', 'https://mod.mcimirror.top/files/')))
            return original_get(session, url.replace('https://mod.mcimirror.top',
                         f'http://127.0.0.1:{server.server_port}').replace('/fixture/', '/'), **kwargs)
        return patch.object(_DownloadSession, 'get', local_get), hits

    def test_real_download_hashes_layers_client_environment_and_client_jar(self):
        self.manifest['files'] += [self.file('mods/optional.jar', env={'client': 'optional'}),
                                   self.file('mods/server.jar', env={'client': 'unsupported'})]
        self.pack({'overrides/config/example.txt': b'general',
                   'client-overrides/config/example.txt': b'client',
                   'server-overrides/server.properties': b'server only'})
        info = inspect_pack(self.archive)
        self.assertEqual((info.source, info.minecraft, info.loader, len(info.files)), ('Modrinth', '1.20.1', 'Fabric', 2))
        http, hits = self.server()
        with http, patch.object(CurseForgeClient, 'resolve') as curseforge, \
                patch('core.modpacks.install_loader', side_effect=self.loader):
            identity = ModpackImporter(self.game).install(self.archive, 'MR-Test')
        curseforge.assert_not_called()
        target = self.game / 'versions' / identity
        self.assertEqual((target / 'mods/example.jar').read_bytes(), self.payload)
        self.assertEqual((target / 'mods/optional.jar').read_bytes(), self.payload)
        self.assertFalse((target / 'mods/server.jar').exists())
        self.assertEqual((target / 'config/example.txt').read_bytes(), b'client')
        self.assertFalse((target / 'server.properties').exists())
        metadata = json.loads((target / (identity + '.json')).read_text())
        self.assertEqual(metadata['jar'], '1.20.1')
        self.assertTrue((self.game / 'versions' / metadata['jar'] / (metadata['jar'] + '.jar')).is_file())
        self.assertEqual(metadata['buggcraftModpack']['source'], 'Modrinth')
        self.assertEqual(len(hits), 2)

    def test_secondary_url_is_used_after_failure(self):
        self.manifest['files'][0]['downloads'].insert(0, 'https://cdn.modrinth.com/fixture/broken')
        self.pack()
        http, hits = self.server()
        with http, patch('core.modpacks.install_loader', side_effect=self.loader):
            ModpackImporter(self.game).install(self.archive, 'Mirrors')
        self.assertEqual(hits.count('/broken'), 1)
        self.assertIn('/mods/example.jar', hits)

    def test_zip_with_forge_cdn_files_imports_through_domestic_mirror(self):
        self.archive = self.root / 'pack.zip'
        self.manifest['files'][0]['downloads'] = ['https://edge.forgecdn.net/files/100/20/example.jar',
                                                   'https://cdn.modrinth.com/fixture/mods/example.jar']
        self.pack()
        self.assertEqual(inspect_pack(self.archive).source, 'Modrinth')
        http, hits = self.server()
        with http, patch('core.modpacks.install_loader', side_effect=self.loader):
            ModpackImporter(self.game, source='BMCLAPI').install(self.archive, 'Forge-CDN')
        self.assertEqual(hits, ['/files/100/20/example.jar'])
        self.assertEqual((self.game / 'versions/Forge-CDN/mods/example.jar').read_bytes(), self.payload)

    def test_sha512_mismatch_never_publishes_instance_or_installs_loader(self):
        self.manifest['files'][0]['hashes']['sha512'] = '0' * 128
        self.pack()
        http, _ = self.server()
        with http, patch('core.modpacks.install_loader') as loader:
            with self.assertRaisesRegex(ValueError, 'SHA512'):
                ModpackImporter(self.game).install(self.archive, 'Bad-Hash')
        loader.assert_not_called()
        self.assertFalse((self.game / 'versions/Bad-Hash').exists())

    def test_invalid_entries_and_conflicting_loaders_are_rejected(self):
        original = copy.deepcopy(self.manifest)
        changes = [dict(path='../escape.jar'), dict(downloads=['http://cdn.modrinth.com/a']),
                   dict(downloads=['https://example.org/a']), dict(hashes={'sha1': '0' * 40}),
                   dict(fileSize=-1), dict(env={'client': 'invalid'}),
                   dict(downloads=['https://edge.forgecdn.net.evil.org/a']),
                   dict(downloads=['https://user@edge.forgecdn.net/a']),
                   dict(downloads=['https://edge.forgecdn.net:444/a'])]
        for change in changes:
            with self.subTest(change=change):
                self.manifest = copy.deepcopy(original)
                self.manifest['files'][0].update(change)
                self.pack()
                with self.assertRaises(ValueError):
                    inspect_pack(self.archive)
        self.manifest = original
        self.manifest['dependencies']['forge'] = '47.4.0'
        self.pack()
        with self.assertRaises(ValueError):
            inspect_pack(self.archive)

    def test_client_override_can_replace_manifest_file_but_not_launcher_metadata(self):
        self.pack({'client-overrides/mods/example.jar': b'author override'})
        http, _ = self.server()
        with http, patch('core.modpacks.install_loader', side_effect=self.loader):
            ModpackImporter(self.game).install(self.archive, 'Overrides')
        self.assertEqual((self.game / 'versions/Overrides/mods/example.jar').read_bytes(), b'author override')
        self.pack({'client-overrides/Protected.json': b'{}'})
        with http, patch('core.modpacks.install_loader', side_effect=self.loader):
            with self.assertRaises(ValueError):
                ModpackImporter(self.game).install(self.archive, 'Protected')
        self.assertFalse((self.game / 'versions/Protected').exists())
