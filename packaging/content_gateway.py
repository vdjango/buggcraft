"""Read-only Minecraft metadata gateway; API credentials stay on the server."""
import asyncio
from collections import OrderedDict
import json
import os
import re
import time
from urllib.parse import urljoin, urlsplit

from aiohttp import ClientSession, ClientTimeout, TCPConnector, web


API = 'https://api.curseforge.com/v1'
ROUTE = re.compile(r'/mods(?:/search|/files|/[1-9][0-9]{0,9}(?:/files(?:/[1-9][0-9]{0,9})?)?)?')
CLASSES = {6, 12, 6552, 4471}


def trusted_cdn(url):
    try:
        parsed = urlsplit(url or '')
        return (parsed.scheme == 'https' and not parsed.username and not parsed.password and
                (parsed.hostname or '').endswith('.forgecdn.net') and parsed.port in (None, 443))
    except ValueError:
        return False


def request_arguments(request, body):
    route = request.match_info['route']
    if not ROUTE.fullmatch(route):
        raise web.HTTPNotFound()
    if request.method == 'POST':
        field = {'/mods': 'modIds', '/mods/files': 'fileIds'}.get(route)
        if not field or request.query or not isinstance(body, dict) or set(body) != {field}:
            raise web.HTTPBadRequest()
        ids = body[field]
        if not isinstance(ids, list) or not 1 <= len(ids) <= 50 or any(type(x) is not int or not 1 <= x <= 2**31-1 for x in ids):
            raise web.HTTPBadRequest()
        return route, {}, {field: list(dict.fromkeys(ids))}
    if route in ('/mods', '/mods/files'):
        raise web.HTTPNotFound()
    params = dict(request.query)
    allowed = {'pageSize', 'index', 'gameVersion', 'modLoaderType'} if route.endswith('/files') else set()
    if route == '/mods/search':
        allowed |= {'pageSize', 'index', 'gameVersion', 'modLoaderType',
                    'gameId', 'classId', 'searchFilter', 'sortField', 'sortOrder'}
        if params.get('gameId') != '432' or params.get('classId') not in {str(x) for x in CLASSES}:
            raise web.HTTPBadRequest()
    if set(params) - allowed or len(params) != len(request.query):
        raise web.HTTPBadRequest()
    for name, value in params.items():
        if name in ('gameVersion', 'searchFilter'):
            if len(value) > (128 if name == 'searchFilter' else 32) or any(ord(x) < 32 for x in value):
                raise web.HTTPBadRequest()
        elif name == 'sortOrder':
            if value not in ('asc', 'desc'):
                raise web.HTTPBadRequest()
        elif not value.isascii() or not value.isdigit() or len(value) > 5:
            raise web.HTTPBadRequest()
    if not 1 <= int(params.get('pageSize', '20')) <= 50 or int(params.get('index', '0')) > 9950:
        raise web.HTTPBadRequest()
    return route, params, None


