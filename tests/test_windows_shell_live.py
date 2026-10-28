"""Actual Windows Explorer and launcher-window acceptance, without shell mocks."""
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QCursor

from test_client_ui_acceptance import ClientUiAcceptanceCase as _UiCase
import test_home_ui as home_ui
import test_settings_ui as settings_ui


@unittest.skipUnless(os.name == 'nt' and os.environ.get('QT_QPA_PLATFORM') == 'windows'
                     and os.environ.get('BUGGCRAFT_DESKTOP_TESTS') == '1',
                     'Set BUGGCRAFT_DESKTOP_TESTS=1 on an isolated Windows desktop')
class WindowsShellUiTests(_UiCase):
    settings_tab = settings_ui.ClientUiSettingsTests.settings_tab
    restart = home_ui.HomeChecklistUiTests.restart

    def explorer_windows(self, path, close=False):
        # Filter within PowerShell; never return unrelated user folder names.
        script = r'''$target = $env:BUGGCRAFT_SHELL_EXPECTED
$rows = @()
foreach ($w in (New-Object -ComObject Shell.Application).Windows()) {
    try {
        if ([IO.Path]::GetFullPath($w.Document.Folder.Self.Path).TrimEnd('\') -ieq $target.TrimEnd('\')) {
            $rows += @{handle=[long]$w.HWND; path=$target}
            if ($env:BUGGCRAFT_SHELL_CLOSE -eq '1') { $w.Quit() }
        }
    } catch {}
}
ConvertTo-Json -InputObject @($rows) -Compress'''
        env = dict(os.environ, BUGGCRAFT_SHELL_EXPECTED=str(Path(path).resolve()),
                   BUGGCRAFT_SHELL_CLOSE='1' if close else '0')
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                                env=env, capture_output=True, text=True, check=True,
                                timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
        return json.loads(result.stdout or '[]')

    def test_instance_and_java_folder_buttons_open_exact_explorer_directory(self):
        paths = []
        self.navigate('instances-button')
        page = self.window.version_page.versions_page
        target = self.game_dir / 'versions/1.21.8'
        self.check(not self.explorer_windows(target), 'temporary instance has no preexisting Explorer window')
        self.addCleanup(self.explorer_windows, target, True)
        self.click_ui(page, 'instance-folder-1.21.8')
        self.wait_for(lambda: self.explorer_windows(target), 'Explorer opens the instance itself, not its parent', timeout=20000)
        paths.extend(self.explorer_windows(target))
        # The fixture runtime has a real executable; directory action does not
        # substitute the OS open operation or validate a runtime version.
        java = self.settings_tab(2)
        target = Path(sys.executable).parent
        existed = self.explorer_windows(target)
        if not existed:
            self.addCleanup(self.explorer_windows, target, True)
        self.click_ui(java, 'java-folder-' + sys.executable)
        self.wait_for(lambda: self.explorer_windows(target), 'Java directory is displayed by actual Explorer', timeout=20000)
        paths.extend(self.explorer_windows(target))
        (self.output / 'explorer-windows.json').write_text(json.dumps(paths, indent=2), encoding='utf-8')
        self.navigate('launcher-nav-home')
        self.check(self.window.isVisible(), 'launcher remains usable after both external actions')
        self.screenshot_ui('external-explorer-return')
        self.assert_no_qml_errors()
        self.finish_test()

    def test_native_minimize_restore_title_drag_close_and_reopen(self):
        user32 = ctypes.windll.user32
        handle = int(self.window.winId())
        self.click_ui(self.window.title_bar, 'minimize-launcher')
        self.wait_for(lambda: bool(user32.IsIconic(handle)), 'native launcher window is minimized')
        user32.ShowWindow(handle, 9)  # Native shell restore action (SW_RESTORE).
        user32.SetForegroundWindow(handle)
        self.wait_for(lambda: not user32.IsIconic(handle) and self.window.isVisible(),
                      'native restore returns launcher with the same content')
        self.pump(400)
        before = self.window.pos()
        point = self.window.title_bar.quick.mapToGlobal(QPoint(12, 12))
        errors = []

        def drag():
            try:
                # Qt supplies logical screen coordinates; SetCursorPos expects
                # physical pixels on scaled desktops. Let Qt apply the scale.
                QCursor.setPos(point)
                user32.mouse_event(0x0002, 0, 0, 0, 0)
                time.sleep(.15)
                for step in range(1, 9):
                    QCursor.setPos(point + QPoint(step * 5, step * 3))
                    time.sleep(.035)
            except Exception as exc:
                errors.append(str(exc))
            finally:
                user32.mouse_event(0x0004, 0, 0, 0, 0)

        worker = threading.Thread(target=drag, daemon=True)
        worker.start()
        self.wait_for(lambda: not worker.is_alive(), 'native mouse drag finishes')
        self.check(not errors and self.window.pos() != before,
                   'dragging the real title bar changes actual window position')
        self.screenshot_ui('native-title-drag')
        self.click_ui(self.window.title_bar, 'close-launcher')
        self.wait_for(lambda: not self.window.isVisible(), 'close button closes the real launcher window')
        self.restart()
        self.check(self.window.isVisible(), 'reopening creates an operational launcher window')
        self.navigate('launcher-nav-settings')
        self.screenshot_ui('native-reopened-launcher')
        self.assert_no_qml_errors()
        self.finish_test()
