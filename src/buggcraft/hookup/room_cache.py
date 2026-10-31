"""Node-authorized origin planning. Only explicitly requested bodies are sent."""
import asyncio
import hashlib
import json
import logging
from pathlib import Path
import re
import threading
import time
from urllib.parse import urlsplit

import requests

LOG = logging.getLogger(__name__)
PUBLIC_HOSTS = {'edge.forgecdn.net', 'mediafilez.forgecdn.net', 'media.forgecdn.net',
                'cdn.modrinth.com', 'mod.mcimirror.top', 'mirror.minguncle.cn'}


def public_url(url):
    try:
        parsed = urlsplit(url)
        return (parsed.scheme == 'https' and parsed.hostname in PUBLIC_HOSTS
                and not parsed.username and not parsed.password and parsed.port in (None, 443)
                and not parsed.query and not parsed.fragment and len(url) <= 2048)
    except (TypeError, ValueError):
        return False


class CacheUnavailable(ConnectionError):
    pass


class PendingRoomFiles(ConnectionError):
    def __init__(self, files):
        self.files = files
        names = '、'.join(item['name'] for item in files[:4])
        reasons = '；'.join('模组下载失败（' + item['name'] + '）：' + item.get('_download_error', '来源暂不可用') for item in files[:4])
        super().__init__(f'还有 {len(files)} 个必需文件未就绪：{names}。{reasons}。已完成的文件已保留；请让房主保持在线并开启文件共享，稍后点击重试将只补齐缺失文件。')


class RoomCacheClient:
    def __init__(self, endpoint):
        self.endpoint, self.grant, self.files = endpoint, {}, {}
        self.unavailable = False
        self.lock = asyncio.Lock()

    async def authorize(self):
        async with self.lock:
            if self.unavailable:
                raise CacheUnavailable('当前节点未配置源站文件兜底。')
            if self.grant.get('expires_at', 0) > time.time() + 30:
                return self.grant
            fields = {'share': bool(self.endpoint.room_settings.get('allow_mod_transfer'))} if self.endpoint.role == 'host' else {}
            try:
                grant = await self.endpoint.lobby_request('content_cache_grant', **fields)
            except (ValueError, AttributeError) as exc:
                self.unavailable = True
                raise CacheUnavailable('当前节点未启用房间文件兜底。') from exc
            parsed = urlsplit(grant.get('url', ''))
            if (grant.get('protocol') != 'room-content-cache-v1' or parsed.scheme != 'https'
                    or not parsed.hostname or parsed.username or parsed.password
                    or parsed.path or parsed.query or parsed.fragment or parsed.port not in (None, 443)
                    or self.endpoint.role == 'host' and (not isinstance(grant.get('token'), str) or len(grant['token']) > 2048)):
                raise CacheUnavailable('节点返回的文件兜底地址无效。')
            self.grant = grant
            from core.client_file_source import set_origin
            set_origin(grant['url'])
            return grant

    @staticmethod
    def request(grant, method, path, **kwargs):
        return requests.request(method, grant['url'] + path,
            headers={**({'Authorization': 'Bearer ' + grant['token']} if grant.get('token') and method in ('POST', 'PUT') and path != '/room-cache/resolve' else {}), 'Accept-Encoding': 'identity',
                     'User-Agent': 'Buggcraft-RoomClient/1 (+https://bugg.icu)', **kwargs.pop('headers', {})},
            timeout=(4, 20), allow_redirects=False, **kwargs)

    async def plan(self, *, files=None, failed=(), wanted=None):
        grant = await self.authorize()
        data = {'failed': list(failed)}
        route = '/room-cache/plan'
        if self.endpoint.role != 'host':
            route = '/room-cache/resolve'
            if wanted is not None:
                self.wanted = list(wanted)
            data['wanted'] = getattr(self, 'wanted', [])
        if files is not None:
            data['files'] = files
        def query():
            with self.request(grant, 'POST', route, json=data, stream=True) as response:
                if response.status_code == 401:
                    self.grant = {}
                response.raise_for_status()
                raw = bytearray()
                for chunk in response.iter_content(65536):
                    raw.extend(chunk)
                    if len(raw) > 2 * 1024 ** 2:
                        raise CacheUnavailable('源站文件清单过大。')
                result = json.loads(raw)
                if result.get('protocol') != 'room-content-cache-v1' or not isinstance(result.get('files'), list):
                    raise CacheUnavailable('源站文件清单无效。')
                return result
        result = await asyncio.to_thread(query)
        self.files = {item['sha256']: item for item in result['files']}
        return result

    def enrich(self, items):
        for item in items:
            plan = self.files.get(item['sha256'], {})
            if not plan or plan.get('size') != item['size']:
                continue
            if isinstance(plan.get('sha1'), str) and re.fullmatch('[0-9a-f]{40}', plan['sha1']):
                item['sha1'] = plan['sha1']
            urls = plan.get('downloads', []) if plan.get('action') == 'redirect' else []
            item['downloads'] = [url for url in urls if public_url(url)]

    async def download(self, item, target, cancel, progress):
        plan = self.files.get(item['sha256'], {})
        if plan.get('action') != 'cached' or plan.get('size') != item['size']:
            return False
        grant = self.grant if self.grant.get('url') else await self.authorize()
        try:
            await asyncio.to_thread(self._download, grant, item, Path(target), cancel, progress)
        except (requests.RequestException, CacheUnavailable):
            # Eviction/expiry or source downtime is an internal routing event.
            # Preserve the checkpoint and allow normal/P2P sources this round.
            return False
        return True

    def _download(self, grant, item, target, cancel, progress):
        # A checkpoint is bound to size + SHA-256, never to the current URL.
        partial = target.with_name('.origin-' + item['sha256'] + '.part')
        offset = partial.stat().st_size if partial.exists() else 0
        if offset > item['size']:
            partial.unlink()
            offset = 0
        if offset != item['size']:
            headers = {'Range': f'bytes={offset}-'} if offset else {}
            with self.request(grant, 'GET', '/room-cache/files/' + item['sha256'], headers=headers, stream=True) as response:
                if response.status_code == 401:
                    self.grant = {}
                response.raise_for_status()
                if response.status_code not in (200, 206):
                    raise CacheUnavailable('源站文件尚未就绪，等待房主补齐。')
                if response.status_code == 206:
                    if response.headers.get('Content-Range') != f"bytes {offset}-{item['size'] - 1}/{item['size']}":
                        raise CacheUnavailable('源站续传范围无效。')
                elif offset:
                    offset = 0
                with partial.open('ab' if offset else 'wb') as output:
                    for chunk in response.iter_content(128 * 1024):
                        if cancel.is_set():
                            raise InterruptedError('安装已取消。')
                        if offset + len(chunk) > item['size']:
                            raise CacheUnavailable('源站文件大小超出房间清单。')
                        output.write(chunk)
                        offset += len(chunk)
                        progress(offset, item['size'])
        digest = hashlib.sha256()
        with partial.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                if cancel.is_set():
                    raise InterruptedError('安装已取消。')
                digest.update(chunk)
        if offset != item['size'] or digest.hexdigest() != item['sha256']:
            partial.unlink(missing_ok=True)
            raise CacheUnavailable('源站文件校验失败，等待重新补齐。')
        partial.replace(target)
        progress(item['size'], item['size'])