class Gateway:
    def __init__(self, api_key, fetch=None):
        if not api_key or '\n' in api_key or '\r' in api_key:
            raise ValueError('Set CURSEFORGE_API_KEY in the service environment')
        self.api_key = api_key
        self.cache = OrderedDict()
        self.recent = OrderedDict()
        self.semaphore = asyncio.Semaphore(8)
        self.download_semaphore = asyncio.Semaphore(2)
        self.fetch = fetch or self.upstream
        self.session = None

    async def startup(self, app):
        self.session = ClientSession(timeout=ClientTimeout(total=20),
                                     connector=TCPConnector(limit=8), trust_env=False)

    async def cleanup(self, app):
        if self.session:
            await self.session.close()

    async def upstream(self, method, route, params, body):
        async with self.session.request(method, API + route, params=params, json=body,
                headers={'x-api-key': self.api_key, 'Accept': 'application/json',
                         'User-Agent': 'Buggcraft-content-gateway/1.0'}, allow_redirects=False) as response:
            if response.status != 200:
                raise web.HTTPServiceUnavailable(text='Resource provider is unavailable')
            chunks, size = [], 0
            async for chunk in response.content.iter_chunked(65536):
                size += len(chunk)
                if size > 4 * 1024 * 1024:
                    raise web.HTTPBadGateway()
                chunks.append(chunk)
            return json.loads(b''.join(chunks))

    def rate_limit(self, request):
        # Bound both network calls and cache hits. The loopback reverse proxy
        # supplies X-Real-IP; public clients cannot connect to this listener.
        address = request.headers.get('X-Real-IP') or request.remote
        now = time.monotonic()
        start, count = self.recent.get(address, (now, 0))
        if now - start >= 60:
            start, count = now, 0
        if count >= 120:
            raise web.HTTPTooManyRequests(headers={'Retry-After': '60'})
        self.recent[address] = (start, count + 1)
        self.recent.move_to_end(address)
        while len(self.recent) > 4096:
            self.recent.popitem(last=False)

    async def handle(self, request):
        if request.method not in ('GET', 'POST'):
            raise web.HTTPMethodNotAllowed(request.method, ['GET', 'POST'])
        self.rate_limit(request)
        try:
            body = await request.json() if request.method == 'POST' else None
        except (ValueError, UnicodeError):
            raise web.HTTPBadRequest() from None
        route, params, body = request_arguments(request, body)
        payload = await self.metadata(request.method, route, params, body)
        return web.json_response(payload, headers={'Cache-Control': 'no-store'})

    async def metadata(self, method, route, params=None, body=None):
        now = time.monotonic()
        key = (method, route, json.dumps(params, sort_keys=True), json.dumps(body, sort_keys=True))
        cached = self.cache.get(key)
        if cached and now - cached[0] < 300:
            return cached[1]
        try:
            async with asyncio.timeout(25):
                async with self.semaphore:
                    # Waiters can reuse the first caller's freshly cached result.
                    cached = self.cache.get(key)
                    if cached and time.monotonic() - cached[0] < 300:
                        payload = cached[1]
                    else:
                        payload = await self.fetch(method, route, params, body)
                        data = payload.get('data') if isinstance(payload, dict) else None
                        records = data if isinstance(data, list) else [data]
                        if data is None or any(not isinstance(x, dict) or x.get('gameId') != 432 for x in records):
                            raise web.HTTPNotFound()
                        # Bound cache memory independently of the number of requests.
                        if len(json.dumps(payload).encode('utf-8')) > 1024 * 1024:
                            raise web.HTTPBadGateway()
                        self.cache[key] = (time.monotonic(), payload)
                        self.cache.move_to_end(key)
                        while len(self.cache) > 32:
                            self.cache.popitem(last=False)
        except web.HTTPException:
            raise
        except Exception:
            # Do not log response bodies, credentials, headers, or user queries.
            raise web.HTTPBadGateway(text='Resource provider is unavailable') from None
        return payload

    async def download(self, request):
        """Authenticate CDN downloads without exposing the platform's key."""
        self.rate_limit(request)
        project_id, file_id = int(request.match_info['project']), int(request.match_info['file'])
        project = (await self.metadata('GET', f'/mods/{project_id}'))['data']
        item = (await self.metadata('GET', f'/mods/{project_id}/files/{file_id}'))['data']
        if (not isinstance(project, dict) or not isinstance(item, dict) or
                project.get('id') != project_id or project.get('classId') not in CLASSES or
                project.get('allowModDistribution') is False or item.get('id') != file_id or
                item.get('modId') != project_id or item.get('isAvailable') is False or
                item.get('isEarlyAccessContent') or item.get('isServerPack')):
            raise web.HTTPNotFound()
        url, size = item.get('downloadUrl'), item.get('fileLength')
        if not trusted_cdn(url):
            raise web.HTTPNotFound()
        if type(size) is not int or not 0 < size <= 512 * 1024 * 1024:
            raise web.HTTPRequestEntityTooLarge(max_size=512 * 1024 * 1024, actual_size=size or 0)
        try:
            await asyncio.wait_for(self.download_semaphore.acquire(), timeout=5)
        except TimeoutError:
            raise web.HTTPTooManyRequests(headers={'Retry-After': '10'}) from None
        try:
            return await self.stream_file(request, url, size)
        finally:
            self.download_semaphore.release()

    async def stream_file(self, request, url, size):
        for _ in range(4):
            async with self.session.get(url, headers={'x-api-key': self.api_key},
                    allow_redirects=False, timeout=ClientTimeout(total=600, connect=10, sock_read=30)) as upstream:
                if upstream.status in (301, 302, 303, 307, 308):
                    target = urljoin(url, upstream.headers.get('Location', ''))
                    if not trusted_cdn(target):
                        raise web.HTTPBadGateway(text='Resource download is unavailable')
                    url = target
                    continue
                if upstream.status != 200:
                    raise web.HTTPBadGateway(text='Resource download is unavailable')
                response = web.StreamResponse(headers={'Content-Type': 'application/octet-stream',
                    'Content-Length': str(size), 'Cache-Control': 'no-store',
                    'X-Content-Type-Options': 'nosniff'})
                await response.prepare(request)
                count = 0
                async for chunk in upstream.content.iter_chunked(65536):
                    count += len(chunk)
                    if count > size:
                        response.force_close()
                        break
                    await response.write(chunk)
                if count != size:
                    response.force_close()
                await response.write_eof()
                return response
        raise web.HTTPBadGateway(text='Resource download is unavailable')


def create_app(api_key, fetch=None):
    gateway = Gateway(api_key, fetch)
    app = web.Application(client_max_size=32768)
    app.router.add_get('/v1/download/{project:[1-9][0-9]{0,9}}/{file:[1-9][0-9]{0,9}}', gateway.download)
    app.router.add_route('*', '/v1{route:/.*}', gateway.handle)
    app.on_startup.append(gateway.startup)
    app.on_cleanup.append(gateway.cleanup)
    return app


if __name__ == '__main__':
    web.run_app(create_app(os.environ.get('CURSEFORGE_API_KEY', '')),
                host='127.0.0.1', port=18447, access_log=None)
