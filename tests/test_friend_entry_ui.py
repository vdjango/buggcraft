"""Click the shipping home/lobby/friends windows during account failures."""
from pathlib import Path
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PySide6.QtCore import QMetaObject, QUrl
from PySide6.QtQuick import QQuickView

from _qml_test_support import LauncherQmlCase
from test_friend_entry_regression import personal_profile, social_state
from hookup.nodes import save_json, profile_data
from hookup.profiles import RelayProfile
from ui.multiplayer_controller import MultiplayerController


class FriendEntryUiTests(LauncherQmlCase):
    def setUp(self):
        super().setUp()
        service = patch('ui.multiplayer_controller.TunnelService', return_value=Mock(endpoints={}))
        jobs = patch.object(MultiplayerController, 'job', side_effect=lambda key, task: task.close())
        service.start()
        jobs.start()
        self.addCleanup(service.stop)
        self.addCleanup(jobs.stop)
        network_profile = patch.object(MultiplayerController, 'refresh_network_profile')
        network_profile.start()
        self.addCleanup(network_profile.stop)
        self.page = self.window.started_page
        self.dialog = self.page._ensure_multiplayer_dialog()
        self.backend = self.dialog.backend
        self.path = self.directory / 'personal.json'
        save_json(self.path, profile_data(personal_profile()))
        self.backend.store.add_node(str(self.path))
        self.backend.reload_store()
        self.pump()

    def test_queued_floating_button_layout_is_safe_after_page_unload(self):
        source = self.directory / 'floating-lifecycle.qml'
        imports = (Path(__file__).resolve().parents[1] / 'resources/qml/multiplayer').as_uri()
        source.write_text('import QtQuick\nimport "' + imports + '"\n'
            'Item { width: 721; height: 505\n'
            ' FloatingFriends { id: button; manuallyPositioned: true; y: 420 }\n'
            ' function queueClamp() { button.maximumY = 100 }\n}', encoding='utf-8')
        view = QQuickView()
        try:
            for _ in range(5):
                view.setSource(QUrl.fromLocalFile(str(source)))
                self.assertEqual(view.status(), QQuickView.Ready)
                self.assertTrue(QMetaObject.invokeMethod(view.rootObject(), 'queueClamp'))
                # Deliberately unload before Qt.callLater dispatches its clamp.
                view.setSource(QUrl())
                self.pump()
            self.assert_no_qml_errors()
        finally:
            view.close()
            view.deleteLater()

    def test_login_start_opens_browser_then_waits_for_authorization(self):
        from cryptography.hazmat.primitives.asymmetric import ec

        self.backend.act('loginOfficialDevice', {'origin': 'community.example', 'remember': True})
        self.assertEqual(self.backend.view['deviceLoginStage'], 'preparing')
        self.assertTrue(self.backend.view['deviceLoginBusy'])
        generation = self.backend.device_login_generation
        result = {'verification_uri': 'https://community.example/account/access?launcher=device-id'}
        with patch('ui.multiplayer_controller.webbrowser.open', return_value=True) as opened:
            self.backend.finish('device-login-start:' + generation,
                                (result, ec.generate_private_key(ec.SECP256R1())), None)
        opened.assert_called_once_with(result['verification_uri'])
        self.assertEqual(self.backend.view['deviceLoginStage'], 'waiting')
        self.assertTrue(self.backend.device_login_timer.isActive())
        self.assertIn('已打开默认浏览器', self.backend.view['deviceLoginMessage'])
        self.backend.act('cancelDeviceLogin', {})
        self.assertFalse(self.backend.device_login_timer.isActive())
        self.assertFalse(self.backend.view['deviceLoginBusy'])

    def test_login_browser_failure_keeps_copy_link_available(self):
        self.backend.device_login = ({}, None, 'generation')
        self.backend.patch(deviceLoginBusy=True, deviceLoginStage='waiting',
                           deviceLoginUrl='https://community.example/account/access?launcher=device-id')
        with patch('ui.multiplayer_controller.webbrowser.open', side_effect=OSError), \
             patch('ui.multiplayer_controller.QDesktopServices.openUrl', side_effect=RuntimeError):
            self.backend.open_device_browser()
        self.assertIn('复制登录链接', self.backend.view['deviceLoginMessage'])
        self.assertTrue(self.backend.view['deviceLoginUrl'])
        self.backend.act('cancelDeviceLogin', {})

    def test_failed_or_canceled_login_start_never_opens_browser(self):
        self.backend.act('loginOfficialDevice', {'origin': 'node.example'})
        key = 'device-login-start:' + self.backend.device_login_generation
        with patch('ui.multiplayer_controller.webbrowser.open') as opened:
            self.backend.finish(key, None, '节点代理拒绝了启动器请求（HTTP 403）')
            self.assertFalse(self.backend.view['deviceLoginBusy'])
            self.assertIn('HTTP 403', self.backend.view['deviceLoginMessage'])
            self.backend.act('loginOfficialDevice', {'origin': 'node.example'})
            key = 'device-login-start:' + self.backend.device_login_generation
            self.backend.act('cancelDeviceLogin', {})
            self.backend.finish(key, ({'verification_uri': 'https://node.example'}, None), None)
            opened.assert_not_called()
        self.assertEqual(self.backend.view['deviceLoginStage'], 'idle')

    def fail_refresh(self):
        key = 'socialstatus:' + self.backend.social_generation + ':' + self.backend.node_path
        self.backend.finish(key, None, 'SSH authentication rejected / timeout fixture')
        self.pump()

    def open_friends(self):
        self.click(self.page, 'open-friends-home')
        self.assertTrue(self.dialog.friends_window.isVisible())
        return SimpleNamespace(quick=self.dialog.friends_window.quick)

    def test_first_login_failure_has_clickable_entry_and_real_retry_action(self):
        self.fail_refresh()
        friends = self.open_friends()
        self.assertTrue(self.item(friends, 'friends-sign-in').isVisible())
        self.assertNotEqual(self.item(friends, 'friend-access-mode').property('text'), '匿名接入')
        with patch.object(self.backend, 'refresh_friends') as retry:
            self.click(friends, 'friends-replace-node-code')
        retry.assert_called_once()
        self.assertNotEqual(self.backend.view['page'], 'nodes')
        self.snapshot('friends-initial-failure', self.dialog.friends_window)
        self.assert_no_qml_errors()

    def test_click_open_close_filters_copy_and_recovery_after_many_failures(self):
        self.backend.apply_social_state(social_state())
        self.pump()
        friends = self.open_friends()
        self.click(friends, 'copy-social-name')
        self.assertEqual(self.app.clipboard().text(), social_state()['account'])
        for _ in range(12):
            self.fail_refresh()
        with patch.object(RelayProfile, 'load', side_effect=PermissionError('sharing violation')):
            self.backend.reload_store()
        self.pump()
        self.assertTrue(self.item(friends, 'friends-stale-state').isVisible())
        self.assertEqual(self.item(friends, 'friends-list').property('count'), 1)
        self.assertEqual(self.item(friends, 'friend-presence-0').property('text'), '在线状态未知')
        self.click(friends, 'friend-filter-online')
        self.assertEqual(self.item(friends, 'friends-list').property('count'), 0)
        self.click(friends, 'friend-filter-all')
        self.assertEqual(self.item(friends, 'friends-list').property('count'), 1)
        self.snapshot('friends-stale-contacts', self.dialog.friends_window)
        self.dialog.friends_window.close()
        self.pump()
        self.assertTrue(self.item(self.page, 'open-friends-home').isVisible())
        self.open_friends()
        self.dialog.show()
        self.pump()
        self.assertTrue(self.item(self.dialog, 'open-friends-window').isVisible())
        self.dialog.friends_window.close()
        self.click(self.dialog, 'open-friends-window')
        self.assertTrue(self.dialog.friends_window.isVisible())
        key = 'socialstatus:' + self.backend.social_generation + ':' + self.backend.node_path
        self.backend.finish(key, dict(path=self.backend.node_path, state=social_state()), None)
        self.pump()
        self.assertFalse(self.item(friends, 'friends-stale-state').isVisible())
        self.assertTrue(self.backend.view['contacts'][0]['online'])
        self.snapshot('friends-recovered', self.dialog.friends_window)
        self.assert_no_qml_errors()

    def test_network_type_uses_beginner_friendly_labels_in_friends_and_hall(self):
        network = dict(type='direct_easier', direct_successes=3, relay_successes=1)
        state = social_state()
        state['networkProfile'] = network
        state['friends'][0]['network_profile'] = network
        self.backend.apply_social_state(state)
        self.backend.patch(playerNetworkProfile=network, playerNetworkTypeReady=True, playerNetworkProfileReady=True)
        self.pump()
        friends = self.open_friends()
        self.assertIn('你的网络类型：较容易直连', self.item(friends, 'my-network-type').property('text'))
        self.assertIn('直连成功 3 次', self.item(friends, 'friend-network-type-0').property('text'))
        state['friends'][0].pop('network_profile')
        self.backend.apply_social_state(state)
        self.pump()
        self.assertIn('暂无联机记录', self.item(friends, 'friend-network-type-0').property('text'))
        self.backend.patch(page='hall')
        self.pump()
        self.assertIn('你的网络类型：较容易直连', self.item(self.dialog, 'hall-network-type').property('text'))
        for item in ('my-network-type', 'my-network-history', 'hall-network-type'):
            text = str(self.item(friends if item != 'hall-network-type' else self.dialog, item).property('text'))
            self.assertNotRegex(text, r'实测|IPv[46]|UDP')
        self.assert_no_qml_errors()

    def test_network_type_appears_before_history_scan_finishes(self):
        self.backend.patch(page='hall')
        self.backend.player_network_profile_task = True
        self.backend.update_network_type(self.backend.generation, 'direct_easier')
        self.pump()
        label = self.item(self.dialog, 'hall-network-type')
        self.assertIn('较容易直连', label.property('text'))
        self.assertNotIn('正在判断', label.property('text'))
        self.assertIn('正在读取近7天联机记录', label.property('text'))
        self.assertFalse(self.backend.view['playerNetworkProfileReady'])
        self.assertTrue(self.backend.player_network_profile_task)

        profile = dict(type='direct_easier', direct_successes=2, relay_successes=0)
        self.backend.finish('network-profile:' + self.backend.generation, profile, None)
        self.pump()
        self.assertFalse(self.backend.player_network_profile_task)
        self.assertIn('较容易直连', label.property('text'))
        self.assertIn('直连成功 2 次', label.property('text'))
        self.assert_no_qml_errors()

    def test_expired_personal_account_entry_opens_code_recovery(self):
        save_json(self.path, profile_data(personal_profile(expiry=1)))
        with patch.object(self.backend, 'prompt_node_credential_update',
                           side_effect=lambda: setattr(self.backend, 'credential_prompted_node', self.backend.node_path)):
            self.backend.reload_store()
        self.pump()
        friends = self.open_friends()
        self.assertEqual(self.item(friends, 'friend-access-mode').property('text'), '登录已失效')
        self.click(friends, 'friends-replace-node-code')
        self.assertEqual(self.backend.view['page'], 'nodes')
        self.assertTrue(self.dialog.isVisible())
        self.assert_no_qml_errors()

    def test_rejected_personal_credential_exposes_code_replacement_action(self):
        self.backend.patch(nodeCredentialRequired=True,
                           socialLoading=False, socialError='个人启动器接入码需要更新。')
        friends = self.open_friends()
        action = self.item(friends, 'friends-replace-node-code')
        self.assertEqual(action.property('text'), '重新登录')
        self.click(friends, 'friends-replace-node-code')
        self.assertEqual(self.backend.view['page'], 'nodes')

    def test_revoked_device_login_offers_browser_recovery_at_original_node(self):
        save_json(self.path, profile_data(personal_profile(expiry=int(time.time()) + 3 * 86400)))
        save_json(str(self.path) + '.device.json', {'id': 'device', 'origin': 'https://community.example:18443'})
        self.backend.reload_store(refresh_identity=True)
        self.assertTrue(self.backend.view['deviceManaged'])
        self.assertTrue(self.backend.view['nodes'][0]['deviceManaged'])
        self.backend.apply_social_state(social_state())
        self.backend.social_failure('request', 'Invalid delegated key')
        dialog = self.backend.credential_prompt_dialog
        self.assertIsNotNone(dialog)
        # macOS native alerts can omit the window title; the visible guidance
        # and recovery action are the cross-platform contract.
        self.assertIn('浏览器登录', dialog.text())
        self.assertTrue(any(button.text() == '前往重新登录' for button in dialog.buttons()))
        next(button for button in dialog.buttons() if button.text() == '稍后').click()
        friends = self.open_friends()
        self.assertEqual(self.item(friends, 'friends-stale-recovery').property('text'), '重新登录')
        self.click(friends, 'friends-stale-recovery')
        self.assertEqual(self.backend.view['page'], 'nodes')
        self.assertEqual(self.backend.view['deviceOrigin'], 'https://community.example:18443')
        self.pump()
        self.assertEqual(self.item(self.dialog, 'node-web-address').property('text'),
                         'https://community.example:18443')
        self.assertTrue(self.path.is_file())
        self.assert_no_qml_errors()

    def test_expired_device_refresh_denial_exposes_relogin_and_keeps_node(self):
        save_json(str(self.path) + '.device.json', {'id': 'device', 'origin': 'https://community.example'})
        self.backend.reload_store()
        save_json(self.path, profile_data(personal_profile(expiry=1)))
        self.backend.finish('device-refresh:' + self.backend.node_path, None, '授权已失效')
        self.assertTrue(self.backend.view['nodeAccessExpired'])
        self.assertTrue(self.backend.view['nodeCredentialRequired'])
        self.assertFalse(self.backend.view['nodeAvailable'])
        dialog = self.backend.credential_prompt_dialog
        self.assertIsNotNone(dialog)
        next(button for button in dialog.buttons() if button.text() == '前往重新登录').click()
        self.assertEqual(self.backend.view['page'], 'nodes')
        self.assertEqual(self.backend.view['deviceOrigin'], 'https://community.example')
        self.assertTrue(self.path.is_file())
        friends = self.open_friends()
        self.assertEqual(self.item(friends, 'friends-replace-node-code').property('text'), '重新登录')
        self.assert_no_qml_errors()

    def test_transient_device_refresh_error_keeps_valid_login_for_retry(self):
        save_json(str(self.path) + '.device.json', {'id': 'device', 'origin': 'https://community.example'})
        self.backend.reload_store()
        self.backend.apply_social_state(social_state())
        self.backend.finish('device-refresh:' + self.backend.node_path, None, 'connection timed out')
        self.assertFalse(self.backend.view['nodeCredentialRequired'])
        self.assertIsNone(self.backend.credential_prompt_dialog)
        self.assertTrue(self.backend.view['socialReady'])
        self.assertNotIn(self.backend.node_path, self.backend.device_refresh_denied)
        self.assertIn('自动重试', self.backend.view['notice'])

    def test_cached_friends_credential_rejection_keeps_visible_recovery_action(self):
        self.backend.apply_social_state(social_state())
        self.backend.patch(nodeCredentialRequired=True, socialState='stale',
                           socialError='个人启动器接入码需要更新。')
        friends = self.open_friends()
        action = self.item(friends, 'friends-stale-recovery')
        self.assertTrue(action.isVisible())
        self.assertEqual(action.property('text'), '重新登录')
        self.click(friends, 'friends-stale-recovery')
        self.assertEqual(self.backend.view['page'], 'nodes')
        self.assert_no_qml_errors()
