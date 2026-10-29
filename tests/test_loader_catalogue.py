"""Catalogue contracts from the official Maven metadata and BMCLAPI documentation."""
import hashlib
import io
from pathlib import Path
import sys
import tempfile
import time
import unittest
import json
import threading
import zipfile
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / 'buggcraft'))
from core import loaders


class LoaderCatalogueTests(unittest.TestCase):
    def test_loader_metadata_parser_error_is_actionable_and_closes_response(self):
        response = Mock()
        response.json.side_effect = json.JSONDecodeError('Expecting value', '', 0)
        with patch.object(loaders, '_response', return_value=response):
            with self.assertRaisesRegex(ValueError, '加载器安装信息.*重试'):
                loaders._response_json('https://example.test/loader.json', '加载器安装信息')
        response.close.assert_called_once()

    def test_standalone_fabric_game_and_loader_share_one_download_limit(self):
        identity = 'fabric-loader-0.15.0-1.20.1'
        active = peak = 0
        lock = threading.Lock()

        def transfer(_downloader, _url, relative, *_args, **_kwargs):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            try:
                time.sleep(.05)
                return Path(relative)
            finally:
                with lock:
                    active -= 1

        def jobs(prefix):
            return [('https://example.test/' + prefix + str(number),
                     prefix + str(number), None, None) for number in range(6)]

        def install_game(downloader, _version):
            downloader._batch(jobs('game-'), 'game files')

        def prefetch(_loader, _game, _version, root, _callback, cancel, _source, publish):
            self.assertFalse(publish)
            loaders.MinecraftDownloader(root, cancel=cancel)._batch(jobs('loader-'), 'loader files')
            return identity, {'id': identity, 'inheritsFrom': '1.20.1'}

        with (tempfile.TemporaryDirectory() as root,
              patch('core.downloads.download_concurrency', return_value=2),
              patch.object(loaders.MinecraftDownloader, '_fetch', transfer),
              patch.object(loaders.MinecraftDownloader, 'install', install_game),
              patch.object(loaders, '_profile_loader', side_effect=prefetch)):
            loaders.install_loader('Fabric', '1.20.1', '0.15.0', root, None,
                {'setStatus': lambda _value: None, 'setProgress': lambda _value: None,
                 'setMax': lambda _value: None}, threading.Event(), '官方')
        self.assertEqual(peak, 2)
        self.assertEqual(active, 0)

    def test_verified_vanilla_prefetch_is_reused_by_loader_install(self):
        identity = 'fabric-loader-0.15.0-1.20.1'
        with (tempfile.TemporaryDirectory() as root,
              patch.object(loaders, 'verified_installation', return_value=True),
              patch.object(loaders.MinecraftDownloader, 'install') as install_game,
              patch.object(loaders, '_profile_loader', return_value=(
                  identity, {'id': identity, 'inheritsFrom': '1.20.1'}))):
            result = loaders._install_loader('Fabric', '1.20.1', '0.15.0', root, None,
                {'setStatus': lambda _value: None, 'setProgress': lambda _value: None,
                 'setMax': lambda _value: None}, threading.Event(), '官方')
            self.assertEqual(result, identity)
            install_game.assert_not_called()
            self.assertTrue((Path(root) / 'versions' / identity / (identity + '.json')).is_file())

    def test_fabric_prefetch_overlaps_vanilla_without_early_profile(self):
        game_started = threading.Event()
        loader_started = threading.Event()
        identity = 'fabric-loader-0.15.0-1.20.1'
        metadata = {'id': identity, 'inheritsFrom': '1.20.1'}

        def install_game(_downloader, _version):
            game_started.set()
            self.assertTrue(loader_started.wait(2), 'loader prefetch should start with the game')

        def prefetch(_loader, _game, _version, root, _callback, _cancel, _source, publish):
            self.assertFalse(publish)
            loader_started.set()
            self.assertTrue(game_started.wait(2))
            self.assertFalse((Path(root) / 'versions' / identity / (identity + '.json')).exists())
            return identity, metadata

        with (tempfile.TemporaryDirectory() as root,
              patch.object(loaders.MinecraftDownloader, 'install', install_game),
              patch.object(loaders, '_profile_loader', side_effect=prefetch)):
            result = loaders._install_loader('Fabric', '1.20.1', '0.15.0', root, None,
                {'setStatus': lambda _value: None, 'setProgress': lambda _value: None,
                 'setMax': lambda _value: None}, threading.Event(), '官方')
            self.assertEqual(result, identity)
            self.assertTrue((Path(root) / 'versions' / identity / (identity + '.json')).is_file())

    def test_fabric_libraries_download_together_before_profile_is_published(self):
        game_version, loader_version = '1.20.1', '0.15.0'
        identity = f'fabric-loader-{loader_version}-{game_version}'
        metadata = {'id': identity, 'inheritsFrom': game_version, 'libraries': [
            {'name': f'example:library-{number}:1', 'downloads': {'artifact': {
                'url': f'https://maven.fabricmc.net/example/library-{number}.jar'}}}
            for number in range(2)]}
        response = Mock()
        response.json.return_value = metadata
        barrier = threading.Barrier(2)
        progress = []

        def fetch(downloader, _url, relative, *_args):
            barrier.wait(timeout=2)
            target = downloader.inside(relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b'library')
            return target

        with (tempfile.TemporaryDirectory() as root,
              patch.object(loaders, '_response', return_value=response),
              patch.object(loaders.MinecraftDownloader, 'fetch', fetch)):
            installed = loaders._profile_loader('Fabric', game_version, loader_version, root,
                {'setStatus': lambda _message: None, 'setMax': lambda maximum: progress.append(('max', maximum)),
                 'setProgress': lambda done: progress.append(('done', done))}, threading.Event(), '官方')
            self.assertEqual(installed, identity)
            self.assertTrue((Path(root) / 'versions' / identity / (identity + '.json')).is_file())
        self.assertIn(('max', 2), progress)
        self.assertIn(('done', 2), progress)

    def response(self, content=None, records=None):
        response = Mock()
        response.content = content
        response.json.return_value = records
        return response

    def test_forge_mirror_accepts_build_objects_and_preserves_branch(self):
        records = [
            {'mcversion': '1.7.10', 'version': '10.13.4.1614', 'branch': '1.7.10'},
            {'mcversion': '1.7.10', 'version': '10.13.4.1558', 'branch': None},
            {'mcversion': '1.7.10', 'version': '10.13.4.1614', 'branch': '1.7.10'},
            {'mcversion': '1.8', 'version': '11.14.0.1281'},
            None,
        ]
        with patch.object(loaders.requests, 'get', return_value=self.response(records=records)) as get:
            versions = loaders.available_versions('Forge', '1.7.10', 'BMCLAPI')
        self.assertEqual(versions, ['10.13.4.1614-1.7.10', '10.13.4.1558'])
        self.assertEqual(get.call_count, 1)
        self.assertIn('/forge/minecraft/1.7.10', get.call_args.args[0])

    def test_official_forge_maven_filters_game_and_sorts_builds_numerically(self):
        metadata = b'''<metadata><versioning><versions>
        <version>1.20.1-47.2.9</version><version>1.19.4-45.1.0</version>
        <version>1.20.1-47.10.0</version><version>1.20.1-47.2.10</version>
        </versions></versioning></metadata>'''
        with patch.object(loaders.requests, 'get', return_value=self.response(content=metadata)):
            versions = loaders.available_versions('Forge', '1.20.1', '官方')
        self.assertEqual(versions, ['47.10.0', '47.2.10', '47.2.9'])

    def test_forge_automatic_fallback_parses_mirror_contract(self):
        offline = Mock()
        offline.raise_for_status.side_effect = OSError('offline')
        mirror = self.response(records=[{'mcversion': '1.20.1', 'version': '47.4.0'}])
        with patch.object(loaders.requests, 'get', side_effect=[offline, mirror]) as get:
            self.assertEqual(loaders.available_versions('Forge', '1.20.1', '自动'), ['47.4.0'])
        self.assertEqual(get.call_count, 2)

    def test_no_matching_build_reports_no_compatible_version(self):
        response = self.response(records=[{'mcversion': '1.20.1', 'version': '47.4.0'}])
        with patch.object(loaders.requests, 'get', return_value=response):
            with self.assertRaisesRegex(ValueError, '暂无适用于 Minecraft 1.21.8'):
                loaders.available_versions('Forge', '1.21.8', 'BMCLAPI')

    def test_installed_forge_profile_is_resolved_from_its_library_coordinate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            actual = 'legacy-custom-forge-profile'
            version = root / 'versions' / actual
            version.mkdir(parents=True)
            (version / (actual + '.json')).write_text(
                '{\"libraries\":[{\"name\":\"net.minecraftforge:forge:1.20.1-47.2.0:client\"}]}',
                encoding='utf-8')
            self.assertEqual(loaders._installed_forge_version(root, '1.20.1', '47.2.0'), actual)

    def test_forge_profile_is_flattened_and_fresh_vanilla_intermediate_is_removed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            versions = root / 'versions'
            base = versions / '1.20.1'
            forge = versions / '1.20.1-forge-47.4.0'
            base.mkdir(parents=True)
            forge.mkdir(parents=True)
            (base / '1.20.1.json').write_text(json.dumps({'id': '1.20.1', 'mainClass': 'net.minecraft.client.main.Main',
                'libraries': [{'name': 'com.example:base:1'}], 'arguments': {'game': ['base']}}), encoding='utf-8')
            (base / '1.20.1.jar').write_bytes(b'client')
            (base / 'natives').mkdir()
            (base / 'natives/base.dll').write_bytes(b'base')
            (forge / 'natives').mkdir()
            (forge / 'natives/forge.dll').write_bytes(b'forge')
            (forge / '1.20.1-forge-47.4.0.json').write_text(json.dumps({'id': 'forge', 'inheritsFrom': '1.20.1',
                'mainClass': 'cpw.mods.bootstraplauncher.BootstrapLauncher',
                'libraries': [{'name': 'net.minecraftforge:forge:1.20.1-47.4.0'}]}), encoding='utf-8')
            loaders._flatten_forge_version(root, forge.name, '1.20.1', set())
            metadata = json.loads((forge / (forge.name + '.json')).read_text(encoding='utf-8'))
            self.assertNotIn('inheritsFrom', metadata)
            self.assertEqual(metadata['id'], forge.name)
            self.assertEqual({item['name'] for item in metadata['libraries']},
                             {'com.example:base:1', 'net.minecraftforge:forge:1.20.1-47.4.0'})
            self.assertEqual((forge / (forge.name + '.jar')).read_bytes(), b'client')
            self.assertEqual((forge / 'natives/base.dll').read_bytes(), b'base')
            self.assertEqual((forge / 'natives/forge.dll').read_bytes(), b'forge')
            self.assertFalse(base.exists())

    def test_forge_flattening_keeps_preexisting_or_referenced_vanilla_versions(self):
        for mode in ('preexisting', 'referenced'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                versions = root / 'versions'
                base = versions / '1.20.1'
                forge = versions / 'forge-profile'
                base.mkdir(parents=True)
                forge.mkdir(parents=True)
                (base / '1.20.1.json').write_text('{"id":"1.20.1"}', encoding='utf-8')
                (base / '1.20.1.jar').write_bytes(b'client')
                (forge / 'forge-profile.json').write_text('{"id":"forge-profile","inheritsFrom":"1.20.1"}', encoding='utf-8')
                if mode == 'referenced':
                    other = versions / 'other'
                    other.mkdir()
                    (other / 'other.json').write_text('{"id":"other","inheritsFrom":"1.20.1"}', encoding='utf-8')
                before = {'1.20.1'} if mode == 'preexisting' else set()
                loaders._flatten_forge_version(root, 'forge-profile', '1.20.1', before)
                self.assertTrue(base.exists())

    def test_loader_download_has_timeout_and_falls_back_without_global_patches(self):
        import requests
        import threading
        session = Mock()
        session.get.side_effect = [requests.Timeout('temporary outage'), Mock()]
        def download(url, path, callback, sha1, compressed, scoped, directory, overwrite):
            scoped.get(url, stream=True)
            Path(path).write_bytes(b'installer')
            return True
        with tempfile.TemporaryDirectory() as temp:
            path = str(Path(temp) / 'installer.jar')
            wrapped = loaders._routed_downloader(download, '自动')
            self.assertTrue(wrapped('https://maven.minecraftforge.net/installer.jar', path,
                                    callback={}, session=session))
        self.assertEqual(session.get.call_count, 2)
        self.assertEqual(session.get.call_args.kwargs['timeout'], (8, 20))
        self.assertTrue(session.get.call_args.args[0].startswith(loaders.BMCLAPI))
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(InterruptedError):
            loaders._LoaderSession(session, cancel).get('https://example.org')

    def test_neoforge_installer_libraries_follow_selected_source_and_verify_profile_paths(self):
        payload = b'verified NeoForge dependency'
        digest = hashlib.sha1(payload).hexdigest()
        profile = {'libraries': [
            {'name': 'net.neoforged:example:1.0', 'downloads': {'artifact': {
                'url': 'https://maven.neoforged.net/releases/net/neoforged/example/1.0/example-1.0.jar',
                'path': 'net/neoforged/example/1.0/example-1.0.jar', 'sha1': digest, 'size': len(payload)}}},
            {'name': 'com.google.code.gson:gson:2.8.9', 'downloads': {'artifact': {
                'url': 'https://libraries.minecraft.net/com/google/code/gson/gson/2.8.9/gson-2.8.9.jar',
                'path': 'com/google/code/gson/gson/2.8.9/gson-2.8.9.jar', 'sha1': digest, 'size': len(payload)}}},
        ]}
        installer = io.BytesIO()
        with zipfile.ZipFile(installer, 'w') as archive:
            archive.writestr('install_profile.json', json.dumps(profile))
        installer.seek(0)
        with tempfile.TemporaryDirectory() as temporary:
            installer_path = Path(temporary) / 'installer.jar'
            installer_path.write_bytes(installer.getvalue())
            for source, mirror_first in (('自动', False), ('官方', False), ('BMCLAPI', True)):
                root = Path(temporary) / source
                calls = []
                def fake_fetch(downloader, url, relative, sha1, size):
                    candidates = downloader.urls(url)
                    calls.append((url, relative, sha1, size, candidates))
                    target = downloader.inside(relative)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(payload)
                    return target
                callback_values = []
                callback = dict(setStatus=lambda _message: None, setMax=lambda value: callback_values.append(('max', value)),
                                setProgress=lambda value: callback_values.append(('progress', value)))
                with patch.object(loaders.MinecraftDownloader, 'fetch', fake_fetch):
                    loaders._prefetch_neoforge_libraries(installer_path, root, callback,
                                                          __import__('threading').Event(), source)
                self.assertEqual(len(calls), 2)
                self.assertTrue(all(root.joinpath(row[1]).read_bytes() == payload for row in calls))
                self.assertTrue(all(row[2] == digest and row[3] == len(payload) for row in calls))
                for url, _relative, _sha1, _size, candidates in calls:
                    if mirror_first:
                        self.assertIn(loaders.BMCLAPI, candidates[0])
                        self.assertNotIn('/maven/releases/', candidates[0])
                    elif source == '官方':
                        self.assertEqual(candidates, [url])
                    else:
                        self.assertEqual(candidates[0], url)
                        self.assertIn(loaders.BMCLAPI, candidates[1])
                self.assertEqual(callback_values[0], ('max', 2))

            malicious = dict(profile)
            malicious['libraries'] = [dict(profile['libraries'][0], downloads={'artifact': dict(
                profile['libraries'][0]['downloads']['artifact'], path='../escape.jar')})]
            with zipfile.ZipFile(installer_path, 'w') as archive:
                archive.writestr('install_profile.json', json.dumps(malicious))
            with patch.object(loaders.MinecraftDownloader, 'fetch') as fetch:
                with self.assertRaisesRegex(RuntimeError, '有效路径'):
                    loaders._prefetch_neoforge_libraries(installer_path, Path(temporary) / 'unsafe', callback,
                                                          __import__('threading').Event(), 'BMCLAPI')
                fetch.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
