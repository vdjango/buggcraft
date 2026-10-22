import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / 'buggcraft'))
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QWidget
from ui.pages.version.versions import VersionsPage


class InstanceModpackEntryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_entry_remains_clickable_after_refresh_and_directory_changes(self):
        tasks = Mock()
        parent = QWidget()
        parent.resource_path = str(Path(__file__).resolve().parents[1] / 'resources')
        parent.parent = SimpleNamespace(download_page=SimpleNamespace(tasks_page=tasks))
        manager = Mock()
        manager.get_setting.return_value = 'E:/games/default'
        with patch('ui.pages.version.versions.get_settings_manager', return_value=manager), \
                patch.object(VersionsPage, 'load_directory_data', return_value=[]), \
                patch.object(VersionsPage, 'scan_versions'), \
                patch.object(VersionsPage, 'on_add_directory') as import_game, \
                patch.object(VersionsPage, 'load_version_data') as load_versions:
            page = VersionsPage(parent)
            parent.resize(900, 600)
            page.resize(900, 600)
            parent.show()
            page.show()
            try:
                button = page.import_modpack_button
                for directory, versions in (
                    ('E:/games/first', [{'version': '1.20.1', 'description': 'Forge', 'is_selected': True}]),
                    ('E:/games/second', []),
                    ('E:/games/first', [{'version': '1.21', 'description': 'Fabric', 'is_selected': False}]),
                ):
                    item = QWidget()
                    item.setProperty('is_selected', True)
                    item.setProperty('path', directory)
                    page.directory_items = [item]
                    load_versions.return_value = versions
                    page.refresh_version_list(directory)
                    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
                    self.app.processEvents()
                    self.assertTrue(button.isVisible())
                    self.assertTrue(page.import_game_button.isVisible())
                    self.assertEqual(len(page.version_items), len(versions))
                    self.assertEqual(page.version_items_layout.count(), len(versions) + 1)
                    button.click()
                    tasks.import_modpack.assert_called_with(game_dir=directory)
                    page.import_game_button.click()
                    import_game.assert_called_with(None)
                self.assertEqual(tasks.import_modpack.call_count, 3)
                self.assertEqual(import_game.call_count, 3)
            finally:
                page.close()
                parent.close()

    def test_import_uses_the_selected_game_directory(self):
        selected = SimpleNamespace(property=lambda key: {
            'path': 'E:/games/selected', 'is_selected': True,
        }[key])
        tasks = Mock()
        page = SimpleNamespace(
            directory_items=[selected],
            settings_manager=Mock(),
            parent=SimpleNamespace(parent=SimpleNamespace(
                download_page=SimpleNamespace(tasks_page=tasks),
            )),
        )

        VersionsPage.import_modpack(page)

        tasks.import_modpack.assert_called_once_with(game_dir='E:/games/selected')

    def test_import_falls_back_to_configured_game_directory(self):
        tasks = Mock()
        manager = Mock()
        manager.get_setting.return_value = 'E:/games/default'
        page = SimpleNamespace(
            directory_items=[], settings_manager=manager,
            parent=SimpleNamespace(parent=SimpleNamespace(
                download_page=SimpleNamespace(tasks_page=tasks),
            )),
        )

        VersionsPage.import_modpack(page)

        tasks.import_modpack.assert_called_once_with(game_dir='E:/games/default')


if __name__ == '__main__':
    unittest.main()
