"""Mod metadata validation and isolated configuration using the native bridge boundary."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/buggcraft'))
from hookup.modpack import validate_manifest
from hookup.preparation import resolved_metadata
from config.settings import SettingsManager
from core.launch_options import configure_room_join


class ModManifestTests(unittest.TestCase):
    def test_optional_resources_allow_same_basename_in_distinct_folders_only(self):
        item = dict(name='same.zip', path='resourcepacks/same.zip', sha256='a' * 64, size=10)
        validate_manifest([item, dict(item, path='shaderpacks/same.zip')], 'resources')
        for path in ('../same.zip', 'mods/same.zip', 'resourcepacks/sub/same.zip',
                     'resourcepacks/../same.zip', 'resourcepacks\\same.zip'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                validate_manifest([dict(item, path=path)], 'resources')
        with self.assertRaises(ValueError):
            validate_manifest([item, dict(item, name='SAME.zip', path='resourcepacks/SAME.zip')], 'resources')

    def test_resolved_loader_keeps_native_classifiers_and_overrides_library_version(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent = dict(id='base', libraries=[{'name': 'org.lwjgl:lwjgl:3.3.1'},
                {'name': 'org.lwjgl:lwjgl:3.3.1:natives-windows'},
                {'name': 'org.lwjgl:lwjgl:3.3.1:natives-linux'}], arguments={'game': ['base']})
            child = dict(id='fabric', inheritsFrom='base', libraries=[{'name': 'org.lwjgl:lwjgl:3.3.2'}],
                         arguments={'game': ['loader']})
            for value in (parent, child):
                path = root / 'versions' / value['id'] / (value['id'] + '.json')
                path.parent.mkdir(parents=True)
                path.write_text(json.dumps(value))
            metadata = resolved_metadata(root, 'fabric')
            names = [item['name'] for item in metadata['libraries']]
            self.assertIn('org.lwjgl:lwjgl:3.3.2', names)
            self.assertIn('org.lwjgl:lwjgl:3.3.1:natives-windows', names)
            self.assertIn('org.lwjgl:lwjgl:3.3.1:natives-linux', names)
            self.assertNotIn('org.lwjgl:lwjgl:3.3.1', names)
            self.assertEqual(metadata['arguments']['game'], ['base', 'loader'])
            self.assertEqual(metadata['jar'], 'base')
            self.assertNotIn('inheritsFrom', metadata)

    def test_untrusted_paths_duplicates_and_sizes_are_rejected(self):
        item = dict(name='safe.jar', sha256='a' * 64, size=10)
        validate_manifest([item])
        for name in ('../bad.jar', 'C:bad.jar', 'folder/bad.jar', 'folder\\bad.jar', 'bad.exe'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_manifest([{**item, 'name': name}])
        with self.assertRaises(ValueError):
            validate_manifest([item, {**item, 'name': 'SAFE.jar'}])
        for size in (-1, True, 2 ** 40):
            with self.assertRaises(ValueError):
                validate_manifest([{**item, 'size': size}])

    def test_room_configuration_keeps_isolation_when_global_is_disabled(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = SettingsManager(str(root / 'settings'))
            settings.set_setting('minecraft.directory.enable', str(root))
            settings.set_setting('minecraft.version.enable', 'room-example')
            settings.set_setting('minecraft.isolation', False)
            path = root / 'versions/room-example/room-example.json'
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({'buggcraftRoom': {}}))
            self.assertEqual(Path(settings.get_minecraft_isolation_directory()), path.parent)

    def test_quick_play_and_legacy_ports_use_the_installed_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for identity, metadata in (('old', {}), ('new', {'arguments': {'game': [
                    {'rules': [{'action': 'allow', 'features': {'is_quick_play_multiplayer': True}}],
                     'value': ['--quickPlayMultiplayer', '${quickPlayMultiplayer}']}]}})):
                path = root / 'versions' / identity / (identity + '.json')
                path.parent.mkdir(parents=True)
                path.write_text(json.dumps(metadata))
                options = {'gameDirectory': str(path.parent)}
                configure_room_join(options, '127.0.0.1:45678', root, identity)
                if identity == 'old':
                    self.assertEqual(options['server'], '127.0.0.1')
                    self.assertEqual(options['port'], '45678')
                else:
                    self.assertEqual(options['quickPlayMultiplayer'], '127.0.0.1:45678')
                    self.assertNotIn('server', options)
