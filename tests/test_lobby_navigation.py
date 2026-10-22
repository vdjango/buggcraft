"""Navigation exposes room management only when a session has room records."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / '.test-tools'), str(ROOT / 'buggcraft/src/buggcraft')]
from PySide6.QtWidgets import QApplication, QDialog
from ui.multiplayer_controller import MultiplayerController


class LobbyNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.window = QDialog()
        self.addCleanup(self.window.close)
        with patch('ui.multiplayer_controller.TunnelService', return_value=Mock(endpoints={})):
            self.controller = MultiplayerController(self.window, Path(temporary.name) / 'lobby.json')
        self.addCleanup(self.controller.close)

    def test_empty_room_navigation_returns_to_hall(self):
        self.controller.act('navigate', {'page': 'connections'})
        self.assertEqual(self.controller.view['page'], 'hall')
        self.assertEqual(self.controller.view['error'], '')

    def test_created_and_joined_room_records_enable_management(self):
        for role in ('host', 'client'):
            for state in ('connecting', 'online', 'reconnecting'):
                with self.subTest(role=role, state=state):
                    self.controller.records['room'] = dict(id='room', title='World', role=role, state=state)
                    self.controller.publish_connections()
                    self.controller.act('navigate', {'page': 'connections'})
                    self.assertEqual(self.controller.view['page'], 'connections')
                    self.assertEqual(self.controller.view['connections'][0]['role'], role)

    def test_terminal_room_events_remove_session_and_chat_without_history(self):
        for terminal in ('closed', 'stopped', 'error'):
            with self.subTest(terminal=terminal):
                self.controller.records['room'] = dict(id='room', role='client', state='online',
                    chatMessages=[{'text':'private history'}], chatDraft='draft')
                self.controller.patch(selected='room', page='connected')
                self.controller.update_status('room', terminal, '房间已关闭')
                self.assertEqual(self.controller.view['connections'], [])
                self.assertEqual(self.controller.view['chatMessages'], [])
                self.assertEqual(self.controller.view['chatDraft'], '')
                self.assertEqual(self.controller.view['page'], 'hall')
                self.assertEqual(self.controller.view['selected'], '')
                self.controller.update_status('room', 'online', 'late event')
                self.assertEqual(self.controller.records, {})

    def test_waiting_world_preserves_room_and_chat_until_explicit_exit(self):
        self.controller.records['room'] = dict(id='room', role='client', state='online',
            chatMessages=[{'text':'retained'}], bridgeStatus='游戏聊天等待世界')
        self.controller.patch(selected='room', page='connected')
        self.controller.update_chat('room', {'type':'room','state':'waiting'})
        self.assertEqual(self.controller.view['connections'][0]['availability'], 'waiting')
        self.assertEqual(self.controller.view['chatMessages'][0]['text'], 'retained')
        self.controller.act('stop', {'id':'room'})
        self.assertEqual(self.controller.view['connections'], [])
        self.assertEqual(self.controller.view['page'], 'hall')


if __name__ == '__main__':
    unittest.main()
