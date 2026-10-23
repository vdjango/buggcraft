"""Exercise gateway HTTP routes and a local streaming upstream."""
import asyncio
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer


spec = importlib.util.spec_from_file_location('content_gateway', Path(__file__).resolve().parents[1] / 'packaging/content_gateway.py')
gateway = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gateway)


class GatewayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.calls = []
        async def fetch(method, route, params, body):
            self.calls.append((method, route, params, body))
            return {'data': [{'id': 10, 'gameId': 432}]}
        self.client = TestClient(TestServer(gateway.create_app('server-secret', fetch)))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)

    async def test_minecraft_search_is_cached_and_never_returns_or_requires_the_key(self):
        route = '/v1/mods/search?gameId=432&classId=6&searchFilter=test&pageSize=20'
        for _ in range(2):
            async with self.client.get(route) as response:
                self.assertEqual(response.status, 200)
                text = await response.text()
                self.assertNotIn('server-secret', text)
                self.assertEqual((await response.json())['data'][0]['id'], 10)
        self.assertEqual(len(self.calls), 1)

    async def test_arbitrary_routes_hosts_other_games_and_oversized_queries_are_rejected(self):
        for route in ['/v1/users', '/v1/mods/search?gameId=1&classId=6',
                      '/v1/mods/search?gameId=432&classId=6&url=https://evil.org',
                      '/v1/mods/10/files?pageSize=500', '/v1/mods/10/files?gameVersion='+('x'*33)]:
            async with self.client.get(route) as response:
                self.assertIn(response.status, (400, 404))
        self.assertEqual(self.calls, [])

    async def test_batch_resolution_has_strict_id_and_size_bounds(self):
        async with self.client.post('/v1/mods', json={'modIds':[10, 10, 11]}) as response:
            self.assertEqual(response.status, 200)
        self.assertEqual(self.calls[0][3], {'modIds':[10,11]})
        for body in [{'modIds':list(range(1,52))}, {'modIds':[True]}, {'modIds':['10']}, {'modIds':[10],'url':'evil'}]:
            async with self.client.post('/v1/mods', json=body) as response:
                self.assertEqual(response.status, 400)
        self.assertEqual(len(self.calls), 1)

    async def test_description_is_cached_only_after_validating_minecraft_parent(self):
        calls = []
        async def fetch(method, route, params, body):
            calls.append(route)
            if route.endswith('/description'):
                return {'data': '<p>Minecraft project description</p>'}
            return {'data': {'id': 10, 'gameId': 432 if route == '/mods/10' else 1, 'classId': 6}}
        async with TestClient(TestServer(gateway.create_app('server-secret', fetch))) as client:
            for _ in range(2):
                async with client.get('/v1/mods/10/description') as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual((await response.json())['data'], '<p>Minecraft project description</p>')
            self.assertEqual(calls, ['/mods/10', '/mods/10/description'])
            async with client.get('/v1/mods/11/description') as response:
                self.assertEqual(response.status, 404)
            self.assertNotIn('/mods/11/description', calls)

    async def test_rate_limit_applies_to_cached_results(self):
        for index in range(121):
            async with self.client.get('/v1/mods/10') as response:
                self.assertEqual(response.status, 200 if index < 120 else 429)
        self.assertEqual(len(self.calls), 1)

    async def test_upstream_errors_do_not_leak_secrets(self):
        async def broken(*args):
            raise RuntimeError('server-secret')
        async with TestClient(TestServer(gateway.create_app('server-secret', broken))) as client:
            async with client.get('/v1/mods/10') as response:
                self.assertEqual(response.status, 502)
                self.assertNotIn('server-secret', await response.text())

    async def test_upstream_stream_is_fully_read_and_private_key_stays_upstream(self):
        received = []
        async def upstream(request):
            received.append(request.headers.get('x-api-key'))
            response = web.StreamResponse(headers={'Content-Type': 'application/json'})
            await response.prepare(request)
            await response.write(b'{"data":')
            await asyncio.sleep(0.01)
            await response.write(b'{"id":10,"gameId":432}}')
            await response.write_eof()
            return response
        app = web.Application()
        app.router.add_get('/mods/10', upstream)
        async with TestServer(app) as server:
            with patch.object(gateway, 'API', str(server.make_url('')).rstrip('/')):
                async with TestClient(TestServer(gateway.create_app('server-secret'))) as client:
                    async with client.get('/v1/mods/10') as response:
                        self.assertEqual(response.status, 200)
                        self.assertEqual(await response.json(), {'data': {'id': 10, 'gameId': 432}})
                        self.assertNotIn('x-api-key', response.headers)
        self.assertEqual(received, ['server-secret'])

    async def test_authenticated_download_stream_and_author_restrictions(self):
        data, received, redirect = b'published-mod-content', [], []
        project = {'id': 10, 'gameId': 432, 'classId': 6, 'allowModDistribution': True}
        file = {'id': 20, 'modId': 10, 'gameId': 432, 'fileLength': len(data),
                'downloadUrl': 'https://edge.forgecdn.net/files/0/20/test.jar'}
        async def fetch(method, route, params, body):
            return {'data': file if route.endswith('/files/20') else project}
        async def cdn(request):
            received.append(request.headers.get('x-api-key'))
            if redirect:
                return web.Response(status=302, headers={'Location': redirect[0]})
            return web.Response(body=data)
        app = web.Application()
        app.router.add_get('/test.jar', cdn)
        original = gateway.Gateway.stream_file
        async with TestServer(app) as server:
            async def local_stream(instance, request, url, size):
                self.assertEqual(url, file['downloadUrl'])
                return await original(instance, request, str(server.make_url('/test.jar')), size)
            with patch.object(gateway.Gateway, 'stream_file', local_stream):
                async with TestClient(TestServer(gateway.create_app('server-secret', fetch))) as client:
                    async with client.get('/v1/download/10/20') as response:
                        self.assertEqual(response.status, 200)
                        self.assertEqual(await response.read(), data)
                        self.assertNotIn('x-api-key', response.headers)
                    redirect.append('https://another.example/must-not-receive-key')
                    async with client.get('/v1/download/10/20') as response:
                        self.assertEqual(response.status, 502)
            for change in [{'allowModDistribution': False}, {'classId': 1}]:
                project.update(change)
                async with TestClient(TestServer(gateway.create_app('server-secret', fetch))) as client:
                    async with client.get('/v1/download/10/20') as response:
                        self.assertEqual(response.status, 404)
        self.assertEqual(received, ['server-secret', 'server-secret'])

    def test_cdn_redirect_validation_rejects_downgrade_credentials_and_other_hosts(self):
        self.assertTrue(gateway.trusted_cdn('https://mediafilez.forgecdn.net/files/test.jar'))
        for url in ['http://edge.forgecdn.net/test', 'https://edge.forgecdn.net:8080/test',
                    'https://forgecdn.net.evil.org/test', 'https://user@edge.forgecdn.net/test',
                    'https://edge.forgecdn.net:invalid/test']:
            with self.subTest(url=url):
                self.assertFalse(gateway.trusted_cdn(url))
