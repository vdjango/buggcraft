"""Render every production page with nonempty data and exercise QML actions."""
import json
import threading
from unittest.mock import Mock, patch

from _qml_test_support import LauncherQmlCase, QQuickWidget, QTest, Qt, qt_mouse_click
from PySide6.QtWidgets import QAbstractButton, QLineEdit, QPlainTextEdit


class AllLauncherPagesTests(LauncherQmlCase):
    def test_enabling_notification_sound_can_preview_a_chime(self):
        from utils.social_sound import SocialSound
        controller = self.window.settings_page.general_page.controller
        controller.setValue('multiplayer.notification_sound', False)
        with patch.object(SocialSound, 'play', return_value=True) as chime:
            self.assertFalse(controller.previewNotificationSound())
            controller.setValue('multiplayer.notification_sound', True)
            self.assertTrue(controller.previewNotificationSound())
            self.assertEqual([call.args[0] for call in chime.call_args_list], ['request', 'request'])

    def test_sound_setting_immediately_controls_friend_and_room_notifications(self):
        from ui.multiplayer_controller import MultiplayerController
        from utils.social_sound import SocialSound
        page = self.window.started_page
        with patch('ui.multiplayer_controller.TunnelService', return_value=Mock(endpoints={})), \
                patch.object(MultiplayerController, 'job', side_effect=lambda key, task: task.close()), \
                patch.object(SocialSound, 'play') as chime, \
                patch('ui.dialog.MultiplayerDialog.QApplication.alert'):
            dialog = page._ensure_multiplayer_dialog()
            controller = self.window.settings_page.general_page.controller
            for enabled in (False, True, False):
                with self.subTest(enabled=enabled):
                    controller.setValue('multiplayer.notification_sound', enabled)
                    self.assertEqual(self.manager.get_setting('multiplayer.notification_sound'), enabled)
                    chime.reset_mock()
                    dialog.notify_social('request')
                    dialog.notify_social('invite')
                    self.assertEqual([call.args[0] for call in chime.call_args_list],
                                     ['request', 'invite'] if enabled else [])
            dialog.close()
            controller.setValue('multiplayer.notification_sound', True)
            chime.reset_mock()
            dialog.notify_social('invite')
            chime.assert_called_once_with('invite')
            self.assertFalse(dialog.isVisible())
            self.assertFalse(dialog.backend.closed)

    def test_home_friend_notifications_propagate_and_read_only_opened_tab(self):
        from ui.multiplayer_controller import MultiplayerController
        from PySide6.QtWidgets import QApplication
        from utils.social_sound import SocialSound
        page = self.window.started_page
        with patch('ui.multiplayer_controller.TunnelService', return_value=Mock(endpoints={})), \
                patch.object(MultiplayerController, 'job', side_effect=lambda key, task: task.close()), \
                patch.object(SocialSound, 'play') as chime:
            dialog = page._ensure_multiplayer_dialog()
            backend = dialog.backend
            state = dict(account='a' * 32 + '.' + 'b' * 32, username='local_user', friends=[],
                         requests=[dict(id='1' * 32, account='c' * 32 + '.' + 'd' * 32, username='Alice', incoming=True)],
                         invitations=[])
            backend.apply_social_state(state)
            self.pump()
            self.assertEqual(page.controller.view['friendNotifications']['total'], 1)
            self.assertTrue(page.controller.view['friendNotifications']['homeAttention'])
            self.assertTrue(self.item(page, 'home-friends-glow').property('active'))
            self.assertEqual(self.item(page, 'home-friends-badge').property('count'), 1)
            self.click(page, 'open-friends-home')
            self.pump()
            self.assertFalse(page.controller.view['friendNotifications']['homeAttention'])
            self.assertEqual(page.controller.view['friendNotifications']['requests'], 1)
            friends = dialog.friends_window
            from tests.test_lobby_layout import find_item
            from PySide6.QtCore import QPointF
            tab = find_item(friends.quick, 'friends-tab-1')
            point = tab.mapToScene(QPointF(tab.width()/2, tab.height()/2)).toPoint()
            qt_mouse_click(friends.quick, point)
            self.pump()
            self.assertEqual(page.controller.view['friendNotifications']['requests'], 0)
            self.assertFalse(find_item(friends.quick, 'friends-tab-1').property('attention'))
            backend.apply_social_state(state)
            self.assertEqual(chime.call_count, 1)
            self.manager.set_setting('multiplayer.notification_sound', False)
            backend.apply_social_state(dict(state, requests=[dict(state['requests'][0], id='2' * 32)]))
            self.assertEqual(chime.call_count, 1)

    def test_quick_multiplayer_can_be_disabled_without_blocking_manual_hall(self):
        from ui.multiplayer_controller import MultiplayerController
        from hookup.profiles import RoomInvite
        from PySide6.QtWidgets import QApplication
        page = self.window.started_page
        clipboard = QApplication.clipboard()
        self.addCleanup(clipboard.clear)
        with patch('ui.multiplayer_controller.TunnelService', return_value=Mock(endpoints={})), \
                patch.object(MultiplayerController, 'job', side_effect=lambda key, coroutine: coroutine.close()):
            dialog = page._ensure_multiplayer_dialog()
            backend = dialog.backend
            backend.patch(openWorldPrompt=True, openWorldPort=25565)
            self.window.settings_page.general_page.controller.setValue('multiplayer.quick_action', '关闭')
            clipboard.setText(RoomInvite.create().encode())
            self.pump()
            self.assertEqual(self.manager.get_setting('multiplayer.quick_action'), '关闭')
            self.assertEqual(page.controller.view['multiplayerTitle'], '联机')
            self.assertFalse(page.controller.view['multiplayerAttention'])
            self.assertFalse(backend.view['openWorldPrompt'])
            with patch.object(backend, 'act') as act, patch.object(backend, 'join') as join:
                self.click(page, 'open-lobby-home')
                self.assertTrue(dialog.isVisible())
                join.assert_not_called()
                self.assertFalse(any(c.args[0] in ('quickCreate', 'createFromOpenWorld') for c in act.call_args_list))

    def test_home_offers_clipboard_join_and_hidden_world_guidance_with_optional_automation(self):
        from ui.multiplayer_controller import MultiplayerController
        from hookup.profiles import RoomInvite
        from PySide6.QtWidgets import QApplication
        page = self.window.started_page
        invite = RoomInvite.create().encode()
        with patch('ui.multiplayer_controller.TunnelService', return_value=Mock(endpoints={})), \
                patch.object(MultiplayerController, 'job', side_effect=lambda key, coroutine: coroutine.close()):
            dialog = page._ensure_multiplayer_dialog()
            backend = dialog.backend
            backend.node_path = 'fixture-node'
            backend.patch(nodeAvailable=True, instanceLoading=False, page='hall')
            QApplication.clipboard().setText(invite)
            self.pump()
            self.assertEqual(page.controller.view['multiplayerTitle'], '加入房间')
            self.assertTrue(page.controller.view['multiplayerAttention'])
            self.assertFalse(dialog.isVisible())
            with patch.object(backend, 'join') as join:
                self.click(page, 'open-lobby-home')
                join.assert_called_once_with(invite, room_id=None)
                self.assertEqual(page.controller.view['multiplayerTitle'], '联机')
                self.assertFalse(page.controller.view['multiplayerAttention'])
                dialog.hide()
                dialog.show()
                self.pump()
                join.assert_called_once()
            dialog.hide()
            QApplication.clipboard().clear()
            with patch.object(backend, 'act') as act:
                backend.patch(openWorldPrompt=True, openWorldPort=51234, openWorldMode='create')
                self.pump()
                self.assertEqual(page.controller.view['multiplayerTitle'], '创建房间')
                self.assertFalse(dialog.isVisible())
                act.assert_not_called()
                self.window.settings_page.general_page.controller.setValue('multiplayer.quick_action', '自动创建或加入')
                self.pump()
                act.assert_any_call('quickCreate', {'port':51234, 'title':backend.default_room_title(), 'automatic':True})
                self.assertTrue(dialog.isVisible())
            backend.patch(openWorldPrompt=False)
        QApplication.clipboard().clear()
        self.assert_no_qml_errors()

    def test_automatic_world_creation_waits_for_node_then_shows_result_window(self):
        from ui.multiplayer_controller import MultiplayerController
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().clear()
        page = self.window.started_page
        self.manager.set_setting('multiplayer.quick_action', '自动创建或加入')
        with patch('ui.multiplayer_controller.TunnelService', return_value=Mock(endpoints={})), \
                patch.object(MultiplayerController, 'job', side_effect=lambda key, coroutine: coroutine.close()):
            dialog = page._ensure_multiplayer_dialog()
            backend = dialog.backend
            backend.node_path = 'fixture-node'
            backend.game = {'version': '1.21.8'}
            backend.patch(nodeAvailable=False, instanceLoading=False, page='hall',
                          openWorldPrompt=True, openWorldPort=25565, openWorldMode='create')
            with patch.object(backend, 'profile', return_value=Mock()), patch.object(backend, 'probe') as probe:
                self.pump()
                probe.assert_not_called()
                self.assertFalse(dialog.isVisible())
                self.assertTrue(page.controller.view['multiplayerAttention'])
                backend.patch(nodeAvailable=True)
                self.pump()
                probe.assert_called_once_with({'port':25565, 'title':backend.default_room_title(), 'automatic':True})
                self.assertTrue(dialog.isVisible())
                self.assertFalse(page.controller.view['multiplayerAttention'])
                self.assertEqual(page.controller.view['multiplayerTitle'], '联机')
                backend.patch(error='创建失败，请重试。')
                self.pump()
                probe.assert_called_once()
                self.assertTrue(dialog.isVisible())

    def test_home_consumes_hints_and_only_new_invites_or_worlds_prompt_again(self):
        from ui.multiplayer_controller import MultiplayerController
        from hookup.profiles import RoomInvite
        from PySide6.QtWidgets import QApplication
        page = self.window.started_page
        clipboard = QApplication.clipboard()
        self.addCleanup(clipboard.clear)
        first, second = RoomInvite.create().encode(), RoomInvite.create().encode()
        with patch('ui.multiplayer_controller.TunnelService', return_value=Mock(endpoints={})), \
                patch.object(MultiplayerController, 'job', side_effect=lambda key, coroutine: coroutine.close()):
            dialog = page._ensure_multiplayer_dialog()
            backend = dialog.backend
            backend.node_path = 'fixture-node'
            backend.patch(nodeAvailable=True, instanceLoading=False, page='hall')
            clipboard.setText(first)
            self.pump()
            self.assertTrue(page.controller.view['multiplayerAttention'])
            with patch.object(backend, 'join') as join:
                self.click(page, 'open-lobby-home')
                dialog.hide()
                backend.patch(error='连接失败，请手动重试。')
                self.pump()
                self.assertFalse(page.controller.view['multiplayerAttention'])
                clipboard.clear()
                clipboard.setText('  ' + first + '\n')
                self.pump()
                self.assertFalse(page.controller.view['multiplayerAttention'])
                self.click(page, 'open-lobby-home')
                dialog.hide()
                join.assert_called_once_with(first, room_id=None)

                clipboard.setText(second)
                self.pump()
                self.assertEqual(page.controller.view['multiplayerTitle'], '加入房间')
                self.click(page, 'open-lobby-home')
                dialog.hide()
                self.assertEqual(join.call_count, 2)
                self.assertFalse(page.controller.view['multiplayerAttention'])

            clipboard.clear()
            key = 'auto-lan:' + backend.generation
            world = dict(port=51234, version='1.21.8')
            backend.finish(key, [world], None)
            self.pump()
            self.assertEqual(page.controller.view['multiplayerTitle'], '创建房间')
            glow = self.item(page, 'home-multiplayer-glow')
            self.assertTrue(glow.property('active'))
            backend.patch(openWorldMode='associate')
            self.pump()
            self.assertEqual(page.controller.view['multiplayerTitle'], '开放房间')
            backend.patch(openWorldMode='create')
            self.click(page, 'open-lobby-home')
            dialog.hide()
            backend.navigate('hall')
            backend.finish('auto-lan:' + backend.generation, [world], None)
            self.pump()
            self.assertFalse(page.controller.view['multiplayerAttention'])
            self.assertFalse(glow.property('active'))
            self.assertEqual(page.controller.view['multiplayerTitle'], '联机')
            backend.finish('auto-lan:' + backend.generation, [dict(world, port=51235)], None)
            self.pump()
            self.assertTrue(page.controller.view['multiplayerAttention'])
            backend.act('dismissOpenWorld', {})
            backend.patch(connections=[dict(id='active')])
            self.pump()
            self.assertEqual(page.controller.view['multiplayerTitle'], '联机')
        self.assertEqual(dialog.windowTitle(), 'BUGG·联机大厅')
        self.assertFalse(dialog.windowIcon().isNull())
        self.assertEqual(self.window.windowTitle(), 'BUGG启动器')
        self.assertFalse(self.window.windowIcon().isNull())
        self.assert_no_qml_errors()

    def test_automatic_join_consumes_hint_even_when_node_is_not_ready(self):
        from ui.multiplayer_controller import MultiplayerController
        from hookup.profiles import RoomInvite
        from PySide6.QtWidgets import QApplication
        page = self.window.started_page
        clipboard = QApplication.clipboard()
        self.addCleanup(clipboard.clear)
        self.manager.set_setting('multiplayer.quick_action', '自动创建或加入')
        with patch('ui.multiplayer_controller.TunnelService', return_value=Mock(endpoints={})), \
                patch.object(MultiplayerController, 'job', side_effect=lambda key, coroutine: coroutine.close()):
            dialog = page._ensure_multiplayer_dialog()
            backend = dialog.backend
            backend.node_path = 'fixture-node'
            backend.patch(nodeAvailable=False, instanceLoading=False, page='hall')
            invite = RoomInvite.create().encode()
            with patch.object(backend, 'join') as join:
                clipboard.setText(invite)
                self.pump()
                self.assertFalse(page.controller.view['multiplayerAttention'])
                self.assertEqual(backend.clipboard_invite, invite)
                join.assert_not_called()
                backend.patch(nodeAvailable=True)
                backend.join_from_clipboard()
                self.pump()
                join.assert_called_once_with(invite, room_id=None)
                clipboard.clear()
                clipboard.setText(invite)
                self.pump()
                join.assert_called_once()
                self.assertFalse(page.controller.view['multiplayerAttention'])
                backend.patch(busy=True)
                another = RoomInvite.create().encode()
                clipboard.setText(another)
                self.pump()
                join.assert_called_once()
                self.assertTrue(page.controller.view['multiplayerAttention'])
                backend.patch(busy=False)
                self.pump()
                self.assertEqual(join.call_count, 2)
                join.assert_called_with(another, room_id=None)
                self.assertFalse(page.controller.view['multiplayerAttention'])
        self.assert_no_qml_errors()

    def test_translation_source_shares_toggle_section_and_only_shows_when_enabled(self):
        from PySide6.QtCore import QPointF
        self.window.switch_pages('设置')
        self.window.settings_page.general_tab_btn_clicked()
        page = self.window.settings_page.general_page
        page.controller.setValue('translation.enabled', False)
        self.pump()
        self.assertFalse(self.item(page, 'setting-select-translation.source').isVisible())
        self.assertNotIn('translation.source', [group['key'] for group in page.controller.groups])

        page.controller.setValue('translation.enabled', True)
        self.pump()
        source = self.item(page, 'setting-select-translation.source')
        self.assertTrue(source.isVisible())
        self.assertTrue(source.isEnabled())
        section = source.parentItem()
        while section and section.objectName() != 'setting-group-translation.enabled':
            section = section.parentItem()
        self.assertIsNotNone(section)
        self.assertLessEqual(source.mapToScene(QPointF(source.width(), 0)).x(), page.width() - 15)
        page.controller.setValue('translation.source', 'Buggcraft')
        page.controller.setValue('translation.enabled', False)
        self.pump()
        self.assertFalse(self.item(page, 'setting-select-translation.source').isVisible())
        self.assertEqual(self.manager.get_setting('translation.source'), 'Buggcraft')
        page.controller.setValue('translation.enabled', True)
        self.pump()
        self.assertTrue(self.item(page, 'setting-select-translation.source').isVisible())
        self.assertEqual(self.item(page, 'setting-select-translation.source').property('currentText'), 'Buggcraft')
        self.assert_no_qml_errors()

    def test_supported_game_language_can_be_selected_and_is_passed_to_launch(self):
        page = self.window.settings_page.general_page
        controller = page.controller
        group = next(item for item in controller.groups if item['key'] == 'game.language')
        self.assertGreater(len(group['options']), 100)
        controller.setValue('game.language', 'ja_jp')
        self.assertEqual(self.manager.get_setting('game.language'), 'ja_jp')
        home = self.window.started_page
        home.auth_manager.current_mode = 'offline'
        with patch.object(home.auth_manager, 'is_authenticated', return_value=True), patch.object(home.launcher, 'start'):
            home.started_game()
        self.assertEqual(home.launcher._language, 'ja_jp')

    def test_java_download_catalogue_installs_and_preserves_preferred_java(self):
        from core.java_downloads import JavaPackage
        self.window.switch_pages('设置')
        self.window.settings_page.java_tab_btn_clicked()
        page = self.window.settings_page.java_page
        controller = page.controller
        self.snapshot('java-management')
        runtime = self.directory / 'managed-java.exe'
        runtime.touch()
        entry = (str(runtime), 'openjdk version "25.0.1"', [25, 0, 1])
        package = JavaPackage('Eclipse Temurin', 25, '25.0.1', 'windows', 'x64', 'jre',
                              'temurin.zip', 'a' * 64, 12345, ('https://example.test/temurin.zip',))
        with patch('ui.pages.qml_lists.catalogue', return_value=[package]):
            controller.action('', '下载')
            self.wait_until(lambda: not controller.busy)
            controller.set_java_major(25)
            controller.load_java_catalog()
            self.assertTrue(controller.view['busy'])
            self.wait_until(lambda: not controller.busy)
        self.assertEqual(len(controller.view['javaPackages']), 1)
        self.pump()
        from PySide6.QtCore import QObject
        dialog = page.quick.rootObject().findChild(QObject, 'java-download-catalog')
        self.assertIsNotNone(dialog)
        self.assertTrue(dialog.property('visible'))
        self.assertFalse(self.item(page, 'java-versions-section').property('flat'))
        from PySide6.QtCore import QPointF
        controls = [self.item(page, name) for name in
                    ('java-catalog-major', 'java-catalog-source', 'java-catalog-search')]
        for control in controls:
            self.assertAlmostEqual(control.mapToScene(QPointF()).y(),
                                   controls[0].mapToScene(QPointF()).y(), delta=1)
            self.assertEqual(control.height(), 36)
            self.assertGreater(control.width(), 90)
            self.assertLessEqual(control.mapToScene(QPointF(control.width(), 0)).x(), page.width() - 15)
        self.snapshot('java-download-catalog')
        self.click(page, 'java-catalog-back')
        self.pump()
        self.assertFalse(controller.view['javaCatalogOpen'])
        with patch('ui.pages.qml_lists.install_java', return_value=entry):
            controller.download_java(package.checksum)
            self.wait_until(lambda: not controller.busy)
        self.assertIn(list(entry), self.manager.get_setting('java.installations'))
        self.assertEqual(self.manager.get_setting('java.path'), __import__('sys').executable)
        self.assertIn('已安装', controller.view['status'])
        self.assert_no_qml_errors()

    def test_java_search_preserves_manually_installed_runtime(self):
        runtime = self.directory / 'managed-java.exe'
        runtime.touch()
        self.manager.set_setting('java.installations', [[str(runtime), 'Java 25', [25, 0, 1]]])
        with patch('config.javafinder.JavaPathFinder.find_all_java_installations', return_value=[]), \
                patch('config.javafinder.JavaPathFinder._get_java_version', return_value=('Java 25', (25, 0, 1))):
            self.window.load_java_path(notify_missing=False)
            self.wait_until(lambda: not self.window.search_thread.isRunning())
            self.pump()
        self.assertEqual(self.manager.get_setting('java.installations')[0][0], str(runtime))
        self.assert_no_qml_errors()

    def test_room_mod_downloads_are_persisted_in_launcher_task_history(self):
        tasks = self.window.download_page.tasks_page
        cancel = threading.Event()
        game = dict(version='1.20.1', loader='forge', loader_version='47.4.0')
        task_id = tasks.track_room_preparation('好友的房间', str(self.game_dir), game, cancel)
        item = dict(name='example.jar', size=1280, sha256='a' * 64)
        tasks.room_preparation_event(task_id, {'kind':'manifest', 'files':[item]})
        tasks.room_preparation_event(task_id, {'kind':'file', 'name':'example.jar', 'state':'downloading', 'size':1280})
        tasks.room_preparation_event(task_id, {'kind':'progress', 'name':'example.jar', 'done':640, 'total':1280})
        self.assertEqual(tasks._find_task(task_id)['files'][0]['done'], 640)
        tasks.room_preparation_event(task_id, {'kind':'file', 'name':'example.jar', 'state':'verified',
            'size':1280, 'sha256':'a' * 64, 'path':str(self.game_dir / 'mods/example.jar')})
        tasks.room_preparation_event(task_id, {'kind':'complete', 'version':'room-1.20.1-abc', 'loader':'forge'})
        tasks.finish_room_preparation(task_id, True, '房间模组与加载器已安装并校验完成')
        row = tasks._find_task(task_id)
        self.assertEqual(row['state'], '已完成')
        self.assertEqual(row['files'][0]['state'], 'verified')
        self.assertTrue(any('example.jar' in line and 'SHA-256' in line for line in row['logs']))
        tasks.task_action(task_id)
        self.assertEqual(row['state'], '已完成')

    def test_room_preparation_failure_records_the_file_and_reason(self):
        import threading
        tasks = self.window.download_page.tasks_page
        task_id = tasks.track_room_preparation('好友的房间', str(self.game_dir),
            dict(version='1.20.1', loader='forge', loader_version='47.4.0'), threading.Event())
        tasks.room_preparation_event(task_id, {'kind':'manifest', 'files':[
            dict(name='example.jar', size=1280, sha256='a' * 64)]})
        tasks.room_preparation_event(task_id, {'kind':'file', 'name':'example.jar',
            'state':'failed', 'error':'SHA-256 校验失败'})
        tasks.finish_room_preparation(task_id, False, '房间模组下载失败，请返回房间重试')
        row = tasks._find_task(task_id)
        self.assertEqual(row['files'][0]['state'], 'failed')
        self.assertTrue(any('example.jar' in line and 'SHA-256 校验失败' in line for line in row['logs']))

    def test_room_preparation_history_uses_the_launcher_download_page(self):
        from ui.multiplayer_controller import MultiplayerController
        page = self.window.started_page
        from types import SimpleNamespace
        controller = SimpleNamespace(launcher_page=page)
        self.assertIs(MultiplayerController.preparation_history(controller), self.window.download_page.tasks_page)

    def test_hidden_download_pages_create_hosts_only_when_displayed(self):
        downloads = self.window.download_page
        self.assertIsNone(downloads.tasks_page.host._quick)
        self.assertIsNone(downloads.content_page.host._quick)
        downloads.tasks_page.refresh_tasks()
        self.assertIsNone(downloads.tasks_page.host._quick)
        self.window.switch_pages('下载')
        downloads.activate_index(1)
        self.pump()
        self.assertIsNotNone(downloads.tasks_page.quick.rootObject())
        self.assertIsNone(downloads.content_page.host._quick)
        downloads.activate_index(2)
        self.pump()
        self.assertIsNotNone(downloads.content_page.quick.rootObject())
        self.assert_no_qml_errors()

    def test_same_main_button_handles_default_stop_and_multiple_start(self):
        from types import SimpleNamespace
        page = self.window.started_page
        launcher = page.launcher
        worker = SimpleNamespace(process=SimpleNamespace(pid=12345), start_thread=None)
        launcher._sessions = [dict(id=1, phase='running', launcher=worker,
            instance=(str(self.game_dir), '1.21.8', str(self.game_dir / 'versions/1.21.8')))]
        launcher.selected_id = 1
        try:
            for multiple in (False, True):
                self.manager.set_setting('launcher.allow_multiple', multiple)
                page.refresh_game_sessions()
                self.pump()
                self.assertEqual(page.controller.view['launchTitle'], '启动游戏' if multiple else '停止游戏')
                self.assertEqual(self.item(page, 'game-session-actions').isVisible(), multiple)
                with patch.object(page, 'started_game') as start:
                    self.click(page, 'launch-game')
                start.assert_called_once_with(additional=multiple)
                self.snapshot('home-multiple-' + str(multiple))
            names = []
            def collect(item):
                names.append(item.objectName())
                for child in item.childItems():
                    collect(child)
            collect(page.quick.rootObject())
            self.assertNotIn('launch-additional-game', names)
        finally:
            launcher._sessions = []
        self.assert_no_qml_errors()

    def test_all_pages_render_without_widgets_controls_or_qml_errors(self):
        downloads = self.window.download_page
        games = downloads.games_page.controller
        games.versions = [dict(id='1.21.8', type='release', releaseTime='2026-01-01')]
        games.changed.emit()
        tasks = downloads.tasks_page
        tasks._tasks = [dict(id='fixture', version='1.21.8', game_dir=str(self.game_dir),
                            state='已完成', status='安装完成', progress=144, maximum=144,
                            created_at='2026-10-23', logs=['fixture log'])]
        tasks.refresh_tasks()
        self.window.switch_pages('开始')
        self.snapshot('home')
        self.window.switch_pages('下载')
        for index in range(2):
            downloads.activate_index(index)
            self.pump()
            self.snapshot('download-' + str(index))
        downloads.open_content('modpack', 'browse')
        self.wait_until(lambda: not downloads.content_page.controller.busy)
        downloads.content_page.controller.chooseProject(0)
        self.wait_until(lambda: not downloads.content_page.controller.busy)
        self.snapshot('content')
        downloads.open_content('modpack', 'import')
        self.snapshot('import')
        self.window.switch_pages('设置')
        for index in range(4):
            self.window.settings_page.activate_index(index)
            self.pump()
            self.snapshot('settings-' + str(index))
        self.window.switch_pages('实例')
        for index in range(2):
            self.window.version_page.activate_index(index)
            self.pump()
            self.snapshot('instances-' + str(index))
        for dialog in (self.window.started_page.login_dialog,
                       self.window.java_runtime_full, self.window.gamed_version_full):
            dialog.show()
            self.pump()
            self.snapshot(type(dialog).__name__, dialog)
            dialog.hide()
        self.window._show_debug_output()
        self.window.minecraft_handle_output('detail fixture')
        self.pump(120)
        self.assertIn('detail fixture', self.window._debug_dialog.controller.log)
        widgets = self.window.findChildren(QQuickWidget)
        self.assertGreaterEqual(len(widgets), 18)
        for widget in widgets:
            self.assertEqual(widget.status(), QQuickWidget.Ready,
                             '\n'.join(error.toString() for error in widget.errors()))
        self.assertEqual(self.window.findChildren(QAbstractButton), [])
        self.assertEqual(self.window.findChildren(QLineEdit), [])
        self.assertEqual(self.window.findChildren(QPlainTextEdit), [])
        self.assert_no_qml_errors()

    def test_hidden_pages_are_loaded_on_demand(self):
        self.assertEqual(self.window.started_page.quick.status(), QQuickWidget.Ready)
        self.assertEqual(self.window.settings_page.java_page.quick.status(), QQuickWidget.Null)
        self.assertEqual(self.window.started_page.login_dialog.quick.status(), QQuickWidget.Null)
        self.window.switch_pages('设置')
        self.window.settings_page.java_tab_btn_clicked()
        self.pump()
        self.assertEqual(self.window.settings_page.java_page.quick.status(), QQuickWidget.Ready)
        self.assert_no_qml_errors()

    def test_stale_version_cannot_be_selected_and_empty_directory_clears_home(self):
        header = self.window.title_bar
        (self.game_dir / 'versions/1.20.1/1.20.1.json').unlink()
        header.controller.selectVersion('1.20.1')
        self.assertEqual(self.manager.get_setting('minecraft.version.enable'), '1.21.8')
        self.assertNotIn('1.20.1', header.controller.versions)
        empty = str(self.directory / 'empty')
        self.manager.set_setting('minecraft.directory.installed', [empty])
        instances = self.window.version_page.versions_page.controller
        instances.reload()
        instances.selectDirectory(empty)
        self.assertIsNone(self.manager.get_setting('minecraft.version.enable'))
        self.assertIsNone(self.window.launcher.minecraft_version)
        self.assertEqual(self.window.started_page.controller.view['launchTitle'], '选择游戏')
        self.click(header, 'version-picker')
        self.assertTrue(header.quick.rootObject().property('versionPopupVisible'))
        QTest.keyClick(header._picker.quick, Qt.Key_Escape)
        self.pump()
        self.assertFalse(header.quick.rootObject().property('versionPopupVisible'))
        self.assert_no_qml_errors()

    def test_collapse_crops_original_image_and_keeps_content_in_place_on_all_pages(self):
        from PySide6.QtCore import QPoint
        expanded = self.window.size()
        right = self.window.x() + self.window.width()
        cropped = self.window.cache_expanded.copy(self.window.menu_width, 0,
                      expanded.width() - self.window.menu_width, expanded.height())
        self.assertEqual(self.window.cache_collapsed.toImage(), cropped.toImage())
        for name in self.window.tab_names:
            self.window.switch_pages(name)
            self.pump()
            self.assertEqual(self.window.title_bar.controller.active, name)
            page = self.window.content_stack.currentWidget()
            content = getattr(page, 'stack', page)
            def position():
                if page is self.window.started_page:
                    button = self.item(page, 'launch-game')
                    return self.window.pos() + page.quick.mapTo(self.window, button.mapToScene(button.boundingRect().center()).toPoint())
                return self.window.pos() + content.mapTo(self.window, QPoint(0, 0))
            origin = position()
            width = content.width()
            for _ in range(8):
                self.window.title_bar.controller.toggleMenu()
                self.pump()
                collapsed = self.window.menu_collapsed
                self.assertEqual(self.window.width(), expanded.width() - (self.window.menu_width if collapsed else 0))
                self.assertEqual(self.window.height(), expanded.height())
                self.assertEqual(self.window.x() + self.window.width(), right)
                self.assertEqual(position(), origin, name)
                if page is not self.window.started_page:
                    self.assertEqual(content.width(), width, name)
                self.assertEqual(collapsed, self.window.title_bar.controller.collapsed)
            self.snapshot('sidebar-' + name)
        self.assert_no_qml_errors()

    def test_game_category_buttons_switch_to_real_content(self):
        downloads = self.window.download_page
        downloads.on_download_clicked()
        self.pump()
        categories = self.item(downloads.games_page, 'download-categories')
        geometry = (categories.x(), categories.y(), categories.width(), categories.height())
        for index, kind in enumerate(('mod', 'resourcepack', 'shader', 'modpack'), 1):
            self.click(downloads.games_page, 'content-kind-' + str(index))
            self.wait_until(lambda: not downloads.content_page.controller.busy)
            self.assertIs(downloads.stack.currentWidget(), downloads.games_page)
            self.assertEqual(downloads.navigation.index, 0)
            self.assertEqual(downloads.navigation.entries, ['游戏下载', '下载记录'])
            self.assertEqual(downloads.games_page.controller.category, kind)
            self.assertEqual(downloads.content_page.controller.kind, kind)
            self.assertEqual(len(downloads.content_page.controller.results), 1)
            self.assertEqual((categories.x(), categories.y(), categories.width(), categories.height()), geometry)
            self.assertEqual(downloads.games_page.quick.rootObject().property('state').toVariant()['category'], kind)
        self.click(downloads.games_page, 'content-kind-0')
        self.assertEqual(downloads.games_page.controller.category, 'game')
        self.assertIs(downloads.stack.currentWidget(), downloads.games_page)
        self.assert_no_qml_errors()

    def test_settings_preserve_sections_radios_and_collapsed_state_after_save(self):
        self.window.switch_pages('设置')
        self.window.settings_page.global_tab_btn_clicked()
        page = self.window.settings_page.global_version_page
        self.pump()
        groups = page.controller.groups
        self.assertEqual([group['title'] for group in groups], [
            '版本隔离', '游戏 Java', '游戏内存分配', '启动器可见性',
            '游戏窗口分辨率', '进程优先级', '游戏调试模式'])
        isolation = self.item(page, 'setting-group-minecraft.isolation')
        self.assertTrue(isolation.property('expanded'))
        self.click(page, 'setting-option-minecraft.isolation-0')
        self.assertFalse(self.manager.get_setting('minecraft.isolation'))
        self.click(page, 'setting-group-minecraft.isolation-header')
        self.assertFalse(self.item(page, 'setting-group-minecraft.isolation').property('expanded'))
        page.controller.setValue('launcher.window_size', '最大化')
        self.pump()
        self.assertFalse(self.item(page, 'setting-group-minecraft.isolation').property('expanded'))
        self.assertEqual(self.item(page, 'setting-group-minecraft.isolation').height(), 60)
        self.assertTrue(page.memory_timer.isActive())
        self.window.settings_page.general_tab_btn_clicked()
        self.pump()
        self.assertFalse(page.memory_timer.isActive())
        self.assert_no_qml_errors()

    def test_settings_descriptions_and_game_list_use_existing_bounds_and_row_style(self):
        from PySide6.QtCore import QPointF
        self.window.switch_pages('设置')
        self.window.settings_page.global_tab_btn_clicked()
        page = self.window.settings_page.global_version_page
        self.pump()
        for index in range(2):
            description = self.item(page, 'setting-option-minecraft.isolation-' + str(index) + '-description')
            self.assertLessEqual(description.mapToScene(QPointF(description.width(), 0)).x(), page.width() - 15)
        downloads = self.window.download_page
        downloads.games_page.controller.versions = [dict(id='1.20.1', type='release', releaseTime='2026-01-01')]
        downloads.on_download_clicked()
        self.pump()
        row = self.item(downloads.games_page, 'install-1.20.1')
        self.assertEqual(row.height(), 70)
        self.assertEqual(row.property('radius'), 0)
        self.assertTrue(row.property('icon').toString().endswith('offline_login.png'))
        self.assert_no_qml_errors()

    def test_settings_controls_share_alignment_in_general_global_and_instance_pages(self):
        from PySide6.QtCore import QPointF

        def left(page, name):
            return self.item(page, name).mapToScene(QPointF()).x()

        self.window.switch_pages('设置')
        self.window.settings_page.general_tab_btn_clicked()
        page = self.window.settings_page.general_page
        self.pump()
        for key in ('launcher.allow_multiple', 'translation.enabled'):
            self.assertAlmostEqual(left(page, 'setting-toggle-' + key + '-indicator'),
                                   left(page, 'setting-description-' + key), delta=1)
        self.snapshot('settings-general-aligned')

        for scope in ('global', 'instance'):
            if scope == 'global':
                self.window.settings_page.global_tab_btn_clicked()
                page = self.window.settings_page.global_version_page
            else:
                self.window.switch_pages('实例')
                self.window.version_page.activate_index(1)
                page = self.window.version_page.settings_page
                page.controller.setValue('instance.enable', True)
            self.pump()
            section_left = left(page, 'setting-group-minecraft.isolation-title')
            for index in (0, 1):
                self.assertAlmostEqual(section_left,
                    left(page, 'setting-option-minecraft.isolation-' + str(index) + '-indicator'), delta=1)
            if scope == 'instance':
                self.assertAlmostEqual(left(page, 'setting-toggle-instance.enable-indicator'),
                                       left(page, 'setting-description-instance.enable'), delta=1)
            text_left = left(page, 'setting-toggle-minecraft.auto_allocate_memory-indicator')
            for name in ('setting-memory-label', 'setting-memory-bar', 'setting-memory-info'):
                self.assertAlmostEqual(text_left, left(page, name), delta=1)
            self.assertAlmostEqual(section_left,
                left(page, 'setting-toggle-minecraft.auto_allocate_memory-indicator'), delta=1)
            self.click(page, 'setting-group-java.path-header')
            self.snapshot('settings-' + scope + '-aligned')
        self.assert_no_qml_errors()

    def test_import_entry_returns_to_previous_catalogue_without_duplicate_sidebar_route(self):
        downloads = self.window.download_page
        downloads.open_content('mod', 'browse')
        self.wait_until(lambda: not downloads.content_page.controller.busy)
        with patch.object(downloads.content_page.controller, 'choosePack') as choose:
            self.click(downloads.games_page, 'download-import-pack')
        choose.assert_called_once()
        self.assertEqual(downloads.content_page.controller.view, 'import')
        self.assertIs(downloads.stack.currentWidget(), downloads.content_page)
        self.click(downloads.content_page, 'pack-import-back')
        self.pump()
        self.assertIs(downloads.stack.currentWidget(), downloads.games_page)
        self.assertEqual(downloads.games_page.controller.category, 'mod')
        self.assertEqual(downloads.content_page.controller.kind, 'mod')
        self.assertEqual(len(downloads.content_page.controller.results), 1)
        self.assert_no_qml_errors()

    def test_memory_uses_one_section_and_manual_slider_enables_without_changing_scope(self):
        page = self.window.settings_page.global_version_page
        self.window.switch_pages('设置')
        self.window.settings_page.global_tab_btn_clicked()
        page.controller.setValue('minecraft.auto_allocate_memory', False)
        self.pump()
        groups = page.controller.groups
        memory = next(group for group in groups if group['kind'] == 'memory')
        self.assertTrue(memory['memory']['enabled'])
        self.assertFalse(any(group['key'] == 'memory.allocation' for group in groups))
        page.controller.setValue('memory.allocation', 3072)
        self.pump()
        self.assertEqual(self.manager.get_setting('memory.allocation'), 3072)
        self.assertGreater(page.controller.memoryInfo['total'], 0)
        self.assertEqual([section['title'] for section in self.window.settings_page.about_page.controller.view['sections']],
                         ['关于', '鸣谢', '依赖', '法律声明'])
        self.assert_no_qml_errors()

    def test_version_picker_changes_selected_game_once(self):
        from PySide6.QtTest import QSignalSpy
        instances = self.window.version_page.versions_page
        # Keep the instance list loaded to catch missing selection notifications.
        self.window.switch_pages('实例')
        instances.ensure_loaded()
        changes = QSignalSpy(instances.controller.changed)
        spy = QSignalSpy(self.window.title_bar.version_changed)
        header = self.window.title_bar
        picker = self.item(header, 'version-picker')
        self.click(header, 'version-picker')
        self.assertTrue(header.quick.rootObject().property('versionPopupVisible'))
        QTest.keyClick(header._picker.quick, Qt.Key_Down)
        QTest.keyClick(header._picker.quick, Qt.Key_Return)
        self.pump()
        self.assertEqual(self.window.launcher.minecraft_version, '1.20.1')
        self.assertEqual(spy.count(), 1)
        self.assertGreater(changes.count(), 0)
        self.assertEqual(instances.quick.rootObject().property('state').toVariant()['selected'], '1.20.1')
        instances.controller.selectVersion('1.21.8')
        self.pump()
        self.assertEqual(header.controller.view['selected'], '1.21.8')
        self.assertEqual(self.window.launcher.minecraft_version, '1.21.8')
        self.assert_no_qml_errors()

    def test_header_preserves_button_sizes_and_scrolls_current_version_into_popup(self):
        for index in range(16):
            name = 'zz-fixture-' + str(index).zfill(2)
            target = self.game_dir / 'versions' / name / (name + '.json')
            target.parent.mkdir(parents=True)
            target.write_text(json.dumps({'id': name}), encoding='utf-8')
        header = self.window.title_bar
        header.refresh_versions()
        header.controller.selectVersion(header.controller.versions[-1])
        selected_version = header.controller.selected
        self.pump()
        for name, width in (('version-picker', 125), ('instances-button', 110)):
            button = self.item(header, name)
            self.assertEqual((button.width(), button.height()), (width, 32))
        self.click(header, 'version-picker')
        popup = header._picker
        self.assertEqual((popup.width(), popup.height()), (310, 420))
        self.assertEqual(header.controller.versions[0], selected_version)
        self.assertEqual(self.item(header, 'version-picker').property('text'), '版本')
        selected = self.item(popup.host, 'choice-option-0')
        self.assertTrue(selected.property('selected'))
        center = selected.mapToScene(selected.boundingRect().center())
        self.assertGreater(center.y(), 0)
        self.assertLess(center.y(), popup.height())
        self.assertTrue(self.app.screenAt(popup.pos()).availableGeometry().contains(popup.geometry()))
        self.snapshot('version-dropdown', popup)
        QTest.keyClick(popup.quick, Qt.Key_End)
        self.pump()
        first = self.item(popup.host, 'choice-option-' + str(len(header.controller.versions) - 1))
        self.assertFalse(first.property('selected'))
        self.assertTrue(first.property('keyboardFocused'))
        QTest.keyClick(popup.quick, Qt.Key_Escape)
        self.assertEqual(header.controller.selected, selected_version)
        self.window.switch_pages('实例')
        self.pump()
        self.assertTrue(self.item(header, 'instances-button').property('selected'))
        self.assert_no_qml_errors()

    def test_loader_dialog_loads_and_enforces_exclusions(self):
        page = self.window.download_page.games_page
        page.controller.versions = [dict(id='1.20.1', type='release', releaseTime='2026-01-01')]
        page.controller.changed.emit()
        self.window.download_page.on_download_clicked()
        self.pump()
        self.click(page, 'install-1.20.1')
        page.controller.selectLoader('Forge')
        self.wait_until(lambda: not page.controller.loader_busy)
        blocked = {item['name']: item['reason'] for item in page.controller.view['components']}
        self.assertIn('Forge', blocked['Fabric'])
        page.controller.selectLoader('Fabric')
        self.assertEqual(page.controller.loader, 'Forge')
        self.snapshot('install-game')
        self.assert_no_qml_errors()

    def test_version_popup_reuses_host_and_repeated_mouse_keyboard_and_cancel_work(self):
        header = self.window.title_bar
        popup = None
        for index in range(18):
            previous = header.controller.selected
            self.click(header, 'version-picker')
            self.assertTrue(header.controller.picker_open)
            if popup is None:
                popup = header._picker
            self.assertIs(header._picker, popup)
            # Exercise the QWidget hit-testing path with the popup present.
            self.app.widgetAt(popup.mapToGlobal(popup.rect().center()))
            if index % 3 == 0:
                QTest.keyClick(popup.quick, Qt.Key_Escape)
                expected = previous
            elif index % 3 == 1:
                QTest.keyClick(popup.quick, Qt.Key_End)
                QTest.keyClick(popup.quick, Qt.Key_Return)
                expected = header.controller.versions[-1]
            else:
                self.click(popup.host, 'choice-option-0')
                expected = header.controller.versions[0]
            self.pump()
            self.assertFalse(header.controller.picker_open)
            self.assertEqual(header.controller.selected, expected)
        self.assert_no_qml_errors()

    def test_header_close_button_finishes_handler_before_unloading(self):
        self.click(self.window.title_bar, 'close-launcher')
        self.assertFalse(self.window.isVisible())
        self.assertTrue(self.window._closing)
        self.assertEqual(self.window.title_bar.quick.status(), QQuickWidget.Null)
        self.assert_no_qml_errors()

    def test_settings_save_to_correct_scope(self):
        general = self.window.settings_page.general_page.controller
        general.setValue('launcher.allow_multiple', True)
        self.assertTrue(self.manager.get_setting('launcher.allow_multiple'))
        global_settings = self.window.settings_page.global_version_page.controller
        global_settings.setValue('launcher.window_size', '最大化')
        self.assertEqual(self.manager.get_setting('launcher.window_size'), '最大化')
        instance = self.window.version_page.settings_page.controller
        instance.setValue('instance.enable', True)
        instance.setValue('launcher.window_size', '与启动器一致')
        self.assertEqual(self.manager.get_version_setting('launcher.window_size'), '与启动器一致')
        self.assertEqual(self.manager.get_setting('launcher.window_size'), '最大化')


if __name__ == '__main__':
    import unittest
    unittest.main()
