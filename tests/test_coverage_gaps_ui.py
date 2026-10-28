"""Functional regressions for checklist gaps; no Microsoft login or desktop input.

The command builder supplies a local child instead of Minecraft. Java selection,
launch workers, error dialogs, log actions and retry/session lifecycle stay real.
"""
import json
import sys
from pathlib import Path
from unittest.mock import patch

from _qml_test_support import Qt, qt_mouse_click
from test_client_ui_acceptance import ClientUiAcceptanceCase as _UiCase
import test_home_ui as home_ui
import test_onboarding as onboarding


class CoverageGapsUiTests(_UiCase):
    restart = home_ui.HomeChecklistUiTests.restart
    offline_login = home_ui.HomeChecklistUiTests.offline_login
    prepare_game_process = home_ui.HomeChecklistUiTests.prepare_game_process
    launch_child = home_ui.HomeChecklistUiTests.launch_child
    exit_child = home_ui.HomeChecklistUiTests.exit_child
    step_index = onboarding.OnboardingCoachTests.step_index
    open_tutorial_lobby = onboarding.OnboardingCoachTests.open_tutorial_lobby

    def tearDown(self):
        sessions = self.window.started_page.launcher
        for record in list(sessions.sessions):
            sessions.selected_id = record['id']
            sessions.stop(force=True)
        self.wait_for(lambda: not sessions._sessions, 'all owned launch workers finish before teardown')
        super().tearDown()

    def test_tutorial_completion_survives_new_window_and_settings_manager(self):
        # Existing onboarding tests cover every intermediate control. Replay
        # the final real Continue action, then destroy and rebuild the launcher.
        coach, _backend, dialog, _quick = self.open_tutorial_lobby()
        coach.index = self.step_index('create-next')
        coach.changed.emit()
        coach._prepare_and_refresh()
        self.pause_ui()
        overlay = coach._overlays[dialog]
        overlay.grab()
        self.record('mouseClick', 'tutorial-final-continue')
        qt_mouse_click(dialog, overlay.mapTo(dialog, coach._continue_rect.center().toPoint()))
        self.pause_ui()
        self.check(not coach.visible and not dialog.isVisible(), 'final Continue finishes and closes tutorial')
        previous = self.manager
        self.restart()
        # Wait past the real first-run scheduling delay; a direct call alone
        # would not catch a stale delayed callback reopening the tutorial.
        self.pump(1550)
        self.check(self.manager is not previous and self.manager.get_setting('onboarding.completed'),
                   'new settings manager reads completed marker from disk')
        self.check(not self.window.tutorial_controller.visible and self.window.started_page.isVisible(),
                   'tutorial stays closed after restart and first-run timer')
        self.screenshot_ui('tutorial-completed-after-restart')
        self.assert_no_qml_errors()
        self.finish_test()

    def test_offline_identity_and_version_reach_actual_child_command(self):
        from core.launch_options import offline_uuid
        self.offline_login('Offline_Gaps')
        sessions = self.prepare_game_process()
        script = self.directory / 'identity-child.py'
        receipt = self.output / 'offline-child-arguments.json'
        script.write_text('import json,sys\nfrom pathlib import Path\n'
                          'Path(sys.argv[1]).write_text(sys.argv[2], encoding="utf-8")\n'
                          'print("OFFLINE_IDENTITY_READY", flush=True)\n'
                          'sys.stdin.readline()\n', encoding='utf-8')

        def command(version, directory, options):
            values = {key: options[key] for key in ('username', 'uuid', 'token', 'version')}
            values['selectedVersion'] = version
            values['directory'] = str(directory)
            return [sys.executable, str(script), str(receipt), json.dumps(values)]

        self._patch(patch('core.launcher.minecraft_launcher_lib.command.get_minecraft_command', side_effect=command))
        process = self.launch_child(sessions)
        self.wait_for(receipt.is_file, 'actual child receives and writes command arguments')
        values = json.loads(receipt.read_text(encoding='utf-8'))
        self.check(values == dict(username='Offline_Gaps', uuid=offline_uuid('Offline_Gaps'), token='0',
                                  version='1.21.8', selectedVersion='1.21.8', directory=str(self.game_dir)),
                   'offline name, Java-compatible UUID, offline token and current version reach child')
        self.check(not self.window.started_page.auth_manager.offline.token,
                   'offline role never acquires an online credential')
        self.exit_child(process)
        self.wait_for(lambda: not sessions._sessions, 'offline child exits and worker is reclaimed')
        self.check(process.returncode == 0, 'identity child exits normally')
        self.screenshot_ui('offline-command-after-exit')
        self.assert_no_qml_errors()
        self.finish_test()

    def java_failure_and_retry(self, incompatible):
        self.offline_login()
        sessions = self.window.started_page.launcher
        self.manager.set_setting('java.installations', [])
        bad_path = str(Path(sys.executable) if incompatible else self.directory / 'missing-java.exe')
        self.manager.set_setting('java.path', bad_path)
        self.manager.save_settings()
        # Only runtime probing and remote package catalogue are boundaries.
        # Production select_java must reject the real configured candidate.
        with patch('config.javafinder.JavaPathFinder._get_java_version', return_value=('Java 8 fixture', (1, 8, 0))), \
                patch('core.launcher.java_catalogue', side_effect=ConnectionError('isolated package catalogue unavailable')):
            self.click_ui(self.window.started_page, 'launch-game')
            self.wait_for(lambda: self.window._launch_error_dialog is not None
                          and self.window._launch_error_dialog.isVisible() and not sessions._sessions,
                          'real Java selection rejects unsuitable runtime and releases worker')
        dialog = self.window._launch_error_dialog
        detail = dialog.controller.detail
        self.check('21' in detail and bad_path in detail and '自动安装 Java' in detail,
                   'Java error identifies required version, configured path and auto-install failure')
        self.check(dialog.controller.actions == ['下载 Java', 'Java 设置', '关闭'],
                   'Java failure offers usable download and settings actions')
        self.check(any('自动安装 Java' in line for line in self.window._debug_output),
                   'Java cause is retained in launcher output')
        self.screenshot_ui('java-incompatible' if incompatible else 'java-missing', dialog)
        self.click_ui(dialog, 'dialog-action-1')
        self.check(self.window.settings_page.java_page.isVisible(), 'Java Settings action opens runtime management')
        sessions = self.prepare_game_process()
        self.navigate('launcher-nav-home')
        process = self.launch_child(sessions)
        self.exit_child(process)
        self.wait_for(lambda: not sessions._sessions, 'repaired runtime permits retry through same Home action')
        self.assert_no_qml_errors()
        self.finish_test()

    def test_missing_java_reports_cause_opens_settings_and_allows_retry(self):
        self.java_failure_and_retry(False)

    def test_incompatible_java_reports_cause_opens_settings_and_allows_retry(self):
        self.java_failure_and_retry(True)

    def test_missing_corrupt_version_and_invalid_arguments_have_logs_and_retry(self):
        self.offline_login()
        sessions = self.prepare_game_process()
        metadata = self.game_dir / 'versions/1.21.8/1.21.8.json'
        original = metadata.read_bytes()
        for mode, expected in (('missing', '版本文件缺失'), ('corrupt', '已损坏'), ('arguments', 'No closing quotation')):
            if mode == 'missing':
                metadata.unlink()
            elif mode == 'corrupt':
                metadata.write_text('{broken', encoding='utf-8')
            else:
                self.manager.set_version_setting('game.launch_args', '"unterminated')
            self.click_ui(self.window.started_page, 'launch-game')
            self.wait_for(lambda: self.window._launch_error_dialog is not None
                          and self.window._launch_error_dialog.isVisible() and not sessions._sessions,
                          mode + ' produces an error without a running child')
            dialog = self.window._launch_error_dialog
            self.check(expected in dialog.controller.message, 'visible error retains specific cause: ' + mode)
            if mode != 'arguments':
                self.check(str(metadata) in dialog.controller.message and '修复' in dialog.controller.message,
                           'version error includes exact affected path and recovery instruction')
            self.check(any(expected in row for row in self.window._debug_output), 'launch output retains cause: ' + mode)
            self.click_ui(dialog, 'dialog-action-0')
            self.check(self.window._debug_dialog.isVisible(), 'View log action opens real log window: ' + mode)
            self.screenshot_ui('launch-failure-' + mode, self.window._debug_dialog)
            self.key_ui(self.window._debug_dialog, Qt.Key_Escape, 'close-log')
            metadata.write_bytes(original)
            self.manager.set_version_setting('game.launch_args', '')
            process = self.launch_child(sessions)
            self.exit_child(process)
            self.wait_for(lambda: not sessions._sessions, 'repair permits new launch: ' + mode)
            self.check(process.returncode == 0, 'retry child exits normally: ' + mode)
        self.assert_no_qml_errors()
        self.finish_test()
