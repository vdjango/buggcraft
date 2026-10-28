"""Busy clipboard handling must preserve the latest request and report failure."""
import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QObject
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from utils.clipboard import cancel_copy, copy_text


class ClipboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.owner = QObject()
        self.addCleanup(cancel_copy, self.owner)
        self.success, self.failure = Mock(), Mock()

    def wait_for(self, predicate):
        for _ in range(150):
            if predicate():
                return
            QTest.qWait(10)
        self.assertTrue(predicate())

    def test_busy_clipboard_retries_and_only_then_reports_success(self):
        clipboard = Mock()
        clipboard.text.side_effect = ['', '', 'expected']
        with patch('utils.clipboard.QApplication.clipboard', return_value=clipboard):
            copy_text(self.owner, 'expected', self.success, self.failure)
            self.success.assert_not_called()
            self.wait_for(lambda: self.success.called)
        self.assertEqual(clipboard.setText.call_count, 3)
        self.success.assert_called_once_with()
        self.failure.assert_not_called()
        self.assertIsNone(self.owner._clipboard_copy_timer)

    def test_permanently_busy_clipboard_has_bounded_failure(self):
        clipboard = Mock()
        clipboard.text.return_value = ''
        with patch('utils.clipboard.QApplication.clipboard', return_value=clipboard):
            copy_text(self.owner, 'expected', self.success, self.failure)
            self.wait_for(lambda: self.failure.called)
        self.assertEqual(clipboard.setText.call_count, 20)
        self.success.assert_not_called()
        self.failure.assert_called_once_with()

    def test_new_copy_cancels_old_pending_request(self):
        clipboard = Mock()
        clipboard.text.side_effect = ['', 'new']
        old_success, old_failure = Mock(), Mock()
        with patch('utils.clipboard.QApplication.clipboard', return_value=clipboard):
            copy_text(self.owner, 'old', old_success, old_failure)
            copy_text(self.owner, 'new', self.success, self.failure)
            QTest.qWait(80)
        self.assertEqual([call.args[0] for call in clipboard.setText.call_args_list], ['old', 'new'])
        old_success.assert_not_called()
        old_failure.assert_not_called()
        self.success.assert_called_once_with()

    def test_close_cancels_pending_clipboard_write(self):
        clipboard = Mock()
        clipboard.text.return_value = ''
        with patch('utils.clipboard.QApplication.clipboard', return_value=clipboard):
            copy_text(self.owner, 'expected', self.success, self.failure)
            cancel_copy(self.owner)
            QTest.qWait(80)
        clipboard.setText.assert_called_once_with('expected')
        self.success.assert_not_called()
        self.failure.assert_not_called()
