"""Real independent child processes test multi-launch and targeted stopping."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/buggcraft'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QSignalSpy
from config.settings import SettingsManager
from core.game_sessions import GameSessions


class GameSessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.settings = SettingsManager(str(self.root / 'config'))
        probe = patch('config.javafinder.JavaPathFinder._get_java_version', return_value=('Java 21 fixture', (21, 0, 1)))
        probe.start()
        self.addCleanup(probe.stop)
        for key, value in {'minecraft.directory.enable': str(self.root / 'game'),
                           'minecraft.version.enable': 'fixture', 'java.path': sys.executable,
                           'minecraft.auto_allocate_memory': False, 'memory.allocation': 1024}.items():
            self.settings.set_setting(key, value)
        self.script = self.root / 'fake_game.py'
        self.script.write_text('import sys\nprint("game ready", flush=True)\nsys.stdin.readline()\n')
        self.native_directories = []
        def command(version, directory, options):
            self.native_directories.append(Path(options['nativesDirectory']))
            return [sys.executable, str(self.script)]
        for module in ('core.game_sessions', 'core.launcher'):
            patcher = patch(module + '.get_settings_manager', return_value=self.settings)
            patcher.start()
            self.addCleanup(patcher.stop)
        for name, value in [('core.launcher.verified_installation', True),
                             ('core.launcher.minecraft_launcher_lib.command.get_minecraft_command', None)]:
            patcher = patch(name, return_value=value)
            mocked = patcher.start()
            if value is None:
                mocked.side_effect = command
            self.addCleanup(patcher.stop)
        self.sessions = GameSessions(str(self.root))
        self.sessions.set_options(version='fixture', username='Fixture', uuid=None, token=None)
        self.addCleanup(self.cleanup)

    def wait_for(self, condition):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            self.app.processEvents()
            if condition():
                return
            time.sleep(.01)
        self.fail('session state did not settle')

    def cleanup(self):
        for record in list(self.sessions.sessions):
            process = record['launcher'].process
            if process and process.poll() is None:
                process.terminate()
        self.wait_for(lambda: not self.sessions._sessions)

    def test_default_rejects_second_process_and_multi_open_stops_only_selected(self):
        native_source = self.root / 'game/versions/fixture/natives'
        native_source.mkdir(parents=True, exist_ok=True)
        (native_source / 'fixture.dll').write_bytes(b'native fixture')
        self.assertTrue(self.sessions.start())
        self.wait_for(lambda: self.sessions.running)
        first = self.sessions.selected
        first_process = first['launcher'].process
        self.assertFalse(self.sessions.start())
        self.settings.set_setting('launcher.allow_multiple', True)
        self.assertTrue(self.sessions.start())
        self.wait_for(lambda: len([r for r in self.sessions.sessions if r['phase'] == 'running']) == 2)
        second = self.sessions.selected
        second_process = second['launcher'].process
        self.assertNotEqual(first_process.pid, second_process.pid)
        self.assertNotEqual(*self.native_directories)
        self.assertTrue(all((path / 'fixture.dll').read_bytes() == b'native fixture'
                            for path in self.native_directories))
        self.sessions.selected_id = first['id']
        self.sessions.stop()
        self.wait_for(lambda: first_process.poll() is not None and len(self.sessions.sessions) == 1)
        self.assertIsNone(second_process.poll())
        self.assertTrue(self.sessions.running)
        self.assertEqual(self.sessions.selected_id, second['id'])
        self.assertFalse(self.native_directories[0].exists())
        self.assertTrue(self.native_directories[1].exists())
        self.assertEqual(self.sessions.running_instance, second['instance'])
        self.sessions.stop()
        self.wait_for(lambda: not self.sessions.sessions)
        self.assertFalse(self.sessions.running)

    def test_worker_settings_are_frozen_while_global_selection_changes(self):
        self.assertTrue(self.sessions.start())
        self.wait_for(lambda: self.sessions.running)
        launcher = self.sessions.selected['launcher']
        self.settings.set_setting('minecraft.version.enable', 'other')
        self.settings.set_setting('memory.allocation', 4096)
        self.assertEqual(launcher.settings_manager.get_setting('minecraft.version.enable'), 'fixture')
        self.assertEqual(launcher.settings_manager.get_setting('memory.allocation'), 1024)

    def test_cancelling_java_preparation_never_stops_selected_running_game(self):
        from types import SimpleNamespace
        import threading
        running = SimpleNamespace(_java_cancel=threading.Event())
        preparing = SimpleNamespace(_java_cancel=threading.Event())
        self.sessions._sessions = [dict(id=1, phase='running', launcher=running),
                                   dict(id=2, phase='starting', launcher=preparing)]
        self.sessions.selected_id = 1
        try:
            self.sessions.cancel_preparation()
            self.assertFalse(running._java_cancel.is_set())
            self.assertTrue(preparing._java_cancel.is_set())
            self.assertTrue(self.sessions._sessions[1]['stop_requested'])
        finally:
            self.sessions._sessions = []

    def test_manual_stop_is_not_reported_as_crash_but_unexpected_exit_is(self):
        stopped = QSignalSpy(self.sessions.signals.stopped)
        self.assertTrue(self.sessions.start())
        self.wait_for(lambda: self.sessions.running)
        self.sessions.stop()
        self.wait_for(lambda: not self.sessions._sessions)
        self.assertEqual(stopped.at(0), [0])
        self.assertTrue(self.sessions.start())
        self.wait_for(lambda: self.sessions.running)
        self.sessions.selected['launcher'].process.terminate()
        self.wait_for(lambda: not self.sessions._sessions)
        self.assertNotEqual(stopped.at(1), [0])

    def test_one_home_button_starts_multiple_games_and_menu_stops_only_selected(self):
        from PySide6.QtWidgets import QWidget
        from ui.pages.started_game import StartGamePage
        parent = QWidget()
        parent.config_path = str(self.root)
        with patch('ui.pages.qml_start.get_settings_manager', return_value=self.settings):
            page = StartGamePage(parent, str(Path(__file__).resolve().parents[1] / 'resources'), str(self.root / 'cache'))
        # Reuse the real session manager created by the page for process cleanup.
        self.sessions = page.launcher
        page.auth_manager.current_mode = 'offline'
        page.auth_manager.offline.username = 'Fixture'
        with patch.object(page.auth_manager, 'is_authenticated', return_value=True):
            page.started_game()
            self.wait_for(lambda: page.current_client)
            self.assertEqual(page.controller.view['launchTitle'], '停止游戏')
            self.settings.set_setting('launcher.allow_multiple', True)
            page.on_page_activate()
            self.assertTrue(page.controller.view['allowMultiple'])
            self.assertEqual(page.controller.view['launchTitle'], '启动游戏')
            page.controller.launch(True)
            self.wait_for(lambda: len([r for r in self.sessions.sessions if r['phase'] == 'running']) == 2)
            first, second = self.sessions.sessions
            second_process = second['launcher'].process
            page.controller.selectSession(first['id'])
            page.controller.stopSelected()
            self.wait_for(lambda: len(self.sessions.sessions) == 1)
            self.assertIsNone(second_process.poll())
            self.assertEqual(page.controller.view['launchTitle'], '启动游戏')
            self.settings.set_setting('launcher.allow_multiple', False)
            page.on_page_activate()
            self.assertEqual(page.controller.view['launchTitle'], '停止游戏')
        self.cleanup()
        page.auth_refresh_timer.stop()
        parent.close()
