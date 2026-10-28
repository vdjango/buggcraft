"""Shared launcher branches, exercised through shipping QML and real effects.

Remote social payloads are deterministic. Sound on Windows uses the production
PlaySound call; this verifies dispatch and WAV validity, not speaker hardware.
Microsoft authentication is deliberately outside this suite.
"""
import json
import os
from pathlib import Path
import wave
from unittest.mock import patch

from PySide6.QtCore import QPoint, Qt

from _qml_test_support import QTest, qt_mouse_click, qt_mouse_move
from test_client_ui_acceptance import ClientUiAcceptanceCase as _UiCase
import test_home_ui as home_ui
import test_settings_ui as settings_ui


class SharedBranchesUiTests(_UiCase):
    settings_tab = settings_ui.ClientUiSettingsTests.settings_tab
    scroll_control = settings_ui.ClientUiSettingsTests.scroll_control
    setting_click = settings_ui.ClientUiSettingsTests.setting_click
    choose_box = settings_ui.ClientUiSettingsTests.choose_box
    select_choice = settings_ui.ClientUiSettingsTests.select_choice
    persisted = settings_ui.ClientUiSettingsTests.persisted
    offline_login = home_ui.HomeChecklistUiTests.offline_login
    prepare_game_process = home_ui.HomeChecklistUiTests.prepare_game_process
    launch_child = home_ui.HomeChecklistUiTests.launch_child
    exit_child = home_ui.HomeChecklistUiTests.exit_child

    def test_instance_destructive_and_export_dialog_dismissals_preserve_files(self):
        self.navigate('instances-button')
        page = self.window.version_page.versions_page
        marker = self.game_dir / 'versions/1.21.8/cancel-must-preserve.txt'
        marker.write_text('owned temporary instance', encoding='utf-8')
        for target, attribute, cancel in (
                ('instance-delete-1.21.8', '_delete_dialog', 0),
                ('instance-remove-directory-' + str(self.game_dir), '_delete_dialog', 0),
                ('instance-export-1.21.8', '_export_dialog', 2)):
            for action in ('cancel', 'escape', 'window-close'):
                self.click_ui(page, target)
                dialog = getattr(page.controller, attribute)
                before = json.loads((self.manager.config_path / 'settings.json').read_text(encoding='utf-8'))
                qt_mouse_click(self.window.title_bar.quick, QPoint(3, 3))
                self.pause_ui()
                self.check(dialog.isVisible() and marker.is_file(),
                           'outside click cannot authorize deletion/export: ' + target)
                if action == 'cancel':
                    self.click_ui(dialog, 'dialog-action-' + str(cancel))
                elif action == 'escape':
                    self.key_ui(dialog, Qt.Key_Escape, 'dismiss-instance-confirmation')
                else:
                    self.record('nativeClose', target, 'OS window close request')
                    dialog.close()
                self.wait_for(lambda: getattr(page.controller, attribute) is None,
                              'dismissed confirmation releases its dialog reference')
                self.check(marker.read_text(encoding='utf-8') == 'owned temporary instance'
                           and before == json.loads((self.manager.config_path / 'settings.json').read_text(encoding='utf-8')),
                           'cancel/escape/window-close preserve actual files and configuration: ' + target)
        self.screenshot_ui('shared-instance-dialog-dismissals')
        self.assert_no_qml_errors()
        self.finish_test()

    def test_every_setting_radio_and_disabled_cache_has_correct_disk_result(self):
        for tab in (0, 1):
            page = self.settings_tab(tab)
            groups = [dict(g) for g in page.controller.groups
                      if g['kind'] in ('radio', 'radio-horizontal') and
                      g['key'] != 'java.path']
            for group in groups:
                key = group['key']
                for index, option in enumerate(group['options']):
                    saved = self.persisted()
                    getter = saved.get_setting if tab == 0 else saved.get_version_setting
                    before = getter(key)
                    option_name = ('launcher-update-channel-' + str(option['value'])
                                   if key == 'settings.general.update' else
                                   'setting-option-' + key + '-' + str(index))
                    self.check(self.item(page, option_name) is not None,
                               'every enumerated setting has an actionable control: ' + option_name)
                    self.setting_click(page, option_name)
                    saved = self.persisted()
                    getter = saved.get_setting if tab == 0 else saved.get_version_setting
                    if group.get('enabled', True):
                        self.check(getter(key) == option['value'], 'radio commits its exact value to disk: ' + key)
                    else:
                        self.check(getter(key) == before, 'disabled cache choice cannot pretend to migrate configuration')
        self.screenshot_ui('shared-radio-disk-results')
        self.assert_no_qml_errors()
        self.finish_test()

    def test_quick_action_setting_controls_clipboard_join_and_lan_creation(self):
        from PySide6.QtWidgets import QApplication
        from hookup.profiles import RoomInvite
        home = self.window.started_page
        dialog = home._ensure_multiplayer_dialog()
        backend = dialog.backend
        clipboard = QApplication.clipboard()
        previous = clipboard.text()
        self.addCleanup(clipboard.setText, previous)
        backend.node_path = 'fixture-node'
        backend.patch(nodeAvailable=True, instanceLoading=False, busy=False, page='hall')
        for index, mode in enumerate(('关闭', '首页提示', '自动创建或加入')):
            clipboard.clear()
            backend.patch(openWorldPrompt=False)
            dialog.hide()
            general = self.settings_tab(0)
            self.setting_click(general, 'setting-option-multiplayer.quick_action-' + str(index))
            self.check(self.persisted().get_setting('multiplayer.quick_action') == mode,
                       'quick-action preference is saved through its actual radio button')
            self.navigate('launcher-nav-home')
            backend.pending = None
            backend.patch(page='hall', nodeAvailable=True, busy=False, connections=[],
                          openWorldPrompt=False, openWorldPort=0)
            invite = RoomInvite.create().encode()
            with patch.object(backend, 'profile', return_value=object()), \
                    patch.object(backend, 'continue_join') as continue_join:
                clipboard.setText(invite)
                self.pause_ui()
                if index == 0:
                    self.check(not home.controller.view['multiplayerAttention'] and not continue_join.called,
                               'disabled shortcut ignores a clipboard invite')
                    self.click_ui(home, 'open-lobby-home')
                    self.check(dialog.isVisible() and not continue_join.called,
                               'manual lobby remains available without silently joining')
                elif index == 1:
                    self.check(home.controller.view['multiplayerAttention'] and not continue_join.called,
                               'prompt mode advertises the invite and waits for explicit action')
                    self.click_ui(home, 'open-lobby-home')
                    continue_join.assert_called_once_with()
                    self.check(backend.pending == ('fixture-node', RoomInvite.decode(invite))
                               and backend._state['page'] == 'join',
                               'manual action validates invite and stages the selected room')
                else:
                    self.wait_for(lambda: continue_join.called,
                                  'automatic mode validates and stages the clipboard invitation')
                    continue_join.assert_called_once_with()
                    self.check(backend.pending == ('fixture-node', RoomInvite.decode(invite))
                               and backend._state['page'] == 'join',
                               'automatic action preserves the decoded room for connection')
                dialog.hide()
            clipboard.clear()
            backend.game = {'version': '1.21.8'}
            with patch.object(backend, 'probe') as probe, patch.object(backend, 'profile', return_value=object()):
                backend.patch(openWorldPrompt=True, openWorldPort=51234, openWorldMode='create')
                self.pause_ui()
                if index == 0:
                    self.check(not probe.called and not home.controller.view['multiplayerAttention'],
                               'disabled shortcut does not create a detected LAN world')
                elif index == 1:
                    self.check(not probe.called and home.controller.view['multiplayerAttention'],
                               'prompt mode waits before creating the detected LAN world')
                    self.click_ui(home, 'open-lobby-home')
                    self.check(not probe.called and backend._state['page'] == 'create'
                               and backend._state.get('pendingOpenWorldPort') == 51234,
                               'prompt action opens creation with the detected LAN port')
                else:
                    self.wait_for(lambda: probe.called, 'automatic LAN creation starts the production probe action')
                    probe.assert_called_once()
                    request = probe.call_args.args[0]
                    self.check(request.get('port') == 51234 and request.get('automatic') is True,
                               'automatic LAN action probes the detected port with production flags')
                    self.check(backend.quick_creation_data[1]['port'] == 51234,
                               'detected LAN port reaches the production creation workflow')
        self.screenshot_ui('shared-quick-action-workflow')
        self.assert_no_qml_errors()
        self.finish_test()

    def tearDown(self):
        sessions = self.window.started_page.launcher
        for record in list(sessions.sessions):
            sessions.selected_id = record['id']
            sessions.stop(force=True)
        self.wait_for(lambda: not sessions._sessions, 'all owned processes exit')
        super().tearDown()

    def test_settings_choices_escape_and_outside_never_commit_highlight(self):
        exercised = []
        for tab in (0, 1):
            page = self.settings_tab(tab)
            fields = [dict(field) for field in page.controller.groups
                      if field['kind'] == 'choice' and field.get('enabled', True)]
            for field in fields:
                key = field['key']
                name = 'setting-select-' + ('game-language' if key == 'game.language' else key)
                getter = self.manager.get_setting if tab == 0 else self.manager.get_version_setting
                disk_getter = lambda: (self.persisted().get_setting(key) if tab == 0
                                       else self.persisted().get_version_setting(key))
                before, disk_before = getter(key), disk_getter()
                count = len(field['options'])
                original = next((i for i, option in enumerate(field['options'])
                                 if option['value'] == field['value']), 0)
                alternative = (original + 1) % count
                self.choose_box(page, name, alternative, commit=False)
                self.check(getter(key) == before and disk_getter() == disk_before,
                           'Escape discards highlighted choice in memory and on disk: ' + key)
                self.setting_click(page, name)
                qt_mouse_move(page.quick, QPoint(3, 3))
                self.key_ui(page, Qt.Key_Home, key + '-outside-first')
                self.key_ui(page, Qt.Key_Down, key + '-outside-highlight')
                qt_mouse_click(page.quick, QPoint(3, 3))
                self.pause_ui()
                self.check(not self.item(page, name).property('tutorialPopupVisible'),
                           'outside click dismisses the choice popup: ' + key)
                self.check(getter(key) == before and disk_getter() == disk_before,
                           'outside click never commits a highlighted value: ' + key)
                exercised.append(key)
        self.check(set(exercised) >= {'settings.general.mirrors', 'settings.general.content_mirror',
                                     'game.language',
                                     'launcher.visibility', 'launcher.window_size'},
                   'all general/global non-inline choices are included')
        self.screenshot_ui('shared-choice-cancellation')
        self.assert_no_qml_errors()
        self.finish_test()

    def test_disabled_auto_memory_and_inherited_instance_controls_cannot_write(self):
        page = self.settings_tab(1)
        before = self.manager.get_version_setting('memory.allocation')
        slider = self.scroll_control(page, 'setting-memory-slider')
        self.check(not slider.isEnabled(), 'automatic allocation disables manual slider')
        self.click_ui(page, 'setting-memory-slider')
        for key in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Home, Qt.Key_End):
            self.key_ui(page, key, 'disabled-memory-key')
        self.check(self.manager.get_version_setting('memory.allocation') == before
                   and self.persisted().get_version_setting('memory.allocation') == before,
                   'clicks and keys cannot overwrite automatically selected memory')
        self.click_ui(self.window.title_bar, 'instances-button')
        instances = self.window.version_page.versions_page
        self.click_ui(instances, 'instance-settings-1.21.8')
        page = self.window.version_page.stack.currentWidget()
        page.ensure_loaded()
        self.pause_ui()
        groups = [dict(g) for g in page.controller.groups if g.get('key') != 'instance.enable']
        self.check(groups and all(not g.get('enabled', True) for g in groups),
                   'an inheriting instance exposes disabled override fields')
        before_global = json.loads((self.manager.config_path / 'settings.json').read_text(encoding='utf-8'))
        self.setting_click(page, 'setting-option-minecraft.isolation-0')
        self.setting_click(page, 'setting-select-launcher.visibility')
        self.check(not self.item(page, 'setting-select-launcher.visibility').property('tutorialPopupVisible'),
                   'disabled instance choice cannot open or choose an override')
        after_global = json.loads((self.manager.config_path / 'settings.json').read_text(encoding='utf-8'))
        self.check(after_global == before_global, 'disabled instance controls cannot mutate saved configuration')
        self.screenshot_ui('shared-disabled-instance')
        self.assert_no_qml_errors()
        self.finish_test()

    def test_missing_role_and_version_block_launch_until_remedied(self):
        home = self.window.started_page
        sessions = self.prepare_game_process()
        errors = []
        sessions.signals.error.connect(errors.append)
        self.click_ui(home, 'launch-game')
        self.check(not sessions._sessions and not errors
                   and self.item(home, 'home-launch-title').property('text') == '请先设置角色',
                   'unauthenticated launch explains missing role without creating a process')
        self.offline_login('Guard_Player', enter=True)
        self.manager.set_setting('minecraft.version.enable', '')
        home.set_minecraft_version('')
        self.click_ui(home, 'launch-game')
        self.check(self.window.current_tab == 3 and not sessions._sessions,
                   'missing version routes to Instances without starting a worker')
        instances = self.window.version_page.versions_page
        self.click_ui(instances, 'instance-row-1.21.8')
        self.navigate('launcher-nav-home')
        process = self.launch_child(sessions)
        self.check(process.poll() is None and home.auth_manager.offline.username == 'Guard_Player',
                   'choosing a version after offline login launches the intended real child process')
        self.exit_child(process)
        self.wait_for(lambda: not sessions._sessions, 'remedied launch exits normally')
        self.check(not errors, 'remedied launch produces no launch error')
        self.screenshot_ui('shared-launch-remedied')
        self.assert_no_qml_errors()
        self.finish_test()

    def test_notification_sound_switch_preserves_all_three_unread_events(self):
        if os.name != 'nt':
            self.skipTest('Production Windows PlaySound dispatch requires Windows')
        import winsound
        home = self.window.started_page
        dialog = home._ensure_multiplayer_dialog()
        backend = dialog.backend
        state = dict(account='a' * 32 + '.' + 'b' * 32, username='Shared_Player',
                     friends=[], requests=[], invitations=[], joinRequests=[],
                     capabilities=dict(room_presence=True, join_requests=True, friend_code=True))
        backend.apply_social_state(state)
        received = []
        backend.social_notification.connect(received.append)
        sound_calls = []
        real_play = winsound.PlaySound

        def play(path, flags):
            with wave.open(str(path), 'rb') as wav:
                self.check(wav.getnframes() > 0 and wav.getframerate() > 0,
                           'notification dispatch references a nonempty decodable WAV')
            sound_calls.append(Path(path).name)
            return real_play(path, flags)

        with patch('winsound.PlaySound', side_effect=play):
            for enabled in (False, True):
                general = self.settings_tab(0)
                toggle = 'setting-toggle-multiplayer.notification_sound'
                if bool(self.item(general, toggle).property('checked')) != enabled:
                    self.setting_click(general, toggle)
                self.check(self.persisted().get_setting('multiplayer.notification_sound') == enabled,
                           'sound preference persists before receiving events')
                for index, (kind, priority) in enumerate((('requests', 'request'),
                                                          ('invitations', 'invite'),
                                                          ('joinRequests', 'invite'))):
                    identity = ('1' if enabled else '2') + str(index) + '0' * 30
                    item = dict(id=identity, account='c' * 32 + '.' + 'd' * 32,
                                username='Incoming_Player', incoming=True,
                                room='e' * 32, status='pending')
                    next_state = dict(state, **{kind: [item]})
                    dialog.backend.seen_friend_invitations.add(identity)
                    dialog.social_sound.last_at = float('-inf')
                    before_calls, before_events = len(sound_calls), len(received)
                    backend.apply_social_state(next_state)
                    self.pause_ui()
                    self.check(received[before_events:] == [priority], 'new social event emits once: ' + kind)
                    self.check(len(sound_calls) - before_calls == int(enabled),
                               'notification setting controls actual OS sound dispatch: ' + kind)
                    view = home.controller.view['friendNotifications']
                    counter = {'requests': 'requests', 'invitations': 'invitations',
                               'joinRequests': 'joinRequests'}[kind]
                    self.check(view[counter] == 1 and view['homeAttention'],
                               'muting sound never suppresses the unread marker: ' + kind)
                    backend.apply_social_state(next_state)
                    self.check(len(received) == before_events + 1
                               and len(sound_calls) == before_calls + int(enabled),
                               'repeated polling does not replay notification or sound: ' + kind)
                    backend.apply_social_state(state)
        (self.output / 'sound-dispatch.json').write_text(json.dumps(sound_calls, indent=2), encoding='utf-8')
        self.navigate('launcher-nav-home')
        self.screenshot_ui('shared-social-notification')
        self.assert_no_qml_errors()
        self.finish_test()
