"""HTTP permission boundaries and persistent operator controls."""
import json
from pathlib import Path
import secrets
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / '.test-tools'), str(ROOT / 'minecraft-tunnel/src')]
import asyncssh
from aiohttp import CookieJar
from aiohttp.test_utils import TestClient, TestServer, make_mocked_request
from tunnel.relay import RelayServer
from tunnel.federation import Federation
from tunnel.portal import Portal, password_hash


class PortalTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / 'node-state.json'
        self.admin_password = secrets.token_urlsafe(20)
        self.player_password = secrets.token_urlsafe(20)
        self.path.write_text(json.dumps({
            'admin_user': 'admin', 'admin_hash': password_hash(self.admin_password),
            'access_hash': password_hash(self.player_password), 'public_join': False,
        }), encoding='utf-8')
        key = asyncssh.generate_private_key('ssh-ed25519')
        self.relay = RelayServer('127.0.0.1', 0, host_key=key, token=secrets.token_urlsafe(48))
        self.fed = Federation(key, {'server_host': '127.0.0.1', 'server_port': 3333,
                              'token': self.relay.token, 'server_public_key': key.export_public_key().decode()},
                              network_key=secrets.token_urlsafe(48))
        self.fed.relay = self.relay
        self.fed.publish()
        self.portal = Portal(self.relay, self.fed, self.path)
        self.client = TestClient(TestServer(self.portal.app), cookie_jar=CookieJar(unsafe=True))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.directory.cleanup()

    async def login(self):
        response = await self.client.post('/api/login', json={
            'username': 'admin', 'password': self.admin_password})
        self.assertEqual(response.status, 200)
        self.assertTrue(response.cookies['node_session']['httponly'])
        self.assertEqual(response.cookies['node_session']['samesite'], 'Strict')
        return (await response.json())['csrf']

    async def test_public_page_and_status_do_not_leak_credentials(self):
        response = await self.client.get('/')
        self.assertEqual(response.status, 200)
        self.assertIn("frame-ancestors 'none'", response.headers['Content-Security-Policy'])
        response = await self.client.get('/api/status')
        data = await response.text()
        for secret in (self.relay.token, self.fed.network_key, self.admin_password, self.player_password):
            self.assertNotIn(secret, data)
        for path in ('/api/admin', '/api/federation/invite'):
            self.assertEqual((await self.client.get(path)).status, 401)
        self.assertEqual((await self.client.post('/api/profile', json={})).status, 401)

    async def test_non_object_json_is_rejected_without_server_error(self):
        for path in ('/api/login', '/api/settings', '/api/profile', '/api/federation/join'):
            self.assertEqual((await self.client.post(path, json=['unexpected'])).status, 400)

    async def test_login_csrf_origin_logout_and_persistent_settings(self):
        self.assertEqual((await self.client.post('/api/login', json={
            'username': 'admin', 'password': self.player_password})).status, 401)
        csrf = await self.login()
        settings = {'name': '<script>plain text</script>', 'public_join': True, 'draining': True}
        self.assertEqual((await self.client.post('/api/settings', json=settings)).status, 403)
        headers = {'X-CSRF-Token': csrf, 'Origin': 'https://hostile.example'}
        self.assertEqual((await self.client.post('/api/settings', json=settings, headers=headers)).status, 403)
        headers.pop('Origin')
        self.assertEqual((await self.client.post('/api/settings', json=settings, headers=headers)).status, 200)
        saved = json.loads(self.path.read_text(encoding='utf-8'))
        self.assertEqual(saved['name'], settings['name'])
        self.assertTrue(saved['draining'])
        self.assertTrue(self.relay.draining)
        self.assertEqual(saved['network_key'], self.fed.network_key)
        self.assertEqual((await self.client.post('/api/logout', json={}, headers=headers)).status, 200)
        self.assertEqual((await self.client.get('/api/admin')).status, 401)
        self.assertEqual((await self.client.post('/api/profile', json={})).status, 200)

    async def test_player_authorization_is_separate_and_throttled(self):
        response = await self.client.post('/api/profile', json={'password': self.player_password})
        self.assertEqual(response.status, 200)
        data = await response.json()
        self.assertTrue(data['code'].startswith('buggnode1-'))
        self.assertEqual(data['profile']['token'], self.relay.token)
        self.assertNotIn(self.fed.network_key, json.dumps(data))
        self.assertEqual((await self.client.get('/api/federation/invite')).status, 401)
        for _ in range(7):
            self.assertEqual((await self.client.post('/api/profile', json={'password': 'wrong'})).status, 401)
        self.assertEqual((await self.client.post('/api/profile', json={})).status, 429)

    async def test_federation_invite_join_and_block_are_admin_only(self):
        csrf = await self.login()
        headers = {'X-CSRF-Token': csrf}
        key = asyncssh.generate_private_key('ssh-ed25519')
        other = Federation(key, dict(self.fed.profile, server_port=3334,
                           server_public_key=key.export_public_key().decode()), network_key=secrets.token_urlsafe(48))
        invitation = other.invitation()
        self.assertEqual((await self.client.post('/api/federation/join', json=invitation)).status, 403)
        self.assertEqual((await self.client.post('/api/federation/join', json=invitation, headers=headers)).status, 200)
        self.assertEqual(self.fed.network_key, other.network_key)
        self.assertEqual((await self.client.get('/api/federation/invite')).status, 200)
        response = await self.client.post('/api/federation/block',
                    json={'id': other.id, 'blocked': True, 'confirmation': other.id,
                          'reason': 'Operator reviewed unexpected traffic', 'password': self.admin_password}, headers=headers)
        self.assertEqual(response.status, 200)
        self.assertIn(other.id, json.loads(self.path.read_text())['blocked'])

    async def test_remote_cleartext_authorization_is_refused(self):
        from aiohttp import web
        request = make_mocked_request('GET', '/api/admin', headers={'Host': 'node.example'},
                                      transport=type('Transport', (), {'get_extra_info':
                                          lambda _, name, default=None: ('203.0.113.8', 1234) if name == 'peername' else default})())
        async def handler(request):
            return web.Response(text='should not run')
        with self.assertRaises(web.HTTPForbidden):
            await self.portal.guard(request, handler)

    async def test_capacity_requires_admin_csrf_persists_and_restores(self):
        from tunnel.portal import Portal
        settings = dict(name='Budget node', public_join=False, draining=False,
            capacity=dict(max_rooms=7, room_capacity=6, bandwidth_mb_s=1,
                          reserve_percent=35, per_player_mb_s=.128))
        self.assertNotEqual((await self.client.post('/api/settings', json=settings)).status, 200)
        csrf = await self.login()
        self.assertEqual((await self.client.post('/api/settings', json=settings,
            headers={'X-CSRF-Token': csrf})).status, 200)
        self.assertEqual(self.relay.max_rooms, 7)
        public = await (await self.client.get('/api/status')).json()
        self.assertEqual(public['capacity']['recommended_visitors'], 4)
        self.assertEqual(public['capacity']['unit'], 'MB/s')
        self.assertEqual(public['players'], 0)
        self.assertEqual(public['game_players'], 0)
        self.relay.capacity.configure({})
        Portal(self.relay, self.fed, self.path)
        self.assertEqual(self.relay.capacity.policy, settings['capacity'])

    async def test_invalid_capacity_does_not_partially_apply_other_settings(self):
        csrf = await self.login()
        before = self.path.read_bytes()
        name = self.fed.name
        for capacity in ([], {'bandwidth_mb_s':-1}, {'room_capacity':True},
                         {'reserve_percent':0}, {'per_player_mb_s':0}):
            response = await self.client.post('/api/settings', headers={'X-CSRF-Token':csrf},
                json=dict(name='Must not save', public_join=True, draining=True, capacity=capacity))
            self.assertEqual(response.status, 400)
            self.assertEqual(self.fed.name, name)
            self.assertFalse(self.relay.draining)
            self.assertEqual(self.path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main(verbosity=2)
