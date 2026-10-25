"""Catalogue contracts from the official Maven metadata and BMCLAPI documentation."""
from pathlib import Path
import sys
import tempfile
import unittest
import json
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / 'buggcraft'))
from core import loaders


class LoaderCatalogueTests(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main(verbosity=2)
