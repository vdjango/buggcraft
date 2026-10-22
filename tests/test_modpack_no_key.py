"""The player-facing import flow requires no API credentials."""
import os
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/buggcraft'))
from PySide6.QtWidgets import QApplication, QLineEdit
from ui.dialog.ModpackImportDialog import ModpackImportDialog
from ui.pages.download_page import DownloadPages


class ModpackNoKeyTests(unittest.TestCase):
    def test_import_form_has_only_archive_and_instance_name(self):
        app = QApplication.instance() or QApplication([])
        dialog = ModpackImportDialog(game_dir='portable/.minecraft')
        self.assertFalse(hasattr(dialog, 'key_input'))
        self.assertFalse(hasattr(dialog, 'api_key'))
        self.assertEqual(set(dialog.findChildren(QLineEdit)), {dialog.archive_input, dialog.name_input})
        dialog.close()
        app.processEvents()

    def test_import_progress_opens_main_download_page_before_its_history_tab(self):
        calls = Mock()
        page = SimpleNamespace(parent=SimpleNamespace(switch_pages=calls.main),
                               update_button_style=calls.style, switch_pages=calls.tab)
        DownloadPages.on_progress_clicked(page)
        self.assertEqual(calls.mock_calls[0].args, ('下载',))
        calls.main.assert_called_once_with('下载')
        calls.tab.assert_called_once_with('下载记录')


if __name__ == '__main__':
    unittest.main()
