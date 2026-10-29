"""Pack transactions, actual HTTP cache reuse, API validation and archive safety."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / 'buggcraft'))
from core.modpacks import CurseForgeClient, ModpackImporter, export_pack, inspect_pack, instance_name, safe_path
from core.downloads import DownloadCancelled, MinecraftDownloader, _DownloadSession


class ModpackTests(unittest.TestCase):
    def test_export_reports_real_progress_and_cancel_removes_only_its_partial_archive(self):
        instance = self.root / 'source/versions/Pack'
        instance.mkdir(parents=True)
        (instance / 'Pack.json').write_text(json.dumps(dict(id='Pack', clientVersion='1.20.1')), encoding='utf-8')
        (instance / 'config').mkdir()
        (instance / 'config/settings.txt').write_bytes(b'portable-content' * 200000)
        archive = self.root / 'progress.buggpack'
        reports = []
        export_pack(self.root / 'source', 'Pack', archive, progress=lambda *row: reports.append(row))
        self.assertTrue(any(0 < done < total for _, done, total in reports))
        self.assertEqual(reports[-1][1], reports[-1][2])
        self.assertEqual(inspect_pack(archive).files[0]['path'], 'config/settings.txt')
        original = archive.read_bytes()
        with self.assertRaises(FileExistsError):
            export_pack(self.root / 'source', 'Pack', archive)
        self.assertEqual(archive.read_bytes(), original)
        cancelled = self.root / 'cancelled.buggpack'
        event = threading.Event()
        def cancel(label, done, total):
            if label.startswith('正在打包'):
                event.set()
        with self.assertRaises(DownloadCancelled):
            export_pack(self.root / 'source', 'Pack', cancelled, progress=cancel, cancel=event)
        self.assertFalse(cancelled.exists())
        self.assertEqual(archive.read_bytes(), original)

    def test_compact_export_references_verified_content_and_standard_embeds_it(self):
        from core.content_records import record_content
        source = self.root / 'source'
        instance = source / 'versions' / 'Pack'
        instance.mkdir(parents=True)
        (instance / 'Pack.json').write_text(json.dumps(dict(id='Pack', clientVersion='1.20.1',
            libraries=[{'name': 'net.minecraftforge:fmlloader:1.20.1-47.4.0'}])), encoding='utf-8')
        payloads = {}
        for folder, filename in [('mods','mod.jar'), ('resourcepacks','textures.zip'), ('shaderpacks','shader.zip')]:
            path = instance / folder / filename
            path.parent.mkdir()
            path.write_bytes(os.urandom(10000))
            payloads[path.relative_to(instance).as_posix()] = path.read_bytes()
            record_content(instance, path, ['https://cdn.modrinth.com/data/test/' + filename])
        local = instance / 'mods/local.jar'
        local.write_bytes(b'local-only')
        shared_resource = source / 'resourcepacks' / 'shared.zip'
        shared_resource.parent.mkdir()
        shared_resource.write_bytes(b'shared game resource')
        record_content(source, shared_resource, ['https://cdn.modrinth.com/data/test/shared.zip'])
        compact, standard = self.root / 'compact.buggpack', self.root / 'standard.buggpack'
        result = export_pack(source, 'Pack', compact, game_directory=source)
        export_pack(source, 'Pack', standard, mode='standard', game_directory=source)
        self.assertEqual(result['external_files'], 4)
        self.assertLess(compact.stat().st_size, standard.stat().st_size)
        info = inspect_pack(compact)
        self.assertEqual((info.loader, info.loader_version), ('Forge', '47.4.0'))
        self.assertEqual(len([i for i in info.files if not i['embedded']]), 4)
        payloads['resourcepacks/shared.zip'] = shared_resource.read_bytes()
        def fetch(downloader, url, relative, *args):
            target = downloader.inside(relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payloads[relative])
            return target
        with patch.object(MinecraftDownloader, 'fetch', fetch), \
                patch('core.modpacks.install_loader', side_effect=self.install_loader):
            ModpackImporter(self.game).install(compact, 'Imported')
        for relative, payload in payloads.items():
            self.assertEqual((self.game / 'versions/Imported' / relative).read_bytes(), payload)
        self.assertEqual((self.game / 'versions/Imported/mods/local.jar').read_bytes(), b'local-only')
        # A changed resource must be embedded even when an old download record exists.
        (instance / 'mods/mod.jar').write_bytes(b'changed')
        changed = self.root / 'changed.buggpack'
        self.assertEqual(export_pack(source, 'Pack', changed, game_directory=source)['external_files'], 3)

    def test_isolated_export_excludes_unrelated_shared_mods_and_saves(self):
        source = self.root / 'isolated-source'
        instance = source / 'versions' / 'Isolated'
        instance.mkdir(parents=True)
        (instance / 'Isolated.json').write_text(json.dumps(dict(id='Isolated', clientVersion='1.20.1')))
        (instance / 'config').mkdir()
        (instance / 'config/local.txt').write_text('only this instance')
        for folder in ('mods', 'saves'):
            (source / folder).mkdir()
            (source / folder / 'unrelated.txt').write_text('do not export')
        archive = self.root / 'isolated.buggpack'
        export_pack(source, 'Isolated', archive, game_directory=instance)
        with zipfile.ZipFile(archive) as result:
            self.assertEqual(set(result.namelist()), {'buggcraft.pack.json', 'files/config/local.txt'})

    def setUp(self):
        # Loader fixtures create the vanilla files without network access.
        vanilla = patch.object(ModpackImporter, '_install_vanilla', return_value=None)
        vanilla.start()
        self.addCleanup(vanilla.stop)
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
        (self.game / 'versions/1.20.1/1.20.1.jar').write_bytes(b'fake minecraft client jar')
        return '1.20.1-forge-47.4.0'

    def test_buggpack_export_is_hashed_and_round_trips_without_catalogue(self):
        source = self.root / 'source'
        instance = source / 'versions' / 'SourcePack'
        instance.mkdir(parents=True)
        (instance / 'SourcePack.json').write_text(json.dumps({
            'id': 'SourcePack', 'clientVersion': '1.20.1',
            'buggcraftModpack': {
                'name': '本地包', 'version': '3.2', 'minecraft': '1.20.1',
                'loader': 'Forge', 'loaderVersion': '47.4.0', 'recommendedRam': 4096,
            },
        }), encoding='utf-8')
        (instance / 'config').mkdir()
        (instance / 'config' / 'example.json').write_text('{"enabled":true}', encoding='utf-8')
        (instance / 'mods').mkdir()
        (instance / 'mods' / 'example.jar').write_bytes(b'mod payload')
        (instance / 'logs').mkdir()
        (instance / 'logs' / 'latest.log').write_text('must not leave the machine', encoding='utf-8')
        archive = self.root / 'exported.buggpack'
        result = export_pack(source, 'SourcePack', archive)
        self.assertEqual(result['files'], 2)
        self.assertEqual(archive.suffix, '.buggpack')
        info = inspect_pack(archive)
        self.assertEqual((info.source, info.minecraft, info.loader, info.loader_version),
                         ('Buggcraft', '1.20.1', 'Forge', '47.4.0'))
        with zipfile.ZipFile(archive) as packaged:
            names = set(packaged.namelist())
            self.assertIn('buggcraft.pack.json', names)
            self.assertIn('files/config/example.json', names)
            self.assertIn('files/mods/example.jar', names)
            self.assertNotIn('files/logs/latest.log', names)
            manifest = json.loads(packaged.read('buggcraft.pack.json'))
            entry = next(item for item in manifest['files'] if item['path'] == 'mods/example.jar')
            self.assertEqual(entry['sha256'], hashlib.sha256(b'mod payload').hexdigest())

        target = self.root / 'imported'
        def loader(*args, **kwargs):
            for identity, metadata in [('1.20.1', {'id': '1.20.1'}),
                    ('1.20.1-forge-47.4.0', {'id': '1.20.1-forge-47.4.0', 'inheritsFrom': '1.20.1'})]:
                destination = target / 'versions' / identity / (identity + '.json')
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(json.dumps(metadata), encoding='utf-8')
            (target / 'versions/1.20.1/1.20.1.jar').write_bytes(b'client')
            return '1.20.1-forge-47.4.0'
        with patch('core.modpacks.install_loader', side_effect=loader):
            self.assertEqual(ModpackImporter(target).install(archive, 'ImportedPack'), 'ImportedPack')
        imported = target / 'versions' / 'ImportedPack'
        self.assertEqual((imported / 'config/example.json').read_text(encoding='utf-8'), '{"enabled":true}')
        self.assertEqual((imported / 'mods/example.jar').read_bytes(), b'mod payload')
        self.assertFalse((imported / 'logs').exists())

    def test_import_uses_configured_1_to_64_real_http_workers_with_verified_files(self):
        from config.settings import SettingsManager
        settings = SettingsManager(self.root / 'concurrency-config')
        self.pack()
        payload = b'concurrent resource' * 4096
        digest = hashlib.sha1(payload).hexdigest()
        lock = threading.Lock()
        active = peak = hits = 0
        class Server(ThreadingHTTPServer):
            request_queue_size = 128
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                nonlocal active, peak, hits
                with lock:
                    active += 1
                    hits += 1
                    peak = max(peak, active)
                try:
                    time.sleep(.2)
                    self.send_response(200)
                    self.send_header('Content-Length', str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                finally:
                    with lock:
                        active -= 1
            def log_message(self, *args):
                pass
        server = Server(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        for workers in (1, 2, 4, 8, 16, 32, 64):
            with self.subTest(workers=workers):
                settings.set_setting('downloads.concurrency', workers)
                settings.save_settings()
                persisted = SettingsManager(settings.config_path)
                peak = hits = 0
                # Separate archives avoid a previous run's verified file cache.
                self.pack({'overrides/worker-count.txt': str(workers)})
                jobs = [(f'http://127.0.0.1:{server.server_port}/{i}',
                         f'mods/resource-{i}.jar', digest, len(payload)) for i in range(min(128, workers * 2))]
                started = time.monotonic()
                with patch.dict(os.environ, {'NO_PROXY': '127.0.0.1', 'no_proxy': '127.0.0.1'}), \
                        patch('config.settings.get_settings_manager', return_value=persisted), \
                        patch.object(CurseForgeClient, 'resolve', return_value=jobs), \
                        patch('core.modpacks.install_loader', side_effect=self.install_loader):
                    identity = ModpackImporter(self.game).install(self.archive, f'Workers-{workers}')
                self.assertEqual(hits, len(jobs))
                self.assertGreaterEqual(peak, workers // 2)
                self.assertLessEqual(peak, workers)
                for _, relative, _, _ in jobs:
                    self.assertEqual((self.game / 'versions' / identity / relative).read_bytes(), payload)
                print(f'HTTP import workers={workers} peak={peak} verified={hits}/{len(jobs)} '
                      f'elapsed={time.monotonic() - started:.2f}s', flush=True)

    def test_mod_files_download_while_loader_installs(self):
        self.pack()
        payload = b'parallel mod payload'
        jobs = [('https://cdn.example.test/concurrent.jar', 'mods/concurrent.jar',
                 hashlib.sha1(payload).hexdigest(), len(payload))]
        mod_started = threading.Event()
        loader_started = threading.Event()

        def fetch(downloader, _url, relative, *_args):
            mod_started.set()
            self.assertTrue(loader_started.wait(2), 'loader should start before mod download finishes')
            target = downloader.inside(relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            return target

        def install_loader(*args, **kwargs):
            loader_started.set()
            self.assertTrue(mod_started.wait(2), 'mod download should start during loader installation')
            return self.install_loader(*args, **kwargs)

        with (patch.object(CurseForgeClient, 'resolve', return_value=jobs),
              patch.object(MinecraftDownloader, 'fetch', fetch),
              patch('core.modpacks.install_loader', side_effect=install_loader)):
            identity = ModpackImporter(self.game).install(self.archive, 'Parallel-Pack')
        self.assertEqual((self.game / 'versions' / identity / 'mods/concurrent.jar').read_bytes(), payload)

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
        self.assertNotIn('inheritsFrom', metadata)
        self.assertNotIn('jar', metadata)
        self.assertEqual(metadata['id'], 'My-Pack')
        self.assertEqual((target / 'My-Pack.jar').read_bytes(), b'fake minecraft client jar')
        self.assertFalse((self.game / 'mods').exists())
        self.assertFalse((self.game / 'versions/1.20.1').exists())
        self.assertFalse((self.game / 'versions/1.20.1-forge-47.4.0').exists())
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

    def test_combined_pack_preserves_natives_and_existing_vanilla_install(self):
        self.manifest['files'] = []
        self.pack()
        self.install_loader()
        natives = self.game / 'versions/1.20.1/natives'
        natives.mkdir()
        (natives / 'fixture.dll').write_bytes(b'fixture native')
        with patch('core.modpacks.install_loader', side_effect=self.install_loader):
            ModpackImporter(self.game).install(self.archive, 'Combined')
        combined = self.game / 'versions/Combined'
        self.assertEqual((combined / 'natives/fixture.dll').read_bytes(), b'fixture native')
        metadata = json.loads((combined / 'Combined.json').read_text(encoding='utf-8'))
        self.assertEqual(metadata['clientVersion'], '1.20.1')
        self.assertTrue((self.game / 'versions/1.20.1/1.20.1.jar').is_file())

    def test_malformed_neighbor_does_not_break_published_import(self):
        self.manifest['files'] = []
        self.pack()
        malformed = self.game / 'versions/Broken/Broken.json'
        malformed.parent.mkdir(parents=True)
        malformed.write_text('[]', encoding='utf-8')
        with patch('core.modpacks.install_loader', side_effect=self.install_loader):
            self.assertEqual(ModpackImporter(self.game).install(self.archive, 'Combined'), 'Combined')
        self.assertEqual(malformed.read_text(encoding='utf-8'), '[]')
        self.assertTrue((self.game / 'versions/Combined/Combined.jar').is_file())

    def test_loader_failure_then_retry_removes_profiles_created_by_first_attempt(self):
        self.manifest['files'] = []
        self.pack()
        def fail_after_profiles(*args, **kwargs):
            self.install_loader()
            raise RuntimeError('processor stopped after writing profiles')
        with patch('core.modpacks.install_loader', side_effect=fail_after_profiles):
            with self.assertRaisesRegex(RuntimeError, 'processor stopped'):
                ModpackImporter(self.game).install(self.archive, 'Retried')
        self.assertTrue((self.game / 'versions/1.20.1').exists())
        with patch('core.modpacks.install_loader', side_effect=self.install_loader):
            ModpackImporter(self.game).install(self.archive, 'Retried')
        self.assertEqual([item.name for item in (self.game / 'versions').iterdir()], ['Retried'])

    def test_changed_intermediate_after_failure_is_preserved_on_retry(self):
        self.manifest['files'] = []
        self.pack()
        def fail_after_profiles(*args, **kwargs):
            self.install_loader()
            raise RuntimeError('processor stopped')
        with patch('core.modpacks.install_loader', side_effect=fail_after_profiles):
            with self.assertRaises(RuntimeError):
                ModpackImporter(self.game).install(self.archive, 'Retried')
        marker = self.game / 'versions/1.20.1/user-file.txt'
        marker.write_text('keep this modified instance', encoding='utf-8')
        with patch('core.modpacks.install_loader', side_effect=self.install_loader):
            ModpackImporter(self.game).install(self.archive, 'Retried')
        self.assertEqual(marker.read_text(encoding='utf-8'), 'keep this modified instance')

    def test_imported_alias_copies_display_fields_from_core_for_other_launchers(self):
        self.manifest['files'] = []
        self.pack()
        def loader(*args, **kwargs):
            identity = self.install_loader(*args, **kwargs)
            core = self.game / 'versions/1.20.1/1.20.1.json'
            data = json.loads(core.read_text(encoding='utf-8'))
            data.update(type='release', time='2023-06-12T12:00:00Z', releaseTime='2023-06-12T12:00:00Z')
            core.write_text(json.dumps(data), encoding='utf-8')
            return identity
        with patch('core.modpacks.install_loader', side_effect=loader):
            ModpackImporter(self.game).install(self.archive, 'Display-fields')
        metadata = json.loads((self.game / 'versions/Display-fields/Display-fields.json').read_text(encoding='utf-8'))
        self.assertEqual(metadata['type'], 'release')
        self.assertEqual(metadata['releaseTime'], '2023-06-12T12:00:00Z')
        self.assertEqual(metadata['time'], metadata['releaseTime'])

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
        def response(project_record, file_record):
            return lambda route, _body: [project_record] if route == '/mods' else [file_record]
        with patch.object(client, 'post', side_effect=response(project, file)):
            self.assertEqual(client.resolve([(10, 20)])[0][1], 'mods/mod.jar')
        with patch.object(client, 'post', side_effect=response(
                dict(project, allowModDistribution=False),
                dict(file, downloadUrl=None, isAvailable=False))):
            self.assertEqual(client.resolve([(10, 20)])[0][0],
                             'https://edge.forgecdn.net/files/0/20/mod.jar')
            self.assertEqual(client.fallback_urls, {})
        for changes in ({'modId': 11}, {'fileName': '../mod.jar'}, {'hashes': []},
                        {'downloadUrl': 'https://evil.test/mod.jar'}):
            with patch.object(client, 'post', side_effect=response(project, dict(file, **changes))):
                with self.assertRaises(ValueError):
                    client.resolve([(10, 20)])

    def test_curseforge_project_and_file_metadata_requests_overlap(self):
        project = {'id': 10, 'classId': 6}
        file = {'id': 20, 'modId': 10, 'fileName': 'parallel.jar', 'fileLength': 100,
                'downloadUrl': 'https://edge.forgecdn.net/files/0/20/parallel.jar',
                'hashes': [{'algo': 1, 'value': 'a' * 40}]}
        barrier = threading.Barrier(2)

        def response(route, _body):
            barrier.wait(timeout=2)
            return [project] if route == '/mods' else [file]

        client = CurseForgeClient('test-key', threading.Event())
        with patch.object(client, 'post', side_effect=response):
            jobs = client.resolve([(10, 20)])
        self.assertEqual(jobs[0][1], 'mods/parallel.jar')

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
