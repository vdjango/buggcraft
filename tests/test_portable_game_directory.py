"""Deployed downloads must not follow an IDE, shortcut, or runtime cache cwd."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/buggcraft'))
from config.settings import SettingsManager
from utils import path_helper


class PortableGameDirectoryTests(unittest.TestCase):
    def test_packaged_directory_does_not_follow_working_directory(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {}, clear=True):
            executable = Path(temp) / 'launcher/Buggcraft.exe'
            with patch.object(sys, 'frozen', True, create=True), \
                    patch.object(sys, 'executable', str(executable)), \
                    patch.object(Path, 'cwd', return_value=Path(temp) / 'source'):
                self.assertEqual(path_helper.get_default_minecraft_dir(), executable.parent / '.minecraft')

    def test_bootstrap_directory_wins_over_versioned_runtime(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp) / '启动器'
            with patch.dict(os.environ, BUGGCRAFT_LAUNCHER_DIR=str(home)), \
                    patch.object(sys, 'frozen', True, create=True), \
                    patch.object(sys, 'executable', str(home / 'Buggcraft-runtime/hash/Buggcraft.exe')):
                self.assertEqual(path_helper.get_default_minecraft_dir(), home / '.minecraft')

    def test_mac_game_data_is_beside_app_not_inside_bundle(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {}, clear=True):
            root = Path(temp)
            with patch.object(sys, 'frozen', True, create=True), \
                    patch.object(sys, 'executable', str(root / 'Buggcraft.app/Contents/MacOS/Buggcraft')):
                self.assertEqual(path_helper.get_default_minecraft_dir(), root / '.minecraft')

    def test_fresh_settings_use_launcher_directory_and_empty_legacy_settings_recover(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp) / 'launcher'
            config = Path(temp) / 'unrelated-config'
            with patch.dict(os.environ, BUGGCRAFT_LAUNCHER_DIR=str(home)):
                manager = SettingsManager(config)
                self.assertEqual(manager.get_setting('minecraft.directory.enable'), str(home / '.minecraft'))
                manager.set_setting('minecraft.directory.enable', None)
                manager.set_setting('minecraft.directory.installed', [])
                manager.save_settings()
                recovered = SettingsManager(config)
                self.assertEqual(recovered.get_setting('minecraft.directory.enable'), str(home / '.minecraft'))
                self.assertIn(str(home / '.minecraft'), recovered.get_setting('minecraft.directory.installed'))

    def test_existing_explicit_game_directory_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / 'config'
            config.mkdir()
            selected = str(Path(temp) / 'custom-game')
            (config / 'settings.json').write_text(json.dumps({
                'minecraft': {'directory': {'enable': selected, 'installed': [selected]}}
            }), encoding='utf-8')
            manager = SettingsManager(config)
            self.assertEqual(manager.get_setting('minecraft.directory.enable'), selected)

    def test_download_queue_uses_portable_root_when_selection_is_empty(self):
        from PySide6.QtWidgets import QApplication, QWidget
        from ui.pages.download.tasks import TasksPage
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp) / 'launcher'
            with patch.dict(os.environ, BUGGCRAFT_LAUNCHER_DIR=str(home)):
                manager = SettingsManager(Path(temp) / 'config')
                manager.set_setting('minecraft.directory.enable', None)
                parent = QWidget()
                parent.resource_path = str(Path(temp) / 'resources')
                parent.on_progress_clicked = Mock()
                with patch('ui.pages.download.tasks.get_settings_manager', return_value=manager):
                    page = TasksPage(parent)
                try:
                    with patch.object(page.pool, 'start') as enqueue:
                        self.assertTrue(page.start_install('1.20.1', None))
                    worker = enqueue.call_args.args[0]
                    metadata = home / '.minecraft/versions/1.20.1/1.20.1.json'
                    def install(version):
                        metadata.parent.mkdir(parents=True, exist_ok=True)
                        metadata.write_text(json.dumps({'id': version}), encoding='utf-8')
                    with patch('ui.pages.download.tasks.MinecraftDownloader') as downloader:
                        downloader.return_value.install.side_effect = install
                        worker.run()
                    self.assertEqual(downloader.call_args.args[0], str(home / '.minecraft'))
                    self.assertTrue(metadata.is_file())
                    self.assertFalse((Path(temp) / 'config/minecraft').exists())
                    self.assertEqual(manager.get_setting('minecraft.directory.enable'), str(home / '.minecraft'))
                finally:
                    page.shutdown()
                    parent.close()
                    app.processEvents()


if __name__ == '__main__':
    unittest.main()
