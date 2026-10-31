"""Concise memory guidance uses the real launcher dialogs and Qt input."""
from threading import Event
from unittest.mock import patch

from test_client_ui_acceptance import ClientUiAcceptanceCase as _MemoryCase


class MemoryWarningUiTests(_MemoryCase):
    def test_runtime_warning_is_nonmodal_reusable_and_can_be_dismissed(self):
        home = self.window.started_page
        message = '电脑内存快用满了，游戏可能卡顿或退出。先关闭其他程序。'
        with patch('windows.main_window.QSystemTrayIcon.isSystemTrayAvailable', return_value=False):
            home.launcher.memory_pressure.emit(message)
            self.pause_ui()
            dialog = self.window._memory_dialog
            self.check(dialog.isVisible() and not dialog.isModal(), 'warning remains nonmodal')
            self.check(dialog.controller.detail == message, 'short actionable warning is shown')
            self.screenshot_ui('memory-runtime-warning', dialog)
            self.click_ui(dialog, 'dialog-action-0')
            self.check(not dialog.isVisible(), 'the user dismisses the warning')
            home.launcher.memory_pressure.emit(message)
            self.pause_ui()
            self.check(self.window._memory_dialog is dialog and dialog.isVisible(), 'a later warning reuses the dialog')
            self.click_ui(dialog, 'dialog-action-0')
        self.assert_no_qml_errors()
        self.finish_test()

    def test_preflight_return_opens_memory_settings_without_starting_game(self):
        request = dict(event=Event(), accepted=False)
        self.window.minecraft_preflight_confirmation('200 个模组，建议至少 6 GB。电脑可用内存不足。', request)
        self.pause_ui()
        dialog = self.window._preflight_dialog
        self.screenshot_ui('memory-preflight-warning', dialog)
        self.click_ui(dialog, 'dialog-action-0')
        self.check(request['event'].is_set() and not request['accepted'], 'return cancels this launch request')
        self.check(self.window.content_stack.currentWidget() is self.window.settings_page, 'return opens settings')
        self.check(not self.window.started_page.launcher.sessions, 'return starts no game process')
        self.assert_no_qml_errors()
        self.finish_test()
