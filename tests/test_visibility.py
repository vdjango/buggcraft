"""Visibility choices map to explicit window actions and restoration."""
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / 'buggcraft'))
from core.visibility import LauncherVisibilityManager, VisibilitySettings


class FakeWindow:
    def __init__(self):
        self.rect = (1, 2, 800, 600)
        self.maximized = False
        self.minimized = False
        self.visible = True
        self.closed = False
        self.active = False

    def geometry(self): return self.rect
    def isMaximized(self): return self.maximized
    def isMinimized(self): return self.minimized
    def showMinimized(self): self.minimized, self.visible = True, True
    def hide(self): self.visible = False
    def show(self): self.visible, self.minimized = True, False
    def showMaximized(self): self.maximized, self.visible = True, True
    def showNormal(self): self.maximized, self.minimized, self.visible = False, False, True
    def setGeometry(self, geometry): self.rect = geometry
    def activateWindow(self): self.active = True
    def raise_(self): self.active = True
    def close(self): self.closed = True


class VisibilityTests(unittest.TestCase):
    def test_hidden_launcher_restores_the_previous_geometry(self):
        window = FakeWindow()
        manager = LauncherVisibilityManager(window)
        manager.apply_setting(VisibilitySettings.HIDE)
        self.assertFalse(window.visible)
        window.rect = (50, 50, 400, 300)
        manager.restore_if_needed()
        self.assertTrue(window.visible)
        self.assertEqual(window.rect, (1, 2, 800, 600))
        self.assertTrue(window.active)

    def test_minimized_launcher_returns_to_normal_after_game_exit(self):
        window = FakeWindow()
        manager = LauncherVisibilityManager(window)
        manager.apply_setting(VisibilitySettings.MINIMIZE)
        self.assertTrue(window.minimized)
        manager.restore_if_needed()
        self.assertTrue(window.visible)
        self.assertFalse(window.minimized)

    def test_legacy_close_value_uses_deferred_close_choice(self):
        window = FakeWindow()
        manager = LauncherVisibilityManager(window)
        manager.apply_setting(VisibilitySettings.LEGACY_CLOSE)
        self.assertEqual(manager.current_setting, VisibilitySettings.CLOSE)
        self.assertTrue(window.closed)

    def test_close_while_game_runs_hides_launcher_and_preserves_the_managed_process(self):
        from windows.main_window import MinecraftLauncher

        class RunningThread:
            def isRunning(self): return True

        class Event:
            ignored = False
            def ignore(self): self.ignored = True

        class Hideable:
            visible = True
            def hide(self): self.visible = False

        window = Hideable()
        window.launcher = SimpleNamespace(running=True, start_thread=RunningThread())
        window.started_page = SimpleNamespace(_multiplayer_dialog=Hideable())
        window._debug_dialog = Hideable()
        window._close_after_game = False
        window._closing = False
        event = Event()

        MinecraftLauncher.closeEvent(window, event)

        self.assertTrue(event.ignored)
        self.assertTrue(window._close_after_game)
        self.assertFalse(window.visible)
        self.assertFalse(window.started_page._multiplayer_dialog.visible)
        self.assertFalse(window._debug_dialog.visible)
        self.assertTrue(window.launcher.running)
        self.assertFalse(window._closing)


if __name__ == '__main__':
    unittest.main(verbosity=2)
