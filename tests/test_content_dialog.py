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


if __name__ == '__main__':
    unittest.main()
