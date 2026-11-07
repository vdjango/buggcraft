"""Node-authorized origin planning. Only explicitly requested bodies are sent."""
import asyncio
from contextlib import contextmanager
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import threading
import tempfile
import time
from urllib.parse import urljoin, urlsplit

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
        timeout = kwargs.pop('timeout', (4, 20))
        return requests.request(method, grant['url'] + path,
            headers={**({'Authorization': 'Bearer ' + grant['token']} if grant.get('token') and method in ('POST', 'PUT') and path != '/room-cache/resolve' else {}), 'Accept-Encoding': 'identity',
                     'User-Agent': 'Buggcraft-RoomClient/1 (+https://bugg.icu)', **kwargs.pop('headers', {})},
            timeout=timeout, allow_redirects=False, **kwargs)

    async def release(self):
        grant = self.grant
        if not grant.get('token'):
            return
        def send():
            with self.request(grant, 'POST', '/room-cache/release', json={},
                              timeout=(2, 3)) as response:
                response.raise_for_status()
        await asyncio.wait_for(asyncio.to_thread(send), timeout=4)

    async def plan(self, *, files=None, failed=(), wanted=None, timeout=(4, 20)):
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
        if self.endpoint.role == 'host' and not getattr(self, 'legacy_upload_plan', False):
            data['direct_upload'] = True
        def query():
            with self.request(grant, 'POST', route, json=data, stream=True, timeout=timeout) as response:
                if response.status_code == 400 and data.pop('direct_upload', False):
                    # Older origins reject unknown fields; keep their relay compatible.
                    self.legacy_upload_plan = True
                    return query()
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

    async def upload_direct(self, ticket, file, chunks):
        """Use only the exact signed PUT. Room authorization never reaches the bucket."""
        import base64
        if not isinstance(ticket, dict):
            return False
        try:
            parsed = urlsplit(ticket['url'])
            expected = {'Content-Type': 'application/octet-stream', 'Content-Length': str(file['size']),
                        'x-amz-checksum-sha256': base64.b64encode(bytes.fromhex(file['sha256'])).decode('ascii')}
            valid = (ticket.get('method') == 'PUT' and parsed.scheme == 'https' and parsed.hostname
                     and parsed.port in (None,443) and not parsed.username and not parsed.password
                     and not parsed.fragment and len(ticket['url']) <= 8192 and ticket['headers'] == expected
                     and re.fullmatch('[0-9a-f]{32}', ticket['id']) and ticket['expires_at'] > time.time()+5)
        except (KeyError, ValueError, TypeError):
            valid = False
        if not valid:
            return False
        def send():
            with requests.Session() as session:
                with session.put(ticket['url'], headers={**expected, 'User-Agent':'Buggcraft-RoomClient/1'},
                        data=chunks, timeout=(6,30), allow_redirects=False) as response:
                    if response.status_code not in (200,201,204):
                        raise CacheUnavailable('云端直传暂不可用，将改用源站接收。')
        await asyncio.to_thread(send)
        grant = await self.authorize()
        def confirm():
            with self.request(grant,'POST','/room-cache/uploads/complete',json={'uploads':[ticket['id']]}) as response:
                response.raise_for_status()
                receipts = response.json().get('files',[])
                return any(receipt.get('id')==ticket['id'] and receipt.get('state')=='cached'
                           and receipt.get('sha256')==file['sha256'] and receipt.get('size')==file['size'] for receipt in receipts)
        return await asyncio.to_thread(confirm)

    def enrich(self, items):
        for item in items:
            plan = self.files.get(item['sha256'], {})
            if not plan or plan.get('size') != item['size']:
                continue
            if isinstance(plan.get('sha1'), str) and re.fullmatch('[0-9a-f]{40}', plan['sha1']):
                item['sha1'] = plan['sha1']
            urls = plan.get('downloads', []) if plan.get('action') == 'redirect' else []
            from core.client_file_source import mapped_url
            item['_accelerated_downloads'] = [url for url in urls if mapped_url(url)]
            # Keep the manifest's public fallbacks when the plan uses a cache.
            # Eviction must not turn an otherwise downloadable file into P2P-only.
            item['downloads'] = list(dict.fromkeys([*item['_accelerated_downloads'],
                *(url for url in item.get('downloads', []) if public_url(url))]))

    async def download(self, item, target, cancel, progress):
        plan = self.files.get(item['sha256'], {})
        if plan.get('action') != 'cached' or plan.get('size') != item['size']:
            return False
        grant = self.grant if self.grant.get('url') else await self.authorize()
        try:
            await asyncio.to_thread(self._download, grant, item, Path(target), cancel, progress)
        except (requests.RequestException, CacheUnavailable, ValueError):
            # Eviction/expiry or source downtime is an internal routing event.
            # Preserve the checkpoint and allow normal/P2P sources this round.
            return False
        return True

    @contextmanager
    def _download_response(self, grant, path, headers, cancel):
        # Cloud objects may use expiring signed URLs. Follow only HTTPS
        # redirects, retaining the Range but never forwarding a host grant.
        for _ in range(6):
            if cancel.is_set():
                raise InterruptedError('安装已取消。')
            with self.request(grant, 'GET', path, headers=headers, stream=True) as response:
                if response.status_code not in (301, 302, 303, 307, 308):
                    yield response
                    return
                location = response.headers.get('Location', '')
                try:
                    target = urljoin(grant['url'] + path, location)
                    parsed = urlsplit(target)
                    valid = (location and len(target) <= 8192 and parsed.scheme == 'https'
                             and parsed.hostname and not parsed.username and not parsed.password
                             and parsed.port in (None, 443) and not parsed.fragment)
                except ValueError:
                    valid = False
                if not valid:
                    raise CacheUnavailable('源站返回了无效的下载重定向。')
                grant = {'url': f'https://{parsed.netloc}'}
                path = parsed.path or '/'
                if parsed.query:
                    path += '?' + parsed.query
        raise CacheUnavailable('源站下载重定向次数过多，请尝试其他来源。')

    def _download(self, grant, item, target, cancel, progress):
        # A checkpoint is bound to size + SHA-256, never to the current URL.
        partial = target.with_name('.origin-' + item['sha256'] + '.part')
        offset = partial.stat().st_size if partial.exists() else 0
        if offset > item['size']:
            partial.unlink()
            offset = 0
        if offset != item['size']:
            headers = {'Range': f'bytes={offset}-'} if offset else {}
            with self._download_response(grant, '/room-cache/files/' + item['sha256'], headers, cancel) as response:
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


