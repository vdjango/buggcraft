"""Click the shipping home/lobby/friends windows during account failures."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

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
        self.page = self.window.started_page
        self.dialog = self.page._ensure_multiplayer_dialog()
        self.backend = self.dialog.backend
        self.path = self.directory / 'personal.json'
        save_json(self.path, profile_data(personal_profile()))
        self.backend.store.add_node(str(self.path))
        self.backend.reload_store()
        self.pump()

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

    def test_expired_personal_account_entry_opens_code_recovery(self):
        save_json(self.path, profile_data(personal_profile(expiry=1)))
        with patch.object(self.backend, 'prompt_node_credential_update',
                           side_effect=lambda: setattr(self.backend, 'credential_prompted_node', self.backend.node_path)):
            self.backend.reload_store()
        self.pump()
        friends = self.open_friends()
        self.assertEqual(self.item(friends, 'friend-access-mode').property('text'), '接入码已过期')
        self.click(friends, 'friends-replace-node-code')
        self.assertEqual(self.backend.view['page'], 'nodes')
        self.assertTrue(self.dialog.isVisible())
        self.assert_no_qml_errors()

    def test_rejected_personal_credential_exposes_code_replacement_action(self):
        self.backend.patch(nodeCredentialRequired=True,
                           socialLoading=False, socialError='个人启动器接入码需要更新。')
        friends = self.open_friends()
        action = self.item(friends, 'friends-replace-node-code')
        self.assertEqual(action.property('text'), '更换接入码')
        self.click(friends, 'friends-replace-node-code')
        self.assertEqual(self.backend.view['page'], 'nodes')

    def test_cached_friends_credential_rejection_keeps_visible_recovery_action(self):
        self.backend.apply_social_state(social_state())
        self.backend.patch(nodeCredentialRequired=True, socialState='stale',
                           socialError='个人启动器接入码需要更新。')
        friends = self.open_friends()
        action = self.item(friends, 'friends-stale-recovery')
        self.assertTrue(action.isVisible())
        self.assertEqual(action.property('text'), '更换接入码')
        self.click(friends, 'friends-stale-recovery')
        self.assertEqual(self.backend.view['page'], 'nodes')
        self.assert_no_qml_errors()
