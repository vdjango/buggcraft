"""Replacing an anonymous node credential refreshes identity without dropping rooms."""
import os
import base64
import json
import time
from types import SimpleNamespace
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/buggcraft'))
from tests.native_fixtures import ssh_public_key
from PySide6.QtWidgets import QApplication, QDialog
from hookup.nodes import node_identity, profile_data, save_json
from hookup.profiles import RelayProfile
from ui.multiplayer_controller import MultiplayerController


class NodeIdentityUpgradeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)
        cls.key = ssh_public_key()

    def setUp(self):
        work = tempfile.TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.root = Path(work.name)
        self.window = QDialog()
        self.addCleanup(self.window.close)
        self.service = Mock(endpoints={})
        with patch('ui.multiplayer_controller.TunnelService', return_value=self.service), \
                patch.object(MultiplayerController, 'refresh_network_profile'):
            self.controller = MultiplayerController(self.window, self.root / 'lobby.json')
        self.addCleanup(self.controller.close)
        self.controller.friend_timer.stop()
        self.jobs = []
        def schedule(key, coroutine):
            self.jobs.append(key)
            coroutine.close()
        patcher = patch.object(self.controller, 'job', side_effect=schedule)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.anonymous = self.profile()
        self.personal = self.profile(token='acct1.' + 'p' * 48)
        self.verified(self.anonymous)
        self.path = self.controller.node_path

    def profile(self, host='node.example', token='a' * 48, key=None):
        return RelayProfile(host, 3333, token, key or self.key)

    def verified(self, profile):
        self.controller.finish('nodecode:' + self.controller.generation, profile, None)

    def confirm(self, profile):
        self.verified(profile)
        self.assertTrue(self.controller.view['nodeUpdatePrompt'])
        self.controller.act('confirmNodeUpdate', {})

    def test_upgrade_requires_confirmation_then_refreshes_friends_on_same_path(self):
        c = self.controller
        old_generation = c.social_generation
        self.verified(self.personal)
        self.assertTrue(c.view['nodeUpdatePrompt'])
        self.assertEqual(RelayProfile.load(self.path).token, self.anonymous.token)
        with patch('hookup.social.credential', return_value=({}, None)):
            c.act('confirmNodeUpdate', {})
        self.assertEqual(c.store.data['nodes'], [self.path])
        self.assertEqual(c.node_path, self.path)
        self.assertEqual(RelayProfile.load(self.path).token, self.personal.token)
        self.assertNotEqual(c.social_generation, old_generation)
        key = next(key for key in reversed(self.jobs) if key.startswith('socialstatus:'))
        state = {'account': 'a' * 32 + '.' + 'b' * 32, 'username': 'player', 'requests': [],
                 'invitations': [], 'friends': [{'account': 'c' * 32 + '.' + 'd' * 32, 'username': 'friend', 'online': True}]}
        c.finish(key, {'path': self.path, 'state': state}, None)
        self.assertTrue(c.view['socialReady'])
        self.assertEqual(c.view['contacts'][0]['name'], 'friend')

    def test_cancel_keeps_original_credential_and_draft(self):
        self.controller.patch(nodeDraft='keep-this-draft')
        self.verified(self.personal)
        self.controller.act('cancelNodeUpdate', {})
        self.assertFalse(self.controller.view['nodeUpdatePrompt'])
        self.assertEqual(RelayProfile.load(self.path).token, self.anonymous.token)
        self.assertEqual(self.controller.view['nodeDraft'], 'keep-this-draft')

    def test_repeated_updates_keep_one_entry_and_renew_saved_token(self):
        for token in ('acct1.' + 'p' * 48, 'acct1.' + 'q' * 48):
            self.confirm(self.profile(token=token))
            self.assertEqual(self.controller.store.data['nodes'], [self.path])
            self.assertEqual(RelayProfile.load(self.path).token, token)

    def test_address_alias_and_key_comment_still_identify_same_node(self):
        alias = self.profile(host='127.0.0.1', key=self.key.strip() + ' node alias\n')
        self.assertEqual(node_identity(alias), node_identity(self.anonymous))
        self.confirm(alias)
        self.assertEqual(self.controller.store.data['nodes'], [self.path])
        self.assertEqual(RelayProfile.load(self.path).server_host, '127.0.0.1')

    def test_legacy_duplicates_merge_without_deleting_old_profile_files(self):
        other = self.root / 'old-alias.json'
        save_json(other, profile_data(self.profile(host='127.0.0.1')))
        self.controller.store.add_node(str(other))
        self.confirm(self.personal)
        self.assertEqual(self.controller.store.data['nodes'], [self.path])
        self.assertTrue(other.is_file())

    def test_changed_key_at_same_address_is_rejected_without_overwrite(self):
        other_key = ssh_public_key('other-node')
        self.verified(self.profile(key=other_key))
        self.assertIn('公钥发生变化', self.controller.view['error'])
        self.assertEqual(RelayProfile.load(self.path).server_public_key, self.key)

    def test_stale_social_status_and_errors_cannot_reset_new_identity(self):
        old = self.controller.social_generation
        self.confirm(self.personal)
        self.controller.patch(socialReady=True, socialName='new-player')
        for prefix in ('socialstatus:', 'socialop:'):
            self.controller.finish(prefix + old + ':' + self.path, None, 'old credential expired')
        self.assertTrue(self.controller.view['socialReady'])
        self.assertEqual(self.controller.view['socialName'], 'new-player')
        self.assertNotIn('old credential', self.controller.view['socialError'])

    def test_browser_login_and_account_switch_save_before_refresh_and_return_to_hall(self):
        from cryptography.hazmat.primitives.asymmetric import ec
        from hookup import device_login

        c = self.controller
        values = {}
        vault = SimpleNamespace(
            set_password=lambda service, name, value: values.__setitem__((service, name), value),
            get_password=lambda service, name: values.get((service, name)),
        )
        original_reload = c.reload_store
        def reload_saved(path, **kwargs):
            metadata = json.loads(Path(path + '.device.json').read_text(encoding='utf-8'))
            self.assertEqual(metadata['id'], current_id)
            original_reload(path, **kwargs)

        with patch.object(device_login, '_keyring', return_value=vault), \
                patch.object(c, 'reload_store', side_effect=reload_saved) as reloaded:
            for current_id in ('first-device', 'second-device'):
                old_social_generation = c.social_generation
                private = ec.generate_private_key(ec.SECP256R1())
                grant = {'p': 'buggcraft-launcher-device-v1', 'i': 'issuer', 'r': current_id,
                         'o': 'https://node.example', 'd': device_login.public_jwk(private)}
                claims = {'g': grant, 'e': int(time.time()) + 3600, 'a': current_id}
                encoded = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip('=')
                public = self.profile(token='acct1.' + encoded + '.signature~' + device_login._private_scalar(private))
                object.__setattr__(public, '_name', 'Test node')
                object.__setattr__(public, '_region', 'Test region')
                result = {'id': current_id, 'origin': 'https://node.example'}
                c.device_login = (result, private, current_id)
                c.patch(page='nodes', deviceLoginBusy=True)
                c.finish('device-login-verified:' + current_id, (public, result, private), None)
                self.assertEqual(c.view['page'], 'hall')
                self.assertEqual(c.view['deviceLoginStage'], 'complete')
                self.assertTrue(c.view['deviceManaged'])
                self.assertEqual(c.view['socialError'], '')
                self.assertNotEqual(c.social_generation, old_social_generation)
                self.assertEqual(RelayProfile.load(c.node_path).token, public.token)
                c.finish('socialstatus:' + old_social_generation + ':' + c.node_path, None, 'stale login')
                self.assertEqual(c.view['socialError'], '')
            self.assertEqual(reloaded.call_count, 2)

    def test_personal_credential_validation_error_is_visible(self):
        self.confirm(self.personal)
        self.assertFalse(self.controller.view['socialReady'])
        self.assertIn('浏览器重新登录', self.controller.view['socialError'])

    def test_credential_update_preserves_active_room_endpoint(self):
        endpoint = object()
        self.service.endpoints['existing-room'] = endpoint
        self.controller.patch(connections=[{'id': 'existing-room'}])
        self.confirm(self.personal)
        self.assertIs(self.service.endpoints['existing-room'], endpoint)
        self.service.remove.assert_not_called()
