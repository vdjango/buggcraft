"""Friends survive service failures; only verified identity changes reset them."""
import asyncio
import base64
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/buggcraft'))
from PySide6.QtWidgets import QApplication, QDialog
from tests.native_fixtures import ssh_public_key
from hookup.nodes import save_json, profile_data
from hookup.profiles import RelayProfile
from ui.multiplayer_controller import MultiplayerController

ACCOUNT = 'a' * 32 + '.' + 'b' * 32
FRIEND = 'c' * 32 + '.' + 'd' * 32


def personal_profile(expiry=None, salt='test'):
    claims = dict(e=int(time.time()) + 3600 if expiry is None else expiry, g=dict(d=True), salt=salt)
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip('=')
    return RelayProfile('127.0.0.1', 3333, 'acct1.' + payload + '.signature~test-secret',
                        ssh_public_key())


def social_state():
    return dict(account=ACCOUNT, username='owner', friends=[dict(account=FRIEND, username='Alice', online=True)],
                requests=[], invitations=[])


class FriendEntryRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.window = QDialog()
        self.addCleanup(self.window.close)
        self.service = Mock(endpoints={})
        self.jobs = patch.object(MultiplayerController, 'job', side_effect=lambda key, task: task.close())
        self.jobs.start()
        self.addCleanup(self.jobs.stop)
        with patch('ui.multiplayer_controller.TunnelService', return_value=self.service):
            self.backend = MultiplayerController(self.window, Path(self.temp.name) / 'lobby.json')
        self.addCleanup(self.backend.close)
        self.path = Path(self.temp.name) / 'node.json'
        save_json(self.path, profile_data(personal_profile()))
        self.backend.store.add_node(str(self.path))
        self.backend.reload_store()

    def fail_refresh(self, message='node timeout'):
        self.backend.finish('socialstatus:' + self.backend.social_generation + ':' + self.backend.node_path,
                            None, message)

    def test_stale_room_presence_retries_without_hiding_friends(self):
        self.backend._state['socialCapabilities'] = {'room_presence': True}
        self.backend.player_network_profile = {'type': 'unknown'}
        with patch.object(self.backend, '_friend_room_presence', return_value={'room': {'id': 'stale'}}), \
                patch.object(self.backend, 'job') as job, \
                patch('hookup.social.status', new_callable=AsyncMock) as status:
            status.side_effect = [RuntimeError('room route rejected'), social_state()]
            self.backend.refresh_friends()
            result = asyncio.run(job.call_args.args[1])
        self.assertEqual(result['state']['friends'][0]['username'], 'Alice')
        self.assertEqual(status.await_count, 2)
        self.assertNotIn('room', status.await_args_list[1].args[1])

    def test_personal_account_entry_before_first_success_and_after_failure(self):
        self.assertTrue(self.backend.view['friendEntryAvailable'])
        self.fail_refresh()
        self.assertFalse(self.backend.view['socialReady'])
        self.assertTrue(self.backend.view['friendEntryAvailable'])
        self.assertIn('node timeout', self.backend.view['socialError'])

    def test_personal_credential_rejection_prompts_once_and_opens_node_replacement(self):
        class MessageBox:
            def __init__(self, *args):
                self.buttons = []
                self.finished = Mock()
            def addButton(self, *args):
                button = object()
                self.buttons.append(button)
                return button
            def setWindowModality(self, modality):
                pass
            def show(self):
                self.finished.connect.call_args.args[0](0)
            def clickedButton(self):
                return self.buttons[0]
            def deleteLater(self):
                pass

        message_box = MessageBox()
        with patch('ui.multiplayer_controller.QMessageBox', return_value=message_box) as dialog:
            for _ in range(3):
                self.fail_refresh('A personal launcher credential is required')
        dialog.assert_called_once()
        self.assertTrue(self.backend.view['nodeCredentialRequired'])
        self.assertIn('浏览器重新登录', self.backend.view['socialError'])
        self.assertEqual(self.backend.view['page'], 'nodes')

    def test_successful_sync_clears_credential_replacement_state(self):
        with patch.object(self.backend, 'prompt_node_credential_update',
                           side_effect=lambda: setattr(self.backend, 'credential_prompted_node', self.backend.node_path)):
            self.fail_refresh('A personal launcher credential is required')
        self.assertTrue(self.backend.view['nodeCredentialRequired'])
        self.backend.apply_social_state(social_state())
        self.assertFalse(self.backend.view['nodeCredentialRequired'])

    def test_real_credential_popup_is_nonmodal_and_replacement_shows_instructions(self):
        from PySide6.QtCore import Qt
        self.fail_refresh('Personal credential expired; sign in on the node website')
        dialog = self.backend.credential_prompt_dialog
        self.assertIsNotNone(dialog)
        self.assertTrue(dialog.isVisible())
        self.assertEqual(dialog.windowModality(), Qt.NonModal)
        self.assertIn('浏览器登录', dialog.text())
        next(button for button in dialog.buttons() if button.text() == '前往重新登录').click()
        self.assertIsNone(self.backend.credential_prompt_dialog)
        self.assertEqual(self.backend.view['page'], 'nodes')
        self.assertIn('浏览器重新登录', self.backend.view['notice'])

    def test_expired_profile_retains_visible_popup_after_identity_reload(self):
        save_json(self.path, profile_data(personal_profile(expiry=1)))
        self.backend.reload_store()
        self.assertTrue(self.backend.view['nodeCredentialRequired'])
        self.assertTrue(self.backend.credential_prompt_dialog.isVisible())

    def test_expired_and_invalid_credentials_offer_recovery_but_timeout_does_not(self):
        for message in ('Personal credential expired; sign in on the node website',
                        'Invalid personal credential', 'Invalid delegated key',
                        'Delegated key mismatch'):
            with self.subTest(message=message), patch.object(self.backend, 'prompt_node_credential_update') as prompt:
                self.fail_refresh(message)
                prompt.assert_called_once()
                self.assertTrue(self.backend.view['nodeCredentialRequired'])
                self.backend.apply_social_state(social_state())
        for message in ('Node connection failed', 'Node authentication failed'):
            with self.subTest(message=message), patch.object(self.backend, 'prompt_node_credential_update') as prompt:
                self.fail_refresh(message)
                prompt.assert_not_called()
                self.assertFalse(self.backend.view['nodeCredentialRequired'])

    def test_online_room_does_not_show_login_popup_after_friend_sync_failure(self):
        self.backend.records['room'] = dict(state='online')
        with patch('ui.multiplayer_controller.QMessageBox') as popup:
            self.fail_refresh('Invalid delegated key')
            popup.assert_not_called()
        self.assertEqual(self.backend.records['room']['state'], 'online')
        self.assertIn('当前房间保持连接', self.backend.view['notice'])

    def test_remembered_device_renews_before_asking_user_to_login(self):
        save_json(self.path, profile_data(personal_profile(expiry=int(time.time()) + 3 * 86400)))
        save_json(str(self.path) + '.device.json', {'id': 'device', 'origin': 'https://community.example'})
        self.backend.reload_store(refresh_identity=True)
        with patch.object(self.backend, 'job', side_effect=lambda key, task: task.close()) as job, \
                patch('ui.multiplayer_controller.QMessageBox') as popup:
            self.fail_refresh('Invalid delegated key')
            self.assertEqual(job.call_args.args[0], 'device-refresh:' + self.backend.node_path)
            popup.assert_not_called()
        self.assertFalse(self.backend.view['nodeCredentialRequired'])
        self.assertIn('自动恢复', self.backend.view['socialError'])

    def test_active_remembered_device_is_refreshed_daily_even_with_valid_token(self):
        save_json(self.path, profile_data(personal_profile(expiry=int(time.time()) + 3 * 86400)))
        save_json(str(self.path) + '.device.json', {'id': 'device', 'origin': 'https://community.example'})
        self.backend.reload_store(refresh_identity=True)
        with patch.object(self.backend, 'job', side_effect=lambda key, task: task.close()) as job:
            self.assertTrue(self.backend.renew_device_login())
            self.assertEqual(job.call_args.args[0], 'device-refresh:' + self.backend.node_path)
            self.backend.device_refresh_successes[self.backend.node_path] = time.monotonic()
            job.reset_mock()
            self.assertFalse(self.backend.renew_device_login())
            job.assert_not_called()

    def test_verified_identity_change_clears_credential_warning(self):
        with patch.object(self.backend, 'prompt_node_credential_update'):
            self.fail_refresh('Invalid personal credential')
        save_json(self.path, profile_data(personal_profile(salt='renewed')))
        self.backend.reload_store()
        self.assertFalse(self.backend.view['nodeCredentialRequired'])

    def test_directory_unavailable_has_actionable_message_without_claiming_expiry(self):
        message = self.backend.operation_error('Room directory unavailable; retry with an online node')
        self.assertIn('刷新或切换在线节点', message)
        self.assertFalse(self.backend.view['nodeCredentialRequired'])

    def test_repeated_failures_preserve_contacts_but_never_report_them_online(self):
        self.backend.apply_social_state(social_state())
        generation = self.backend.social_generation
        for _ in range(100):
            self.fail_refresh()
        self.assertEqual(self.backend.social_generation, generation)
        self.assertTrue(self.backend.view['friendEntryAvailable'])
        self.assertEqual(self.backend.view['socialAccount'], ACCOUNT)
        self.assertEqual(self.backend.view['contacts'][0]['account'], FRIEND)
        self.assertFalse(self.backend.view['contacts'][0]['online'])
        self.assertTrue(self.backend.view['contacts'][0]['presenceStale'])
        key = 'socialstatus:' + generation + ':' + self.backend.node_path
        self.backend.finish(key, dict(path=self.backend.node_path, state=social_state()), None)
        self.assertEqual(self.backend.view['socialState'], 'online')
        self.assertEqual(self.backend.view['socialError'], '')
        self.assertEqual(self.backend.social_failures, 0)

    def test_profile_read_failure_does_not_become_an_account_switch(self):
        self.backend.apply_social_state(social_state())
        generation, identity = self.backend.social_generation, self.backend.social_identity
        with patch.object(RelayProfile, 'load', side_effect=PermissionError('sharing violation')):
            self.backend.reload_store()
        self.assertEqual(self.backend.social_generation, generation)
        self.assertEqual(self.backend.social_identity, identity)
        self.assertEqual(self.backend.view['socialAccount'], ACCOUNT)
        self.assertEqual(self.backend.view['contacts'][0]['account'], FRIEND)
        self.assertTrue(self.backend.view['friendEntryAvailable'])
        self.assertEqual(self.backend.view['socialState'], 'stale')
        self.backend.reload_store()
        self.assertEqual(self.backend.social_generation, generation)

    def test_explicit_reload_with_unreadable_profile_does_not_clear_identity(self):
        self.backend.apply_social_state(social_state())
        with patch.object(RelayProfile, 'load', side_effect=ValueError('invalid json')):
            self.backend.reload_store(refresh_identity=True)
        self.assertEqual(self.backend.view['socialAccount'], ACCOUNT)
        self.assertTrue(self.backend.view['friendEntryAvailable'])

    def test_real_identity_replacement_resets_contacts_and_ignores_old_response(self):
        self.backend.apply_social_state(social_state())
        old_key = 'socialstatus:' + self.backend.social_generation + ':' + self.backend.node_path
        save_json(self.path, profile_data(personal_profile(salt='replacement')))
        self.backend.reload_store()
        self.assertEqual(self.backend.view['contacts'], [])
        self.assertEqual(self.backend.view['socialAccount'], '')
        self.assertTrue(self.backend.view['friendEntryAvailable'])
        self.backend.finish(old_key, dict(path=self.backend.node_path, state=social_state()), None)
        self.assertEqual(self.backend.view['contacts'], [])

    def test_anonymous_replacement_and_node_removal_hide_personal_entry(self):
        self.backend.apply_social_state(social_state())
        profile = personal_profile()
        save_json(self.path, profile_data(RelayProfile(profile.server_host, profile.server_port,
                                                      'a' * 48, profile.server_public_key)))
        self.backend.reload_store()
        self.assertFalse(self.backend.view['friendEntryAvailable'])
        self.backend.store.data['nodes'] = []
        self.backend.reload_store()
        self.assertFalse(self.backend.view['friendEntryAvailable'])

    def test_expired_code_keeps_recovery_entry_and_blocks_new_connections(self):
        from hookup.social import ExpiredNodeCredential
        save_json(self.path, profile_data(personal_profile(expiry=int(time.time()) - 1)))
        with patch.object(self.backend, 'prompt_node_credential_update'):
            self.backend.reload_store()
        self.assertTrue(self.backend.view['nodeAccessExpired'])
        self.assertTrue(self.backend.view['friendEntryAvailable'])
        self.assertFalse(self.backend.view['socialReady'])
        with self.assertRaises(ExpiredNodeCredential):
            self.backend.require_available_node()

    def test_malformed_status_marks_presence_unknown_and_finishes_loading(self):
        self.backend.apply_social_state(social_state())
        self.backend.patch(socialLoading=True)
        key = 'socialstatus:' + self.backend.social_generation + ':' + self.backend.node_path
        self.backend.finish(key, dict(path=self.backend.node_path, state={}), None)
        self.assertFalse(self.backend.view['socialLoading'])
        self.assertEqual(self.backend.view['socialState'], 'stale')
        self.assertFalse(self.backend.view['contacts'][0]['online'])


if __name__ == '__main__':
    unittest.main()
