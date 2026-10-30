"""Exercise folder moves, migrations, resume files and protected local accounts."""
import errno
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from utils import storage_paths as storage
from utils.portable_credentials import PortableCredentials


class PortableStorageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.launcher = self.base / 'original' / 'bugg'
        self.launcher.mkdir(parents=True)
        self.addCleanup(patch.stopall)
        patch.object(storage, 'get_launcher_directory', side_effect=lambda: self.launcher).start()
        patch('config.settings._settings_manager_instance', None).start()
        patch.dict(os.environ).start()
        old_temp, old_bytecode = tempfile.tempdir, __import__('sys').dont_write_bytecode
        self.addCleanup(lambda: setattr(tempfile, 'tempdir', old_temp))
        self.addCleanup(lambda: setattr(__import__('sys'), 'dont_write_bytecode', old_bytecode))

    def test_every_startup_directory_is_portable_even_with_foreign_home_and_cwd(self):
        foreign = self.base / 'unrelated'
        foreign.mkdir()
        with patch.dict(os.environ, {'APPDATA': str(foreign), 'LOCALAPPDATA': str(foreign), 'USERPROFILE': str(foreign)}):
            root = storage.initialize_storage()
            self.assertEqual(root, self.launcher / '.buggcraft')
            self.assertTrue(storage.cache_directory('updates').is_relative_to(root))
            self.assertTrue(storage.temporary_directory().is_relative_to(root))
            self.assertTrue(storage.game_cache(self.launcher / '.minecraft').is_relative_to(root))
            with tempfile.TemporaryDirectory() as path:
                self.assertTrue(Path(path).is_relative_to(root))
            self.assertEqual(list(foreign.iterdir()), [])

    def test_custom_migration_copies_configuration_java_and_resume_without_touching_source(self):
        old = storage.initialize_storage()
        game = self.launcher / '.minecraft'
        java = old / 'java/runtime/bin/java.exe'
        java.parent.mkdir(parents=True)
        java.write_bytes(b'java runtime')
        (old / 'settings.json').write_text(json.dumps({'java': {'path': str(java)}, 'game': str(game), 'opacity': 63}))
        partial = storage.game_cache(game) / 'mod.jar.buggcraft-part'
        partial.write_bytes(b'already downloaded')
        target = self.launcher / 'launcher-data'
        storage.request_storage(target)
        self.assertEqual(storage.storage_root(), old)
        self.assertEqual((self.launcher / storage.PENDING).read_text().strip(), 'launcher-data')
        root = storage.initialize_storage()
        self.assertEqual(root, target)
        self.assertEqual((self.launcher / storage.LOCATION).read_text().strip(), 'launcher-data')
        data = json.loads((target / 'settings.json').read_text())
        self.assertEqual(data['java']['path'], str(target / java.relative_to(old)))
        self.assertEqual(data['game'], str(game))
        self.assertEqual((target / partial.relative_to(old)).read_bytes(), b'already downloaded')
        self.assertEqual(partial.read_bytes(), b'already downloaded')
        self.assertTrue(java.exists())
        self.assertFalse((self.launcher / storage.PENDING).exists())

    def test_move_whole_folder_rebases_settings_history_java_nodes_and_cached_game_key(self):
        old = storage.initialize_storage()
        game = self.launcher / '.minecraft'
        java = old / 'java/bin/java.exe'
        node = old / 'cache/multiplayer/node.json'
        node.parent.mkdir(parents=True)
        node.write_text('{}')
        (node.parent / 'lobby.json').write_text(json.dumps({'nodes': [str(node)]}))
        (old / 'settings.json').write_text(json.dumps({'minecraft': {'directory': {'enable': str(game)}}, 'java': str(java), 'external': str(self.base / 'external')}))
        (old / 'download_history.json').write_text(json.dumps([{'game_dir': str(game), 'modpack': str(old / 'cache/pack.zip')}]))
        key = storage.game_cache(game).name
        moved = self.base / 'extracted' / 'bugg'
        moved.parent.mkdir()
        shutil.copytree(self.launcher, moved)
        original = self.launcher
        self.launcher = moved
        current = storage.initialize_storage()
        data = json.loads((current / 'settings.json').read_text())
        self.assertEqual(data['minecraft']['directory']['enable'], str(moved / '.minecraft'))
        self.assertEqual(data['java'], str(current / 'java/bin/java.exe'))
        self.assertEqual(data['external'], str(self.base / 'external'))
        self.assertEqual(json.loads((current / 'cache/multiplayer/lobby.json').read_text())['nodes'], [str(current / 'cache/multiplayer/node.json')])
        self.assertEqual(storage.game_cache(moved / '.minecraft').name, key)
        self.assertNotIn(str(original), (current / 'download_history.json').read_text())

    def test_custom_migration_preserves_long_library_paths_and_checkpoints(self):
        from utils.path_helper import filesystem_path
        old = storage.initialize_storage()
        relative = Path('cache') / ('loader-workspace-' * 5) / ('maven-library-' * 6) / 'artifact.jar.buggcraft-part.json'
        physical = filesystem_path(old / relative)
        physical.parent.mkdir(parents=True)
        physical.write_bytes(b'verified checkpoint')
        target = self.launcher / 'launcher-data'
        try:
            storage.request_storage(target)
            storage.initialize_storage()
            self.assertEqual(filesystem_path(target / relative).read_bytes(), b'verified checkpoint')
            self.assertEqual(physical.read_bytes(), b'verified checkpoint')
        finally:
            for root in (old, target):
                shutil.rmtree(filesystem_path(root / 'cache'), ignore_errors=True)

    def test_nonempty_nested_and_parent_destinations_are_rejected(self):
        root = storage.initialize_storage()
        occupied = self.launcher / 'occupied'
        occupied.mkdir()
        (occupied / 'keep.txt').write_text('keep')
        for destination in (occupied, root / 'inside', self.launcher, self.base):
            with self.subTest(destination=destination), self.assertRaises(ValueError):
                storage.request_storage(destination)
        self.assertEqual((occupied / 'keep.txt').read_text(), 'keep')
        self.assertFalse((self.launcher / storage.PENDING).exists())

    def test_failed_copy_keeps_original_location_and_configuration(self):
        old = storage.initialize_storage()
        (old / 'settings.json').write_text('{"opacity":63}')
        storage.request_storage(self.launcher / 'next')
        with patch.object(shutil, 'copytree', side_effect=OSError(errno.ENOSPC, 'disk full')):
            with self.assertRaises(OSError):
                storage.initialize_storage()
        self.assertEqual(storage.storage_root(), old)
        self.assertEqual((old / 'settings.json').read_text(), '{"opacity":63}')

    def test_download_metadata_and_installer_cache_use_selected_root(self):
        from core.downloads import MinecraftDownloader
        root = storage.initialize_storage()
        game = self.launcher / '.minecraft'
        downloader = MinecraftDownloader(game)
        path = downloader.inside('.buggcraft-downloads/neoforge-installer.jar')
        self.assertTrue(path.is_relative_to(root))
        self.assertFalse(path.is_relative_to(game))
        with self.assertRaises(ValueError):
            downloader.inside('.buggcraft-downloads/../../../../outside')
        self.assertEqual(downloader.inside('versions/1.21.1/1.21.1.jar'), game / 'versions/1.21.1/1.21.1.jar')

    def test_local_vault_keeps_secrets_out_of_json_and_survives_same_user_folder_move(self):
        root = storage.initialize_storage()
        vault = PortableCredentials()
        vault.set_password('service', 'account', 'private-secret')
        self.assertEqual(vault.get_password('service', 'account'), 'private-secret')
        self.assertNotIn('private-secret', (root / 'etc/credentials/vault.json').read_text())
        moved = self.base / 'moved'
        shutil.copytree(self.launcher, moved)
        self.launcher = moved
        storage.initialize_storage()
        self.assertEqual(PortableCredentials().get_password('service', 'account'), 'private-secret')

    def test_cross_volume_instance_publish_and_existing_target_protection(self):
        source, target = self.base / 'source', self.base / 'game/versions/pack'
        source.mkdir()
        target.parent.mkdir(parents=True)
        (source / 'pack.json').write_text('{"id":"pack"}')
        rename = Path.rename
        def cross_volume(path, destination):
            if path.name == 'source':
                raise OSError(errno.EXDEV, 'different drive')
            return rename(path, destination)
        with patch.object(Path, 'rename', cross_volume):
            storage.publish_directory(source, target)
        self.assertTrue((target / 'pack.json').is_file())
        self.assertFalse(source.exists())
        source.mkdir()
        with self.assertRaises(FileExistsError):
            storage.publish_directory(source, target)
        self.assertTrue((target / 'pack.json').is_file())


if __name__ == '__main__':
    unittest.main()
