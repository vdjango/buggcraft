"""Public Microsoft login, cancellation, loopback validation and credential renewal."""
import base64
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch, Mock
from urllib.error import HTTPError
from urllib.request import urlopen

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/buggcraft'))
from PySide6.QtWidgets import QApplication, QDialog
from PySide6.QtTest import QTest
from core.auth.microsoft import Authenticator, JWTDecoder, MicrosoftOnlineUser
from core.auth.microsoft_oauth import (MicrosoftAuthenticator, AsyncAuthServer, LoginError,
                                       LoginCancelled, AUTHORITY)
from ui.dialog.LoginDialog import LoginWaitDialog


def token(expires):
    payload = base64.urlsafe_b64encode(json.dumps({'exp': expires}).encode()).rstrip(b'=').decode()
    return f'e30.{payload}.test'


class MicrosoftAuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.auth = MicrosoftAuthenticator()
        self.success, self.errors = [], []
        self.auth.signals.success.connect(lambda name, data: self.success.append((name, data)))
        self.auth.signals.failure.connect(self.errors.append)

    def tearDown(self):
        self.auth.cancel_authentication()

    def chain(self):
        return [
            (200, {'Token': 'xbox-test', 'DisplayClaims': {'xui': [{'uhs': 'hash-test'}]}}),
            (200, {'Token': 'xsts-test'}),
            (200, {'access_token': token(time.time() + 3600)}),
        ]

    def test_device_login_pending_then_success_uses_registered_public_client(self):
        device = {'user_code': 'TEST-CODE', 'device_code': 'device-test',
                  'verification_uri': 'https://www.microsoft.com/link', 'expires_in': 900, 'interval': 1}
        responses = [(200, device), (400, {'error': 'authorization_pending'}),
                     (200, {'access_token': 'ms-test', 'refresh_token': 'refresh-new'})] + self.chain()
        with patch('core.auth.microsoft_oauth.minecraft_httpx.post', side_effect=responses) as post, \
             patch('core.auth.microsoft_oauth.minecraft_httpx.get', return_value=(200, {'name': 'OwnedPlayer', 'id': 'a' * 32})), \
             patch.object(self.auth._cancel, 'wait', return_value=False), \
             patch('core.auth.microsoft_oauth.webbrowser.open', return_value=True):
            self.auth._device_login()
        self.assertEqual(self.success[0][0], 'OwnedPlayer')
        self.assertEqual(self.success[0][1]['type'], 'online')
        self.assertEqual(self.success[0][1]['refresh_token'], 'refresh-new')
        for call in post.call_args_list:
            self.assertNotIn('client_secret', call.args[1])
        self.assertEqual(post.call_args_list[0].kwargs['headers']['Content-Type'], 'application/x-www-form-urlencoded')
        self.assertEqual(post.call_args_list[3].kwargs['headers']['Content-Type'], 'application/json')

    def test_device_slow_down_increases_poll_interval(self):
        device = {'user_code': 'TEST-CODE', 'device_code': 'device-test',
                  'verification_uri': 'https://microsoft.com/devicelogin', 'expires_in': 30, 'interval': 1}
        with patch('core.auth.microsoft_oauth.minecraft_httpx.post', side_effect=[
            (200, device), (400, {'error': 'slow_down'}), (400, {'error': 'authorization_declined'})]), \
             patch.object(self.auth._cancel, 'wait', return_value=False) as wait, \
             patch('core.auth.microsoft_oauth.webbrowser.open', return_value=True):
            with self.assertRaisesRegex(LoginError, '取消'):
                self.auth._device_login()
        self.assertEqual([call.args[0] for call in wait.call_args_list], [1, 6])

    def test_cancel_pending_device_poll_sends_no_token_request(self):
        device = {'user_code': 'TEST-CODE', 'device_code': 'device-test',
                  'verification_uri': 'https://microsoft.com/devicelogin', 'expires_in': 30}
        with patch('core.auth.microsoft_oauth.minecraft_httpx.post', return_value=(200, device)) as post, \
             patch.object(self.auth._cancel, 'wait', return_value=True), \
             patch('core.auth.microsoft_oauth.webbrowser.open', return_value=True):
            with self.assertRaises(LoginCancelled):
                self.auth._device_login()
        self.assertEqual(post.call_count, 1)

    def test_device_flow_rejects_untrusted_verification_address(self):
        for uri in ('http://microsoft.com/login', 'https://microsoft.com.evil.invalid/login'):
            with self.subTest(uri=uri), patch('core.auth.microsoft_oauth.minecraft_httpx.post', return_value=(200, {
                'user_code': 'TEST', 'device_code': 'test', 'verification_uri': uri})), \
                 patch('core.auth.microsoft_oauth.webbrowser.open') as browser:
                with self.assertRaises(LoginError):
                    self.auth._device_login()
                browser.assert_not_called()

    def test_refresh_rotates_refresh_token_and_rechecks_real_game_profile(self):
        self.auth.refresh_token = 'refresh-old'
        with patch('core.auth.microsoft_oauth.minecraft_httpx.post', side_effect=[
            (200, {'access_token': 'ms-new', 'refresh_token': 'refresh-new'})] + self.chain()) as post, \
             patch('core.auth.microsoft_oauth.minecraft_httpx.get', return_value=(200, {'name': 'OwnedPlayer', 'id': 'a' * 32})):
            self.auth._refresh_login()
        self.assertEqual(post.call_args_list[0].args[0], AUTHORITY + 'token')
        self.assertEqual(post.call_args_list[0].args[1]['refresh_token'], 'refresh-old')
        self.assertEqual(self.success[0][1]['refresh_token'], 'refresh-new')

    def test_empty_entitlement_list_does_not_reject_valid_java_profile(self):
        # Java profile is authoritative; purchase, bundles and subscription grants differ.
        self.auth.minecraft_token = 'game-test'
        with patch('core.auth.microsoft_oauth.minecraft_httpx.get', return_value=(200, {'name': 'OwnedPlayer', 'id': 'a' * 32})) as get:
            self.auth.get_minecraft_profile()
        self.assertTrue(self.success)
        self.assertTrue(get.call_args.args[0].endswith('/minecraft/profile'))

    def test_missing_java_profile_is_not_reported_as_success(self):
        self.auth.minecraft_token = 'game-test'
        with patch('core.auth.microsoft_oauth.minecraft_httpx.get', return_value=(404, {})):
            with self.assertRaisesRegex(LoginError, 'Java'):
                self.auth.get_minecraft_profile()
        self.assertEqual(self.success, [])

    def test_skin_download_failure_keeps_successful_authentication(self):
        self.auth.minecraft_token = 'game-test'
        self.auth.skins_cache_path = 'unused-cache'
        with patch('core.auth.microsoft_oauth.minecraft_httpx.get', return_value=(200, {
            'name': 'OwnedPlayer', 'id': 'a' * 32, 'skins': [{'url': 'https://textures.minecraft.net/test'}]})), \
             patch('core.auth.microsoft_oauth.process_skin_info', side_effect=OSError('offline')):
            self.auth.get_minecraft_profile()
        self.assertIsNone(self.success[0][1]['skin'])

    def test_old_worker_cannot_publish_after_retry(self):
        self.auth._local.attempt = self.auth._attempt
        self.auth._new_attempt()
        with self.assertRaises(LoginCancelled):
            self.auth._request('POST', AUTHORITY + 'token', {})
        self.assertEqual(self.success, [])

    def test_authorization_code_is_consumed_once(self):
        with patch.object(self.auth, '_spawn') as spawn:
            self.auth.handle_auth_code('one-time-test')
            self.auth.handle_auth_code('one-time-test')
        spawn.assert_called_once()

    def test_public_browser_request_uses_state_pkce_and_no_secret(self):
        from urllib.parse import parse_qs, urlparse
        with patch.object(self.auth.auth_server, 'start', return_value=True) as start, \
             patch('core.auth.microsoft_oauth.webbrowser.open'):
            self.auth.start_browser_login()
        params = parse_qs(urlparse(self.auth.authorization_url).query)
        self.assertEqual(params['state'][0], start.call_args.args[0])
        self.assertEqual(params['code_challenge_method'], ['S256'])
        self.assertNotIn('client_secret', params)

    def test_errors_do_not_echo_tokens_or_account_data(self):
        for status, data in ((400, {'error': 'invalid_client', 'access_token': 'SECRET'}),
                             (401, {'error': 'other', 'refresh_token': 'SECRET'}),
                             (403, 'raw-server-content-SECRET')):
            self.assertNotIn('SECRET', str(self.auth._error('test', status, data)))

    def test_xbox_profile_and_child_account_errors_are_actionable(self):
        self.assertIn('Xbox 档案', str(self.auth._error('test', 401, {'XErr': 2148916233})))
        self.assertIn('家庭', str(self.auth._error('test', 401, {'XErr': 2148916238})))

    def test_jwt_decoder_never_reuses_previous_tokens_expiry(self):
        decoder = JWTDecoder(token(time.time() + 3600))
        self.assertFalse(decoder.is_expired())
        decoder.token = token(time.time() - 3600)
        self.assertTrue(decoder.is_expired())
        decoder.token = 'invalid'
        self.assertIsNone(decoder.get_expiration())

    def test_online_validity_accepts_persisted_expiry_dictionary(self):
        user = MicrosoftOnlineUser()
        user.token = token(time.time() + 3600)
        user.expires_at = {'timestamp': time.time() + 3600}
        self.assertTrue(user.is_token_valid())

    def test_cache_retains_refresh_token_when_game_token_expires(self):
        manager = Authenticator()
        manager.online.uuid, manager.online.username = 'a' * 32, 'OwnedPlayer'
        manager.online.token, manager.online.refresh_token = token(time.time() - 60), 'refresh-test'
        with tempfile.TemporaryDirectory() as directory:
            self.assertTrue(manager.save(directory))
            restored = Authenticator()
            with patch.object(restored, 'refresh_login') as refresh:
                self.assertTrue(restored.load(directory))
            refresh.assert_called_once()
            self.assertEqual(restored.online.refresh_token, 'refresh-test')
            self.assertTrue((Path(directory) / 'auth_credentials.json').is_file())

    def test_refresh_supports_credentials_issued_by_previous_live_endpoint(self):
        self.auth.refresh_token = 'legacy-refresh-test'
        with patch('core.auth.microsoft_oauth.minecraft_httpx.post', side_effect=[
            (400, {'error': 'invalid_grant'}),
            (200, {'access_token': 'ms-new', 'refresh_token': 'refresh-new'})] + self.chain()) as post, \
             patch('core.auth.microsoft_oauth.minecraft_httpx.get', return_value=(200, {'name': 'OwnedPlayer', 'id': 'a' * 32})):
            self.auth._refresh_login()
        self.assertEqual(post.call_args_list[1].args[0], 'https://login.live.com/oauth20_token.srf')
        self.assertTrue(self.success)

    def test_only_refresh_token_cache_can_restore_account(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / 'auth_credentials.json').write_text(json.dumps({
                'online': {'refresh_token': 'refresh-test'}, 'offline': {},
            }), encoding='utf8')
            manager = Authenticator()
            with patch.object(manager, 'refresh_login') as refresh:
                self.assertTrue(manager.load(directory))
            refresh.assert_called_once()
            self.assertEqual(manager.current_mode, 'online')
            self.assertEqual(manager.online.refresh_token, 'refresh-test')

    def test_refresh_manager_updates_account_before_success_observers_run(self):
        manager = Authenticator()
        seen = []
        manager.signals.success.connect(lambda name, data: seen.append(manager.online.token))
        manager._accept_refreshed_login('OwnedPlayer', {
            'uuid': 'a' * 32, 'token': 'new-game-token', 'refresh_token': 'new-refresh', 'expires_at': {},
        })
        self.assertEqual(seen, ['new-game-token'])
        self.assertEqual(manager.online.refresh_token, 'new-refresh')

    def test_cache_write_failure_preserves_previous_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'auth_credentials.json'
            previous = json.dumps({'online': {'refresh_token': 'existing-refresh'}})
            path.write_text(previous, encoding='utf8')
            manager = Authenticator()
            with patch('core.auth.microsoft.os.replace', side_effect=PermissionError('locked')), \
                 patch('traceback.print_exc'):
                self.assertFalse(manager.save(directory))
            self.assertEqual(path.read_text(encoding='utf8'), previous)
            self.assertEqual(list(Path(directory).glob('*.tmp')), [])


class LoopbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.server = AsyncAuthServer(port=0, timeout=2)
        self.assertTrue(self.server.start('expected-state'))
        self.base = f'http://127.0.0.1:{self.server.port}'

    def tearDown(self):
        self.server.stop()

    def test_real_http_callback_rejects_wrong_state_and_similar_path(self):
        for path, status in (('/auth_callback?code=test&state=bad', 400),
                             ('/auth_callback_extra?code=test&state=expected-state', 404)):
            with self.assertRaises(HTTPError) as caught:
                urlopen(self.base + path, timeout=2)
            self.assertEqual(caught.exception.code, status)
        self.assertIsNone(self.server.server.auth_code)

    def test_callback_delivered_once_and_port_can_be_reused(self):
        received = []
        self.server.code_received.connect(received.append)
        with urlopen(self.base + '/auth_callback?code=test&state=expected-state', timeout=2) as response:
            self.assertEqual(response.status, 200)
            self.assertIn('no-store', response.headers['Cache-Control'])
        self.server.check_timeout()
        self.server.check_timeout()
        self.assertEqual(received, ['test'])
        self.assertTrue(self.server.start('new-state'))
        self.assertIsNone(self.server.auth_code)

    def test_timeout_emits_signal_and_closes_listener(self):
        expired = []
        self.server.signal_timeout.connect(lambda: expired.append(True))
        self.server.start_time -= 3
        self.server.check_timeout()
        self.assertEqual(expired, [True])
        self.assertIsNone(self.server.server)

    def test_provider_denial_is_handled_without_raw_error_leak(self):
        errors = []
        self.server.error_occurred.connect(errors.append)
        with urlopen(self.base + '/auth_callback?error=access_denied&error_description=SECRET&state=expected-state', timeout=2):
            pass
        self.server.check_timeout()
        self.assertEqual(len(errors), 1)
        self.assertNotIn('SECRET', errors[0])


class LoginDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.dialog = LoginWaitDialog(str(ROOT / 'resources'), self.directory.name)

    def tearDown(self):
        self.dialog.auth.cancel_authentication()
        self.dialog.close()
        self.directory.cleanup()

    def test_success_closes_as_accepted_without_cancel_signal(self):
        cancelled = []
        self.dialog.cancel_signal.connect(lambda: cancelled.append(True))
        self.dialog.auth.signals.success.emit('OwnedPlayer', {'type': 'online'})
        self.assertEqual(self.dialog.result(), QDialog.Accepted)
        self.assertEqual(cancelled, [])

    def test_retry_does_not_duplicate_progress_or_success_connections(self):
        with patch.object(self.dialog.auth, 'start_login') as start:
            self.dialog.start_login_process()
            self.app.processEvents()
            self.dialog.reopen_browser()
            self.app.processEvents()
        self.assertEqual(start.call_count, 2)
        self.dialog.auth.signals.progress.emit('latest status')
        self.assertEqual(self.dialog.info_label.text(), 'latest status')

    def test_reject_before_queued_start_prevents_background_login(self):
        with patch.object(self.dialog.auth, 'start_login') as start:
            self.dialog.start_login_process()
            self.dialog.reject()
            self.app.processEvents()
        start.assert_not_called()

    def test_device_code_copy_has_real_clipboard_behavior(self):
        self.dialog.show_device_code('TEST-CODE', 'https://microsoft.com/devicelogin')
        self.dialog.copy_code_button.click()
        self.assertEqual(self.app.clipboard().text(), 'TEST-CODE')


if __name__ == '__main__':
    unittest.main()
