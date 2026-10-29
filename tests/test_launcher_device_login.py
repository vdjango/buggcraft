import asyncio
import base64
import json
from pathlib import Path
import sys
import tempfile
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
             patch.object(device_login, 'get_status', return_value={'launcher_login': 1}), \
             patch.object(device_login, 'request', side_effect=request):
            result, private_key = asyncio.run(device_login.begin('desktop', True, 'node.example'))
            response = asyncio.run(device_login.poll(result, private_key))

        self.assertEqual(response, approved)
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


if __name__ == '__main__':
    unittest.main()
