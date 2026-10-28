"""Friends survive service failures; only verified identity changes reset them."""
import base64
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

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

    def test_personal_account_entry_before_first_success_and_after_failure(self):
        self.assertTrue(self.backend.view['friendEntryAvailable'])
        self.fail_refresh()
        self.assertFalse(self.backend.view['socialReady'])
        self.assertTrue(self.backend.view['friendEntryAvailable'])
        self.assertIn('node timeout', self.backend.view['socialError'])

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
