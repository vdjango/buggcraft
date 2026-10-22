import os
import sys
import threading
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / 'buggcraft'))
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from ui.dialog.ContentDownloadDialog import ContentDownloadDialog
from PySide6.QtCore import Qt


class ContentDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_type_change_invalidates_a_search_running_in_background(self):
        dialog = ContentDownloadDialog(None, '1.20.1', 'fabric')
        started, release = threading.Event(), threading.Event()

        def slow_search(*_args):
            started.set()
            if not release.wait(3):
                raise TimeoutError('test search gate was not released')
            return [{'project_id': 'stale', 'title': 'Stale result'}]

        dialog.client.search = slow_search
        try:
            dialog.search()
            self.assertTrue(started.wait(2))
            self.assertFalse(dialog.search_button.isEnabled())
            dialog.kind.setCurrentIndex(dialog.kind.findData('resourcepack'))
            self.assertTrue(dialog.search_button.isEnabled())
            self.assertIsNone(dialog.selected_version)
            self.assertFalse(dialog.install.isEnabled())
            release.set()
            for _ in range(30):
                self.app.processEvents()
                QTest.qWait(10)
            self.assertEqual(dialog.results.count(), 0)
        finally:
            release.set()
            dialog.reject()
            self.app.processEvents()

    def test_source_change_clears_selection_and_results_keep_their_provider(self):
        dialog = ContentDownloadDialog(None, '1.20.1', 'fabric')
        try:
            dialog._query_finished(dialog._request_id, 'search', [
                {'project_id':'10','title':'Sample','source':'CurseForge'}], '')
            item = dialog.results.item(0)
            self.assertIn('[CurseForge]', item.text())
            self.assertEqual(item.data(Qt.ItemDataRole.UserRole), {'project_id':'10','source':'CurseForge'})
            dialog._query_finished(dialog._request_id, 'versions', [{'name':'Sample','files':[]}], '')
            self.assertTrue(dialog.install.isEnabled())
            dialog.source.setCurrentText('Modrinth')
            self.assertEqual(dialog.results.count(), 0)
            self.assertIsNone(dialog.selected_version)
            self.assertFalse(dialog.install.isEnabled())
        finally:
            dialog.reject()


if __name__ == '__main__':
    unittest.main()
