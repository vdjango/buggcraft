"""Home entries must restore minimized multiplayer windows."""
import os
from pathlib import Path
import sys
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT.parent / '.test-tools'), str(ROOT / 'src/buggcraft')]

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog
from ui.dialog.MultiplayerDialog import MultiplayerDialog
from ui.pages.started_game import StartGamePage


class LobbyOpeningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.page = QDialog()
        from unittest.mock import Mock
        self.page._social_changed = Mock()
        self.addCleanup(self.page.close)
        self.dialog = MultiplayerDialog(self.page, Path(self.temporary.name) / 'lobby.json')
        self.page._multiplayer_dialog = self.dialog
        self.addCleanup(self.dialog.shutdown)

    def test_home_entry_restores_minimized_lobby_without_replacing_it(self):
        self.dialog.show()
        self.dialog.showMinimized()
        QTest.qWait(20)
        self.assertTrue(self.dialog.isMinimized())
        StartGamePage.show_multiplayer_dialog(self.page)
        QTest.qWait(20)
        self.assertTrue(self.dialog.isVisible())
        self.assertFalse(self.dialog.isMinimized())
        self.assertIs(self.page._multiplayer_dialog, self.dialog)
        self.assertIsNotNone(self.dialog.quick.rootObject())
        self.assertFalse(self.dialog.backend.closed)

    def test_home_entry_reopens_closed_lobby(self):
        self.dialog.show()
        self.dialog.close()
        self.assertFalse(self.dialog.isVisible())
        StartGamePage.show_multiplayer_dialog(self.page)
        QTest.qWait(20)
        self.assertTrue(self.dialog.isVisible())
        self.assertFalse(self.dialog.isMinimized())
        self.assertFalse(self.dialog.backend.closed)

    def test_friend_entry_restores_minimized_friends_window(self):
        self.dialog.backend.patch(socialReady=True)
        self.dialog.show_friends()
        friends = self.dialog.friends_window
        friends.showMinimized()
        QTest.qWait(20)
        self.assertTrue(friends.isMinimized())
        StartGamePage.show_friends_dialog(self.page)
        QTest.qWait(20)
        self.assertTrue(friends.isVisible())
        self.assertFalse(friends.isMinimized())
        self.assertIs(self.dialog.friends_window, friends)
        self.assertIsNotNone(friends.quick.rootObject())

    def test_anonymous_home_friend_entry_opens_lobby_for_authentication(self):
        from unittest.mock import patch
        with patch.object(self.page, 'show_multiplayer_dialog', create=True) as open_lobby:
            StartGamePage.show_friends_dialog(self.page)
        open_lobby.assert_called_once_with()
        self.assertIsNone(self.dialog.friends_window)


if __name__ == '__main__':
    unittest.main(verbosity=2)
