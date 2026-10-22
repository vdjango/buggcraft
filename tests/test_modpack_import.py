"""Pack transactions, actual HTTP cache reuse, API validation and archive safety."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / 'buggcraft'))
from core.modpacks import CurseForgeClient, ModpackImporter, inspect_pack, instance_name, safe_path
from core.downloads import DownloadCancelled, MinecraftDownloader, _DownloadSession


class ModpackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.game = self.root / 'game'
        self.archive = self.root / 'pack.zip'
        self.manifest = {'manifestType': 'minecraftModpack', 'manifestVersion': 1,
                         'name': '示例整合包', 'version': '1.0', 'overrides': 'overrides',
                         'minecraft': {'version': '1.20.1', 'modLoaders': [{'id': 'forge-47.4.0'}]},
                         'files': [{'projectID': 10, 'fileID': 20, 'required': True}]}

    def pack(self, extra=None):
        with zipfile.ZipFile(self.archive, 'w') as archive:
            archive.writestr('manifest.json', json.dumps(self.manifest))
            archive.writestr('overrides/config/示例.json', '{"enabled": true}')
            archive.writestr('overrides/mods/bundled.jar', b'bundled')
            for name, value in (extra or {}).items():
                archive.writestr(name, value)

    def install_loader(self, *args, **kwargs):
        for identity, metadata in [('1.20.1', {'id': '1.20.1'}),
                ('1.20.1-forge-47.4.0', {'id': '1.20.1-forge-47.4.0', 'inheritsFrom': '1.20.1'})]:
            destination = self.game / 'versions' / identity / (identity + '.json')
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(metadata), encoding='utf-8')
        return '1.20.1-forge-47.4.0'

    def test_real_http_retry_reuses_verified_files_and_publishes_separate_instance(self):
        self.pack()
        payload, hits = b'actual mod payload', []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                hits.append(self.path)
                self.send_response(200)
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        jobs = [(f'http://127.0.0.1:{server.server_port}/mod', 'mods/downloaded.jar',
                 hashlib.sha1(payload).hexdigest(), len(payload))]
        with patch.dict(os.environ, {'NO_PROXY': '127.0.0.1', 'no_proxy': '127.0.0.1'}), \
                patch.object(CurseForgeClient, 'resolve', return_value=jobs), \
                patch('core.modpacks.install_loader', side_effect=RuntimeError('loader failed')):
            with self.assertRaisesRegex(RuntimeError, 'loader failed'):
                ModpackImporter(self.game).install(self.archive, 'My-Pack')
        self.assertFalse((self.game / 'versions' / 'My-Pack').exists())
        with patch.object(CurseForgeClient, 'resolve', return_value=jobs), \
                patch('core.modpacks.install_loader', side_effect=self.install_loader):
            result = ModpackImporter(self.game).install(self.archive, 'My-Pack')
        self.assertEqual(hits, ['/mod'])
        self.assertEqual(result, 'My-Pack')
        target = self.game / 'versions' / result
        self.assertEqual((target / 'mods/downloaded.jar').read_bytes(), payload)
        self.assertEqual((target / 'mods/bundled.jar').read_bytes(), b'bundled')
        self.assertTrue((target / 'config/示例.json').is_file())
        metadata = json.loads((target / 'My-Pack.json').read_text(encoding='utf-8'))
        self.assertEqual(metadata['inheritsFrom'], '1.20.1-forge-47.4.0')
        self.assertEqual(metadata['jar'], '1.20.1')
        self.assertFalse((self.game / 'mods').exists())
        with self.assertRaisesRegex(ValueError, '已存在'):
            ModpackImporter(self.game).install(self.archive, 'My-Pack')
        self.assertEqual((target / 'mods/downloaded.jar').read_bytes(), payload)

    def test_cancel_during_extraction_leaves_no_visible_instance(self):
        self.manifest['files'] = []
        self.pack()
        event = threading.Event()
        with patch('core.modpacks.install_loader', side_effect=self.install_loader):
            importer = ModpackImporter(self.game, cancel=event, progress=lambda *args: event.set())
            with self.assertRaises(DownloadCancelled):
                importer.install(self.archive, 'cancelled')
        self.assertFalse((self.game / 'versions' / 'cancelled').exists())
        self.assertEqual(list((self.game / '.buggcraft-downloads/modpacks').glob('*/instance-*')), [])

    def test_bundled_copy_of_manifest_file_is_deduplicated_only_if_identical(self):
        payload = b'identical bundled and downloaded resource'
        jobs = [('https://edge.forgecdn.net/files/0/20/resource.zip', 'resourcepacks/resource.zip',
                 hashlib.sha1(payload).hexdigest(), len(payload))]
        def fetch(downloader, url, relative, *args):
            target = downloader.inside(relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            return target
        for bundled, succeeds in [(payload, True), (b'changed resource', False)]:
            self.pack({'overrides/resourcepacks/resource.zip': bundled})
            identity = 'identical' if succeeds else 'different'
            with patch.object(CurseForgeClient, 'resolve', return_value=jobs), \
                    patch.object(MinecraftDownloader, 'fetch', fetch), \
                    patch('core.modpacks.install_loader', side_effect=self.install_loader):
                if succeeds:
                    ModpackImporter(self.game).install(self.archive, identity)
                    self.assertEqual((self.game / 'versions' / identity / 'resourcepacks/resource.zip').read_bytes(), payload)
                else:
                    with self.assertRaisesRegex(ValueError, '覆盖'):
                        ModpackImporter(self.game).install(self.archive, identity)
                    self.assertFalse((self.game / 'versions' / identity).exists())

    def test_deep_cache_extracts_long_config_filenames(self):
        from core.modpacks import disk_path
        self.manifest['files'] = []
        relative = 'config/ares_hud/presets/' + 'x' * 130 + '.json.before-overlay.bak'
        self.pack({'overrides/' + relative: b'long path config'})
        with patch('core.modpacks.install_loader', side_effect=self.install_loader):
            ModpackImporter(self.game).install(self.archive, 'long-config')
        self.assertEqual(disk_path(self.game / 'versions/long-config' / relative).read_bytes(), b'long path config')

    def test_reject_traversal_windows_names_case_collisions_and_symlinks(self):
        for name in ('../outside', 'overrides/../outside', 'overrides/C:/outside',
                     'overrides/CON.txt', 'overrides/foo.',
                     'overrides/Mods/BUNDLED.jar'):
            with self.subTest(name=name):
                self.pack({name: b'bad'})
                with self.assertRaises(ValueError):
                    inspect_pack(self.archive)
        with self.assertRaises(ValueError):
            safe_path('overrides/a\\b')
        self.pack()
        with zipfile.ZipFile(self.archive, 'a') as archive:
            link = zipfile.ZipInfo('overrides/link')
            link.external_attr = 0o120777 << 16
            archive.writestr(link, '../outside')
        with self.assertRaises(ValueError):
            inspect_pack(self.archive)
        for name in ('..', 'x/', 'x/y', 'NUL', 'foo:bar'):
            with self.assertRaises(ValueError):
                instance_name(name)

    def test_conflicting_loaders_rejected_even_when_only_one_is_primary(self):
        self.manifest['minecraft']['modLoaders'].append({'id': 'fabric-0.16.0', 'primary': False})
        self.pack()
        with self.assertRaisesRegex(ValueError, '互斥'):
            inspect_pack(self.archive)

    def test_unavailable_gateway_fails_before_game_install_without_creating_instance(self):
        self.pack()
        with patch.dict(os.environ, {'BUGGCRAFT_CURSEFORGE_API_KEY': ''}), \
                patch('core.curseforge.requests.post', side_effect=ValueError('公共资源服务不可用')), \
                patch('core.modpacks.install_loader') as install:
            with self.assertRaisesRegex(ValueError, '公共资源服务不可用'):
                ModpackImporter(self.game).install(self.archive, 'missing-key')
            install.assert_not_called()
        self.assertFalse(self.game.exists())

    def test_curseforge_rejects_wrong_project_unsafe_name_and_missing_checksum(self):
        project = {'id': 10, 'classId': 6}
        file = {'id': 20, 'modId': 10, 'fileName': 'mod.jar', 'fileLength': 100,
                'downloadUrl': 'https://edge.forgecdn.net/files/0/20/mod.jar',
                'hashes': [{'algo': 1, 'value': 'a' * 40}]}
        client = CurseForgeClient('test-key', threading.Event())
        with patch.object(client, 'post', side_effect=[[project], [file]]):
            self.assertEqual(client.resolve([(10, 20)])[0][1], 'mods/mod.jar')
        with patch.object(client, 'post', side_effect=[[dict(project, allowModDistribution=False)],
                                                       [dict(file, downloadUrl=None, isAvailable=False)]]):
            self.assertEqual(client.resolve([(10, 20)])[0][0],
                             'https://edge.forgecdn.net/files/0/20/mod.jar')
            self.assertEqual(client.fallback_urls, {})
        for changes in ({'modId': 11}, {'fileName': '../mod.jar'}, {'hashes': []},
                        {'downloadUrl': 'https://evil.test/mod.jar'}):
            with patch.object(client, 'post', side_effect=[[project], [dict(file, **changes)]]):
                with self.assertRaises(ValueError):
                    client.resolve([(10, 20)])

    def test_cdn_redirect_drops_key_outside_curseforge(self):
        import requests
        response = requests.Response()
        response.request = requests.Request('GET', 'https://edge.forgecdn.net/a').prepare()
        redirected = requests.Request('GET', 'https://example.org/a', headers={'x-api-key': 'secret'}).prepare()
        with _DownloadSession() as session:
            session.rebuild_auth(redirected, response)
        self.assertNotIn('x-api-key', redirected.headers)


if __name__ == '__main__':
    unittest.main()