def host_metadata(endpoint, cancel, progress=None):
    from core.content_records import read_records
    from .modpack import manifest
    root = Path(endpoint.game_directory).resolve()
    from utils.storage_paths import game_cache
    index = game_cache(root) / 'room-content-hashes.json'
    try:
        hashes = json.loads(index.read_text(encoding='utf-8'))
        if not isinstance(hashes, dict):
            hashes = {}
    except (OSError, ValueError):
        hashes = {}
    records = {item['path']: item for item in read_records(root)}
    # Reuse fingerprints already computed for pack export; never delay room
    # creation by computing a second hash for every unchanged JAR.
    try:
        fingerprints = json.loads((game_cache(root) / 'room-fingerprints.json').read_text(encoding='utf-8'))
        if not isinstance(fingerprints, dict):
            fingerprints = {}
    except (OSError, ValueError):
        fingerprints = {}
    files = []
    for kind in ('mods', 'resources'):
        for file in manifest(root, kind, progress=(
                (lambda done, total, name: progress('scanning', done, total, name))
                if progress else None), include_sha1=True, cancel=cancel, hash_cache=hashes):
            if cancel.is_set():
                raise InterruptedError()
            path = file.get('path', 'mods/' + file['name'])
            file.update(path=path, downloads=[])
            fingerprint = fingerprints.get(file['sha1'] + ':' + str(file['size']))
            if type(fingerprint) is int and 0 <= fingerprint <= 0xffffffff:
                file['fingerprint'] = fingerprint
            record = records.get(path, {})
            if record.get('sha256') == file['sha256'] and record.get('size') == file['size']:
                file['downloads'] = [url for url in record.get('downloads', []) if public_url(url)]
            files.append(file)
    # Optimization only: a read-only cache directory must never prevent sharing.
    temporary = None
    try:
        index.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix='room-hashes-', dir=index.parent)
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump({file['path']: hashes[file['path']] for file in files}, stream)
        os.replace(temporary, index)
    except OSError:
        pass
    finally:
        if temporary:
            Path(temporary).unlink(missing_ok=True)
    return files


