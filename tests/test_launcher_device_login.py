import asyncio
import base64
import json
from io import BytesIO
from pathlib import Path
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from hookup.device_login import protect_data
from hookup.nodes import save_json
from hookup.profiles import RelayProfile


class LauncherDeviceCredentialTests(unittest.TestCase):
    def test_topology_public_token_recovers_matching_device_key_for_friends(self):
        from hookup import device_login, social

        values = {}
        keyring = types.SimpleNamespace(
            get_keyring=lambda: types.SimpleNamespace(priority=1),
            set_password=lambda service, name, value: values.__setitem__((service, name), value),
            get_password=lambda service, name: values.get((service, name)),
        )
        with patch.dict(sys.modules, {'keyring': keyring}), tempfile.TemporaryDirectory() as folder:
            for account in ('first-account', 'second-account'):
                key = ec.generate_private_key(ec.SECP256R1())
                grant = {'p': 'buggcraft-launcher-device-v1', 'i': 'issuer-id',
                         'r': account + '-device', 'd': device_login.public_jwk(key)}
                payload = {'g': grant, 'a': account, 'e': int(time.time()) + 3600}
                encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip('=')
                public_token = 'acct1.' + encoded + '.signature'
                device_login.save_private_key(grant['r'], key)
                path = Path(folder) / 'node.json'
                # Native topology only returns the public part, including after switching accounts.
                save_json(path, {'server_host': 'node.example', 'server_port': 3333,
                    'server_public_key': 'ssh-ed25519 AAAA', 'token': public_token})
                profile = RelayProfile.load(path)
                self.assertEqual(profile.token, public_token + '~' + device_login._private_scalar(key))
                self.assertEqual(social.credential(profile)[0]['a'], account)
                self.assertNotIn(device_login._private_scalar(key), path.read_text(encoding='utf-8'))

                wrong_key = ec.generate_private_key(ec.SECP256R1())
                device_login.save_private_key(grant['r'], wrong_key)
                with self.assertRaisesRegex(ValueError, '登录密钥不可用'):
                    RelayProfile.load(path)

    def test_device_token_is_stored_in_system_vault_reference(self):
        values = {}
        keyring = types.SimpleNamespace(
            get_keyring=lambda: types.SimpleNamespace(priority=1),
            set_password=lambda service, name, value: values.__setitem__((service, name), value),
            get_password=lambda service, name: values.get((service, name)),
        )
        grant = {'p': 'buggcraft-launcher-device-v1', 'i': 'issuer-id', 'r': 'device-id'}
        encoded = base64.urlsafe_b64encode(json.dumps({'g': grant}).encode()).decode().rstrip('=')
        token = 'acct1.' + encoded + '.signature'
        profile = {'server_host': 'node.example', 'server_port': 22, 'token': token,
                   'server_public_key': 'ssh-ed25519 AAAA'}

        with patch.dict(sys.modules, {'keyring': keyring}), tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'node.json'
            save_json(path, profile)
            stored = path.read_text(encoding='utf-8')
            self.assertNotIn(token, stored)
            self.assertIn('vault1:token:issuer-id:device-id', stored)
            self.assertEqual(RelayProfile.load(path).token, token)

    def test_node_addresses_require_https_and_allow_domains_or_ips(self):
        from hookup.device_login import validate_origin

        self.assertEqual(validate_origin('node.example'), 'https://node.example')
        self.assertEqual(validate_origin('https://203.0.113.10/'), 'https://203.0.113.10')
        for value in ('http://node.example', 'https://user@node.example', 'https://node.example/path',
                      'https://node.example:70000', 'https://node.example\\@evil.example'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_origin(value)

    def test_browser_approval_handshake_signs_the_server_nonce(self):
        from hookup import device_login

        replies = []
        calls = []

        def request(path, body, origin):
            calls.append((path, body, origin))
            return replies.pop(0)

        identifier = 'a' * 32
        start = {'id': identifier, 'nonce': 'server-challenge', 'expires_in': 600,
                 'verification_uri': 'https://node.example/account/access?launcher=' + identifier}
        approved = {'status': 'approved', 'profile': {'server_host': 'node.example'}}
        replies.extend((start, approved))
        with patch.object(device_login, '_keyring'), \
             patch.object(device_login, 'get_status') as status, \
             patch.object(device_login, 'request', side_effect=request):
            result, private_key = asyncio.run(device_login.begin('desktop', True, 'node.example'))
            response = asyncio.run(device_login.poll(result, private_key))

        self.assertEqual(response, approved)
        status.assert_not_called()
        self.assertEqual(calls[0][0], '/api/launcher/start')
        self.assertEqual(calls[0][2], 'https://node.example')
        self.assertEqual(calls[0][1]['name'], 'desktop')
        self.assertTrue(calls[0][1]['remember'])
        path, body, origin = calls[1]
        self.assertEqual((path, origin), ('/api/launcher/poll', 'https://node.example'))
        signature = base64.urlsafe_b64decode(body['signature'] + '=' * (-len(body['signature']) % 4))
        signed = {'p': 'buggcraft-launcher-poll-v1', 'id': identifier, 'nonce': start['nonce']}
        private_key.public_key().verify(encode_dss_signature(
            int.from_bytes(signature[:32], 'big'), int.from_bytes(signature[32:], 'big')),
            device_login.canonical(signed), ec.ECDSA(hashes.SHA256()))

    def test_device_api_rejects_cross_origin_redirects(self):
        from urllib.error import HTTPError
        from urllib.request import Request
        from hookup.device_login import _RejectRedirects

        handler = _RejectRedirects()
        request = Request('https://node.example/api/launcher/poll', data=b'{}')
        with self.assertRaises(HTTPError):
            handler.redirect_request(request, None, 307, 'Temporary Redirect', {},
                                     'https://attacker.example/collect')

    def test_device_api_rejects_requests_to_an_unselected_origin(self):
        from urllib.request import Request
        from hookup.device_login import _open

        with patch('urllib.request.build_opener') as build_opener:
            with self.assertRaises(ValueError):
                _open(Request('https://attacker.example/api/launcher/poll', data=b'{}'),
                      'https://node.example', timeout=1)
            build_opener.assert_not_called()

    def test_status_and_every_device_post_use_launcher_identity(self):
        from hookup import device_login
        from utils.http_identity import USER_AGENT

        def response(call, origin, timeout):
            self.assertEqual(origin, 'https://node.example')
            self.assertEqual(call.get_header('User-agent'), USER_AGENT)
            self.assertEqual(call.get_header('Accept'), 'application/json')
            self.assertEqual(call.get_header('Cache-control'), 'no-store')
            if call.get_method() == 'POST':
                self.assertEqual(call.get_header('Content-type'), 'application/json')
                self.assertEqual(json.loads(call.data), {'id': 'device-id'})
            return BytesIO(b'{"status":"ok"}')

        with patch.object(device_login, '_open', side_effect=response) as opened:
            self.assertEqual(device_login.get_status('node.example'), {'status': 'ok'})
            for path in ('start', 'poll', 'challenge', 'refresh'):
                self.assertEqual(device_login.request('/api/launcher/' + path,
                    {'id': 'device-id'}, 'node.example'), {'status': 'ok'})
        self.assertEqual(opened.call_count, 5)

    def test_proxy_and_node_errors_are_readable_without_html(self):
        from urllib.error import HTTPError
        from hookup import device_login

        cases = (
            (b'{"cloudflare_error":true,"error_code":1010}', '节点代理拒绝'),
            (b'error code: 1010', '节点代理拒绝'),
            (b'<html>cf-error-details</html>', '节点代理拒绝'),
            ('{"error":"设备授权已失效"}'.encode(), '设备授权已失效'),
            ('Origin rejected'.encode(), 'Origin rejected'),
            (b'<html>Internal error</html>', '节点暂时无法处理'),
            (b'{"error":{"detail":"invalid"}}', '节点暂时无法处理'),
        )
        for body, message in cases:
            with self.subTest(body=body):
                error = HTTPError('https://node.example/api/status', 403, 'Forbidden',
                                  {'Server': 'cloudflare'}, BytesIO(body))
                with patch.object(device_login, '_open', side_effect=error):
                    with self.assertRaises(ValueError) as caught:
                        device_login.get_status('node.example')
                self.assertIn(message, str(caught.exception))
                self.assertIn('HTTP 403', str(caught.exception))
                self.assertNotIn('<html>', str(caught.exception))

    def test_status_and_post_reject_invalid_or_oversized_responses(self):
        from hookup import device_login

        for body in (b'<html>proxy challenge</html>', b'[]', b'\xff', b' ' * 65537):
            for operation in ('status', 'post'):
                with self.subTest(body=body[:30], operation=operation):
                    with patch.object(device_login, '_open', return_value=BytesIO(body)):
                        with self.assertRaises(ValueError):
                            if operation == 'status':
                                device_login.get_status('node.example')
                            else:
                                device_login.request('/api/launcher/start', {}, 'node.example')


if __name__ == '__main__':
    unittest.main()