async def client(endpoint):
    if not hasattr(endpoint, 'lobby_request'):
        return None
    current = getattr(endpoint, '_content_cache', None)
    if current is None:
        current = endpoint._content_cache = RoomCacheClient(endpoint)
    return current


def host_metadata(endpoint, cancel):
    from core.content_records import read_records
    from core.modpack_sources import find_public_mod_downloads
    from utils.storage_paths import game_cache
    from .modpack import manifest
    root = Path(endpoint.game_directory).resolve()
    records = {item['path']: item for item in read_records(root)}
    files, lookup = [], []
    for kind in ('mods', 'resources'):
        for file in manifest(root, kind):
            if cancel.is_set():
                raise InterruptedError()
            path = file.get('path', 'mods/' + file['name'])
            source = root / path
            sha1 = hashlib.sha1()
            with source.open('rb') as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    if cancel.is_set():
                        raise InterruptedError()
                    sha1.update(chunk)
            file.update(path=path, sha1=sha1.hexdigest(), downloads=[])
            record = records.get(path, {})
            if record.get('sha256') == file['sha256'] and record.get('size') == file['size']:
                file['downloads'] = [url for url in record.get('downloads', []) if public_url(url)]
            if kind == 'mods' and not any(urlsplit(url).hostname not in ('cdn.modrinth.com', 'mod.mcimirror.top') for url in file['downloads']):
                lookup.append(dict(file, source=source))
            files.append(file)
    found = find_public_mod_downloads(lookup, cancel, cache_file=game_cache(root) / 'room-fingerprints.json',
                                      publisher='CurseForge', verify_downloads=False)
    for file in files:
        file['downloads'] = list(dict.fromkeys(found.get(file['path'], []) + file['downloads']))
    return files


async def publish(endpoint):
    cache = await client(endpoint)
    cancel = threading.Event()
    signature, files, sharing = None, None, False
    try:
        while not endpoint._stopped and endpoint.session:
            if not endpoint.game_directory or not endpoint.room_settings.get('allow_mod_transfer'):
                if sharing:
                    try:
                        await endpoint.lobby_request('content_cache_grant', share=False)
                    except (ValueError, ConnectionError, OSError):
                        pass
                    cache.grant, signature, sharing = {}, None, False
                await asyncio.sleep(5)
                continue
            try:
                current = json.dumps([str(endpoint.game_directory), endpoint.room_info.get('game', {})], sort_keys=True)
                if current != signature:
                    cache.grant = {}
                    await cache.authorize()  # No hash/lookup work on unsupported nodes.
                    sharing = True
                    files = await asyncio.to_thread(host_metadata, endpoint, cancel)
                    signature = current
                # Register metadata once per room configuration, then poll only
                # for new missing-file demand; polling never renews a lease.
                result = await cache.plan(files=files if getattr(cache, 'published', None) != signature else None)
                # A replaced/cleared source index needs metadata again; the
                # next poll restores it without hashing the local files again.
                cache.published = None if files and result.get('state') == 'waiting' else signature
                requested = {item['sha256'] for item in result.get('upload', [])}
                slots = asyncio.Semaphore(2)
                async def upload(file):
                    if file['sha256'] not in requested:
                        return
                    async with slots:
                        grant = await cache.authorize()
                        def send():
                            if cancel.is_set():
                                raise InterruptedError()
                            with (Path(endpoint.game_directory) / file['path']).open('rb') as stream:
                                with cache.request(grant, 'PUT', '/room-cache/files/' + file['sha256'], data=stream) as response:
                                    response.raise_for_status()
                        await asyncio.to_thread(send)
                unique = {file['sha256']: file for file in files}
                results = await asyncio.gather(*(upload(file) for file in unique.values()), return_exceptions=True)
                if any(isinstance(result, BaseException) for result in results):
                    LOG.info('room_file_acceleration_pending')
            except CacheUnavailable:
                if cache.unavailable:
                    return
            except (requests.RequestException, ValueError, OSError):
                LOG.info('room_file_origin_pending')  # Grants and URLs stay out of logs.
            await asyncio.sleep(5)
    finally:
        cancel.set()