def find_requested_sources(root, files, requested, cancel):
    """Query the publisher in one batch only for files the origin needs."""
    from core.modpack_sources import find_public_mod_downloads
    from utils.storage_paths import game_cache
    lookup = [dict(file, source=Path(root) / file['path']) for file in files
              if file['sha256'] in requested and file['path'].startswith('mods/')]
    if not lookup:
        return {}
    return find_public_mod_downloads(lookup, cancel, cache_file=game_cache(root) / 'room-fingerprints.json',
                                     publisher='CurseForge', verify_downloads=False)


async def publish(endpoint):
    cache = await client(endpoint)
    cancel = threading.Event()
    signature, files, sharing = None, None, False
    report_lock = threading.Lock()
    last_report = {'key': None, 'at': 0.0}
    latest_summary = {}
    transfer_started = None
    def report(state, *, done=0, total=0, bytes_done=0, bytes_total=0, file='', message='', summary=None):
        nonlocal latest_summary
        callback = getattr(endpoint, 'on_cache_progress', None)
        if callback is None:
            return
        now = time.monotonic()
        key = (state, done, total, file, message)
        with report_lock:
            if summary is not None:
                latest_summary = dict(summary)
            if (state in ('scanning', 'uploading') and last_report.get('state') == state
                    and now - last_report['at'] < .3):
                return
            if key == last_report['key'] and now - last_report['at'] < .3:
                return
            last_report.update(key=key, state=state, at=now)
        callback(dict(state=state, done=done, total=total, summary=dict(latest_summary),
                      bytesDone=bytes_done, bytesTotal=bytes_total,
                      bytesPerSecond=round(bytes_done / max(.1, now-transfer_started)) if transfer_started else 0,
                      file=file, message=message))
    try:
        while not endpoint._stopped and endpoint.session:
            fast_next = False
            if not endpoint.game_directory or not endpoint.room_settings.get('allow_mod_transfer'):
                if sharing:
                    try:
                        await cache.release()
                    except (requests.RequestException, OSError, TimeoutError, CacheUnavailable):
                        pass
                    try:
                        await endpoint.lobby_request('content_cache_grant', share=False)
                    except (ValueError, ConnectionError, OSError):
                        pass
                    cache.grant, cache.published, cache.last_requested = {}, None, None
                    signature, sharing = None, False
                await asyncio.sleep(5)
                continue
            try:
                current = json.dumps([str(endpoint.game_directory), endpoint.room_info.get('game', {})], sort_keys=True)
                if current != signature:
                    if sharing:
                        try:
                            await cache.release()
                        except (requests.RequestException, OSError, TimeoutError, CacheUnavailable):
                            pass
                    cache.grant = {}
                    cache.published = None
                    cache.sources_checked = set()
                    latest_summary = {}
                    transfer_started = None
                    report('scanning', message='正在读取房间文件清单；正常下载不受影响…')
                    await cache.authorize()  # No hash/lookup work on unsupported nodes.
                    sharing = True
                    files = await asyncio.to_thread(host_metadata, endpoint, cancel,
                        lambda stage, done, total, name: report(stage, done=done, total=total,
                            file=name, message='正在核对文件' if stage == 'scanning' else '正在匹配公开来源'))
                    signature = current
                # Register metadata once per room configuration, then poll only
                # for new missing-file demand; polling never renews a lease.
                result = await cache.plan(files=files if getattr(cache, 'published', None) != signature else None)
                # A replaced/cleared source index needs metadata again; the
                # next poll restores it without hashing the local files again.
                cache.published = None if files and result.get('state') == 'waiting' else signature
                requested = {item['sha256'] for item in result.get('upload', [])}
                source_candidates = {item['sha256'] for item in result.get('upload', [])
                                     if item.get('reason_code') in ('no_source', 'slow', 'unavailable', 'failed')}
                unchecked_sources = source_candidates - getattr(cache, 'sources_checked', set())
                if unchecked_sources and result.get('public_lookup') != 'background':
                    cache.sources_checked.update(unchecked_sources)
                    report('matching', total=len(files), message='仅为需要补传的模组查询公开来源…',
                           summary=result.get('summary'))
                    lookup_cancel = threading.Event()
                    try:
                        found = await asyncio.wait_for(asyncio.to_thread(
                            find_requested_sources, endpoint.game_directory, files, unchecked_sources, lookup_cancel),
                            timeout=2)
                    except (TimeoutError, ConnectionError, OSError, ValueError):
                        lookup_cancel.set()
                        found = {}
                    if found:
                        for file in files:
                            if file['path'] in found:
                                file['downloads'] = list(dict.fromkeys(found[file['path']] + file['downloads']))
                        result = await cache.plan(files=files)
                        requested = {item['sha256'] for item in result.get('upload', [])}
                plan_summary = result.get('summary', {})
                report('matching', done=len(files), total=len(files), summary=plan_summary,
                       message=f"已核对 {len(files)} 个文件：公开来源 {plan_summary.get('redirect', 0)}，已有副本 {plan_summary.get('cached', 0)}，待补传 {plan_summary.get('upload', 0)}。")
                unique = {file['sha256']: file for file in files}
                deferred = {item['sha256'] for item in result.get('upload', []) if item.get('direct_deferred')}
                pending = [unique[digest] for digest in requested if digest in unique and digest not in deferred]
                cache.last_requested = requested
                if not pending:
                    waiting = plan_summary.get('pending', 0) or plan_summary.get('upload', 0)
                    report('pending' if waiting else 'complete', summary=plan_summary,
                           message=(f"已核对 {len(files)} 个文件；{waiting} 个等待来源或容量恢复。" if waiting else
                                    f"已核对 {len(files)} 个文件：公开来源 {plan_summary.get('redirect', 0)}，已有副本 {plan_summary.get('cached', 0)}，无需补传。"))
                slots = asyncio.Semaphore(4 if any(cache.files.get(file['sha256'],{}).get('direct_upload') for file in pending) else 2)
                relay_slots = asyncio.Semaphore(2)
                uploaded_bytes = {file['sha256']: 0 for file in pending}
                completed = set()
                total_bytes = sum(file['size'] for file in pending)
                initial_cached = plan_summary.get('cached', 0)
                initial_cached_bytes = plan_summary.get('cached_bytes', 0)
                initial_upload = plan_summary.get('upload', len(pending))
                def confirmed_summary():
                    return {**plan_summary,
                            'upload': min(plan_summary.get('upload', initial_upload), max(0, initial_upload-len(completed))),
                            'cached': max(plan_summary.get('cached', 0), initial_cached + len(completed)),
                            'cached_bytes': max(plan_summary.get('cached_bytes', 0),
                                initial_cached_bytes + sum(unique[digest]['size'] for digest in completed))}
                if pending:
                    transfer_started = time.monotonic()
                    report('uploading', total=len(pending), bytes_total=total_bytes,
                           summary=plan_summary, message=f'源站请求补传 {len(pending)} 个文件。')
                async def upload(file):
                    if file['sha256'] not in requested:
                        return
                    async with slots:
                        grant = await cache.authorize()
                        digest = file['sha256']
                        class UploadChunks:
                            def __len__(self):
                                return file['size']
                            def __iter__(self):
                                uploaded_bytes[digest] = 0
                                with (Path(endpoint.game_directory) / file['path']).open('rb') as stream:
                                    while True:
                                        block = stream.read(128 * 1024)
                                        if not block:
                                            break
                                        if cancel.is_set() or endpoint._stopped:
                                            raise InterruptedError()
                                        uploaded_bytes[digest] += len(block)
                                        report('uploading', done=len(completed), total=len(pending),
                                               bytes_done=sum(uploaded_bytes.values()), bytes_total=total_bytes,
                                               file=file['path'], message='正在同步所需文件',
                                               summary=confirmed_summary())
                                        yield block
                        ticket = cache.files.get(digest, {}).get('direct_upload')
                        if ticket:
                            try:
                                if await cache.upload_direct(ticket,file,UploadChunks()):
                                    completed.add(digest)
                                    report('uploading',done=len(completed),total=len(pending),
                                        bytes_done=sum(uploaded_bytes.values()),bytes_total=total_bytes,
                                        file=file['path'],message='云空间已接收并通过校验',summary=confirmed_summary())
                                    return
                            except (requests.RequestException, CacheUnavailable, ValueError, OSError):
                                if cancel.is_set() or endpoint._stopped:
                                    raise InterruptedError()
                                LOG.info('room_direct_upload_fallback')
                        def send():
                            if cancel.is_set() or endpoint._stopped:
                                raise InterruptedError()
                            with cache.request(grant, 'PUT', '/room-cache/files/' + digest,
                                               data=UploadChunks()) as response:
                                response.raise_for_status()
                                # The count advances after the server has received
                                # and hash-verified the file, not when our socket writes it.
                                if response.content:
                                    receipt = response.json()
                                    if (receipt.get('state') != 'cached'
                                            or receipt.get('sha256', digest) != digest
                                            or receipt.get('size', file['size']) != file['size']):
                                        raise CacheUnavailable('源站尚未确认文件缓存完成。')
                        async with relay_slots:
                            await asyncio.to_thread(send)
                        completed.add(digest)
                        report('uploading', done=len(completed), total=len(pending),
                               bytes_done=sum(uploaded_bytes.values()), bytes_total=total_bytes,
                               file=file['path'], message='源站已接收并通过校验', summary=confirmed_summary())
                async def observe_origin():
                    nonlocal plan_summary
                    while True:
                        await asyncio.sleep(1)
                        try:
                            status = await cache.plan()
                            plan_summary = status.get('summary', plan_summary)
                            report('uploading', done=len(completed), total=len(pending),
                                bytes_done=sum(uploaded_bytes.values()), bytes_total=total_bytes,
                                message='源站正在接收并核验；正常下载不受影响', summary=confirmed_summary())
                        except (requests.RequestException, CacheUnavailable, OSError, ValueError):
                            pass
                observer = asyncio.create_task(observe_origin()) if pending else None
                try:
                    results = await asyncio.gather(*(upload(file) for file in pending), return_exceptions=True)
                finally:
                    if observer:
                        observer.cancel()
                        await asyncio.gather(observer, return_exceptions=True)
                if any(isinstance(item, BaseException) for item in results):
                    report('pending', done=len(completed), total=len(pending),
                           bytes_done=sum(uploaded_bytes.values()), bytes_total=total_bytes,
                           message='部分文件尚未加速缓存；正常下载可继续，稍后只补齐缺失文件。', summary=confirmed_summary())
                    LOG.info('room_file_acceleration_pending')
                elif pending:
                    fast_next = bool(deferred)
                    report('pending' if deferred else 'complete', done=len(pending), total=len(pending),
                           bytes_done=total_bytes, bytes_total=total_bytes,
                           message=f'文件共享加速已完成：{len(pending)} 个所需文件已同步到源站。',
                           summary=confirmed_summary())
            except CacheUnavailable as exc:
                report('pending', message=str(exc))
                if cache.unavailable:
                    return
            except (requests.RequestException, ValueError, OSError, InterruptedError) as exc:
                report('pending', message=f'源站同步暂未完成：{type(exc).__name__}，稍后自动重试。')
                LOG.info('room_file_origin_pending')  # Grants and URLs stay out of logs.
            await asyncio.sleep(.25 if fast_next else 5)
    finally:
        cancel.set()
        if sharing:
            try:
                await cache.release()
            except (requests.RequestException, OSError, TimeoutError, CacheUnavailable):
                pass
