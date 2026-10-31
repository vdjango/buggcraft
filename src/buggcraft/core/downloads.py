"""Verified Minecraft downloads without UI dependencies or global HTTP patches."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import re
import select
import shutil
import socket
import threading
import time
import zipfile
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, as_completed, wait
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from pathlib import Path
from urllib.parse import urlsplit

import requests
from config.downloads import download_concurrency, normalize_concurrency
from urllib3.exceptions import HTTPError as TransportError
from urllib3.response import HTTPResponse

from utils.archives import extract_zip
from utils.download_locks import download_lock
from utils.http_identity import USER_AGENT


MANIFEST_URL = "https://launchermeta.mojang.com/mc/game/version_manifest_v2.json"
MIRROR = "https://bmclapi2.bangbang93.com"
CONTENT_MIRROR = 'https://mod.mcimirror.top'
logger = logging.getLogger(__name__)
_SHARED_DOWNLOAD_ROOT = ContextVar('shared_download_root', default=None)


@contextmanager
def use_shared_download_cache(directory):
    """Keep isolated loader installs on the game's shared immutable resources."""
    token = _SHARED_DOWNLOAD_ROOT.set(_resolved(directory))
    try:
        yield
    finally:
        _SHARED_DOWNLOAD_ROOT.reset(token)


class _MirrorHealth:
    """Share a short outage backoff across independent content download tasks."""
    def __init__(self):
        self.lock = threading.Lock()
        self.blocked_until = 0

    def blocked(self):
        with self.lock:
            return self.blocked_until > time.monotonic()

    def pause(self):
        with self.lock:
            self.blocked_until = time.monotonic() + 60


_CONTENT_HEALTH = _MirrorHealth()
_CONTENT_ROUTE_CACHE = {}
_CONTENT_ROUTE_LOCK = threading.Lock()
_CONTENT_PROBE_LOCK = threading.Lock()
_CONTENT_ROUTE_TTL = 600
_CONTENT_PROBE_BYTES = 64 * 1024


def _measure_content_route(url):
    started = time.monotonic()
    try:
        with requests.get(url, stream=True, timeout=(3, 5), allow_redirects=True,
                          headers={'User-Agent': USER_AGENT, 'Accept-Encoding': 'identity',
                                   'Range': f'bytes=0-{_CONTENT_PROBE_BYTES - 1}'}) as response:
            response.raise_for_status()
            if str(response.headers.get('Content-Type', '')).split(';')[0].lower() in ('text/html', 'application/xhtml+xml'):
                return 0.0
            chunk = next(response.iter_content(_CONTENT_PROBE_BYTES), b'')
            if not chunk:
                return 0.0
            return len(chunk) / max(time.monotonic() - started, 0.001)
    except (requests.RequestException, OSError, ValueError):
        return 0.0


def _rank_content_candidates(candidates, preference='自动测速'):
    # Concurrent files share one measurement per host and cache lifetime.
    with _CONTENT_PROBE_LOCK:
        return _rank_content_candidates_locked(candidates, preference)


def _rank_content_candidates_locked(candidates, preference):
    """Rank trusted public content routes by a bounded, cached range probe."""
    candidates = list(dict.fromkeys(candidates))
    if len(candidates) < 2:
        return candidates
    hosts = {candidate: urlsplit(candidate).hostname for candidate in candidates}
    pending = {}
    now = time.monotonic()
    with _CONTENT_ROUTE_LOCK:
        for candidate, host in hosts.items():
            cached = _CONTENT_ROUTE_CACHE.get(host)
            if cached and cached[1] > now:
                pending[candidate] = cached[0]
    missing = [candidate for candidate in candidates if candidate not in pending]
    if missing:
        with ThreadPoolExecutor(max_workers=min(4, len(missing))) as pool:
            measured = dict(zip(missing, pool.map(_measure_content_route, missing)))
        with _CONTENT_ROUTE_LOCK:
            for candidate, speed in measured.items():
                host = hosts[candidate]
                _CONTENT_ROUTE_CACHE[host] = (speed, time.monotonic() + _CONTENT_ROUTE_TTL)
                pending[candidate] = speed
    ranked = sorted(candidates, key=lambda candidate: pending.get(candidate, 0), reverse=True)
    if preference == 'MCIM':
        mirror_host = urlsplit(CONTENT_MIRROR).hostname
        mirror = next((candidate for candidate in ranked if hosts[candidate] == mirror_host), None)
        if mirror and pending.get(mirror, 0) >= pending.get(ranked[0], 0) * 0.85:
            ranked.remove(mirror)
            ranked.insert(0, mirror)
    logger.info('content_routes_ranked routes=%s', [
        {'host': hosts[candidate], 'bytes_per_second': round(pending.get(candidate, 0))}
        for candidate in ranked])
    return ranked


class _DownloadSession(requests.Session):
    def __init__(self, curseforge_key='', curseforge_fallbacks=None):
        super().__init__()
        self.headers['User-Agent'] = USER_AGENT
        self.curseforge_key = curseforge_key
        self.curseforge_fallbacks = curseforge_fallbacks or {}

    def request(self, method, url, **kwargs):
        parsed = urlsplit(url)
        headers = dict(kwargs.get('headers') or {})
        if (parsed.scheme == 'https' and parsed.port in (None, 443) and
                (parsed.hostname or '').endswith('.forgecdn.net') and self.curseforge_key):
            headers['x-api-key'] = self.curseforge_key
        else:
            headers.pop('x-api-key', None)
        kwargs['headers'] = headers
        response = super().request(method, url, **kwargs)
        fallback = self.curseforge_fallbacks.get(url)
        if method.upper() == 'GET' and response.status_code == 401 and fallback:
            response.close()
            headers.pop('x-api-key', None)
            return super().request(method, fallback, **kwargs)
        return response

    def rebuild_auth(self, prepared_request, response):
        super().rebuild_auth(prepared_request, response)
        parsed = urlsplit(prepared_request.url)
        if parsed.scheme != 'https' or parsed.port not in (None, 443) or not (parsed.hostname or '').endswith('.forgecdn.net'):
            prepared_request.headers.pop('x-api-key', None)


class DownloadCancelled(Exception):
    pass


class DownloadCancellation(threading.Event):
    """Wake blocked response reads when a task is canceled or changes source."""
    def __init__(self):
        super().__init__()
        self._responses = set()
        self._response_lock = threading.Lock()

    @staticmethod
    def _interrupt(response):
        raw = response.raw
        try:
            # A Connection: close response may have no pool connection, while
            # its body still owns a live socket. urllib3 keeps that socket's
            # shutdown callback specifically for interrupting streaming reads.
            shutdown = getattr(raw, '_sock_shutdown', None)
            if callable(shutdown) and not raw.closed:
                shutdown(socket.SHUT_RDWR)
                connection = getattr(raw, '_connection', None)
                if connection is not None:
                    connection.close()
            else:
                raw.shutdown()
        except (AttributeError, OSError, RuntimeError, ValueError):
            pass

    def set(self):
        super().set()
        with self._response_lock:
            responses = tuple(self._responses)
        for response in responses:
            self._interrupt(response)

    @contextmanager
    def response(self, response):
        # Windows does not reliably wake a timed socket's select() when another
        # thread shuts it down. Wait for readability in short intervals before
        # entering SocketIO, preserving its existing buffered and TLS handling.
        body = getattr(getattr(getattr(response.raw, '_fp', None), 'fp', None), 'raw', None)
        body_socket = getattr(body, '_sock', None)
        original_readinto = getattr(body, 'readinto', None)
        if isinstance(body_socket, socket.socket) and callable(original_readinto):
            def readinto(buffer):
                timeout = body_socket.gettimeout()
                deadline = time.monotonic() + timeout if timeout else None
                while True:
                    if self.is_set():
                        raise DownloadCancelled('下载已取消，已下载进度会保留。')
                    if deadline is not None and time.monotonic() >= deadline:
                        raise socket.timeout('下载响应读取超时')
                    if (getattr(body_socket, 'pending', lambda: 0)()
                            or select.select([body_socket], [], [], 0.2)[0]):
                        return original_readinto(buffer)
            body.readinto = readinto
        with self._response_lock:
            self._responses.add(response)
        if self.is_set():
            self._interrupt(response)
        try:
            yield response
        finally:
            if isinstance(body_socket, socket.socket) and callable(original_readinto):
                body.readinto = original_readinto
            with self._response_lock:
                self._responses.discard(response)


class DownloadSourcesExhausted(RuntimeError):
    """A concise per-source failure summary safe to show outside the logs."""

    def __init__(self, message, *, source_errors=()):
        super().__init__(message)
        self.source_errors = tuple(source_errors)


def _source_failure_reason(error):
    if isinstance(error, requests.HTTPError) and error.response is not None:
        code = error.response.status_code
        return {403: '拒绝访问（403）', 404: '文件不存在（404）', 410: '文件已移除（410）',
                429: '请求过多（429）'}.get(code, f'服务器错误（HTTP {code}）')
    if isinstance(error, requests.Timeout):
        return '连接或读取超时'
    if isinstance(error, requests.exceptions.SSLError):
        return 'TLS 证书或连接失败'
    if isinstance(error, (requests.ConnectionError, requests.exceptions.ChunkedEncodingError)):
        return '连接中断或网络不可达'
    if isinstance(error, PermissionError):
        return '文件夹没有写入权限'
    if isinstance(error, ValueError):
        return str(error)[:140]
    return '写入文件或网络读取失败'


def download_error_message(error):
    """Project transport/parser failures into UI text; retain details in logs."""
    message = str(error or '').strip()
    if isinstance(error, OSError) and error.errno == 28:
        return '磁盘空间不足，请清理空间或更换安装目录后重试。已下载进度会保留。'
    if isinstance(error, DownloadSourcesExhausted) or '全部可用下载源均失败' in message:
        return message
    if isinstance(error, PermissionError) or re.search(r'\bPermissionError\b|Access is denied|access denied',
                                                       message, re.IGNORECASE):
        return '目标文件夹没有写入权限，请选择其他文件夹后重试。'
    if (isinstance(error, (json.JSONDecodeError, UnicodeDecodeError))
            or re.search(r'JSONDecodeError|Expecting (?:value|property name)|Extra data: line|'
                         r'Unterminated string|line \d+ column \d+', message, re.IGNORECASE)):
        return '下载信息不完整或格式错误，请点击重试。已下载进度会保留。'
    raw_data = (message.startswith('{')
                or re.match(r'^\[\s*(?:\{|\[|["\']|\]|true\b|false\b|null\b|-?\d+(?=[.,\]\s]))', message)
                or re.search(r'\{\s*["\'][^\n]+["\']\s*:', message))
    transport = isinstance(error, requests.RequestException) or re.search(
        r'https?://|HTTPS?ConnectionPool|Max retries exceeded|'
        r'(?:Connect|Read)?Timeout(?:Error)?|ConnectionError|SSLError|'
        r'Client Error|Server Error|Caused by|Traceback \(most recent call last\)', message, re.IGNORECASE)
    if transport:
        failed_file = re.match(r'下载\s+([^\n/\\:：]{1,100})\s+失败[:：]', message)
        prefix = (failed_file[1] + ' 下载失败：') if failed_file else ''
        if re.search(r'timed?\s*out|timeout|超时', message, re.IGNORECASE):
            return prefix + '连接下载源超时，请重试或在设置中切换下载源。已下载进度会保留。'
        if re.search(r'\b404\b', message):
            return prefix + '下载源暂未提供所需文件（404），请重试或在设置中切换下载源。已下载进度会保留。'
        return prefix + '暂时无法从下载源获取文件，请重试或在设置中切换下载源。已下载进度会保留。'
    if raw_data or len(message) > 400 or '\n' in message:
        return '下载未完成，请重试。可在任务日志中查看详情。'
    return message


_CURRENT_DOWNLOAD_BUDGET = ContextVar('buggcraft_download_budget', default=None)


class DownloadBudget:
    """One task-wide slot pool shared by game and content downloaders."""

    def __init__(self, workers):
        self.workers = normalize_concurrency(workers)
        self.slots = threading.BoundedSemaphore(self.workers)

    @contextmanager
    def reserve(self, cancel):
        while True:
            if cancel.is_set():
                raise DownloadCancelled('下载已取消')
            if self.slots.acquire(timeout=0.1):
                break
        try:
            yield
        finally:
            self.slots.release()


@contextmanager
def use_download_budget(workers=None):
    existing = _CURRENT_DOWNLOAD_BUDGET.get()
    if existing is not None and workers is None:
        yield existing
        return
    budget = DownloadBudget(download_concurrency() if workers is None else workers)
    token = _CURRENT_DOWNLOAD_BUDGET.set(budget)
    try:
        yield budget
    finally:
        _CURRENT_DOWNLOAD_BUDGET.reset(token)


class _SlowMirror(requests.ConnectionError):
    """Keep verified-size partial data when switching away from a slow mirror."""


def _download_chunks(response, mirror):
    # read1 yields currently available bytes. iter_content waits to fill its
    # buffer, hiding a server that keeps the socket alive with tiny trickles.
    if isinstance(response.raw, HTTPResponse) and hasattr(response.raw, 'read1'):
        try:
            while chunk := response.raw.read1(64 * 1024, decode_content=True):
                yield chunk
        except TransportError as exc:
            raise requests.ConnectionError(exc) from exc
    else:
        yield from response.iter_content(64 * 1024)


def _resolved(path):
    value = str(Path(path).resolve())
    # Windows can retain the extended prefix when another worker creates a parent.
    if os.name == 'nt' and value.startswith('\\\\?\\'):
        value = '\\\\' + value[8:] if value.startswith('\\\\?\\UNC\\') else value[4:]
    return Path(value)


def _sha1(path):
    digest = hashlib.sha1()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verified_installation(directory, version):
    """Check the local installation receipt without needing an Internet connection."""
    root = _resolved(directory)
    try:
        receipt = json.loads((root / 'versions' / version / '.buggcraft-complete.json').read_text(encoding='utf-8'))
        if receipt.get('version') != version or not receipt.get('files'):
            return False
        for item in receipt['files']:
            # Old receipts accidentally included JNA's randomly named temporary
            # DLLs. JNA removes these on exit; they are not installation assets.
            if _temporary_jna_native(item['path'], version):
                continue
            target = _resolved(root / item['path'])
            if not target.is_relative_to(root) or not target.is_file():
                return False
            if item.get('sha1') and _sha1(target) != item['sha1']:
                return False
        return True
    except (OSError, ValueError, KeyError, TypeError):
        return False


def _temporary_jna_native(relative, version):
    parts = str(relative).replace('\\', '/').split('/')
    return (len(parts) == 4 and parts[:3] == ['versions', version, 'natives']
            and re.fullmatch(r'jna[0-9]+\.dll(?:\.x)?', parts[3]) is not None)


class MinecraftDownloader:
    def __init__(self, directory, source="自动", cancel=None, status=None, progress=None, file_event=None, workers=None,
                 retries=2):
        self.root = _resolved(directory)
        self.shared_root = _SHARED_DOWNLOAD_ROOT.get()
        self.source = source
        self.content_source = None
        self.resolve_content_sources = False
        self.budget = _CURRENT_DOWNLOAD_BUDGET.get()
        self.workers = (self.budget.workers if self.budget is not None else download_concurrency()) if workers is None else normalize_concurrency(workers)
        self.cancel = cancel if cancel is not None else threading.Event()
        self.status = status or (lambda message: None)
        self.progress = progress or (lambda current, maximum: None)
        self.file_event = file_event
        self.retries = max(0, min(int(retries), 6))
        self.file_names = {}
        self._sessions = threading.local()
        self._verified = {}
        self._verified_lock = threading.Lock()
        self._blocked_hosts = {}
        self._blocked_hosts_lock = threading.Lock()
        self.system = {"Windows": "windows", "Darwin": "osx"}.get(platform.system(), "linux")

    def check_cancelled(self):
        if self.cancel.is_set():
            raise DownloadCancelled("下载已停止，已下载进度会保留，点击重试继续下载")

    def urls(self, original):
        parsed = urlsplit(original)
        # MCIM serves content files; BMCLAPI serves the game and its libraries.
        # Both settings share this router, including every URL in an MRPACK.
        trusted = (parsed.scheme == 'https' and parsed.port in (None, 443)
                   and not parsed.username and not parsed.password)
        # MCIM explicitly excludes this CDN. Keep its URL exactly as published;
        # independently published edge/Modrinth links can still be candidates.
        if trusted and parsed.hostname == 'mediafilez.forgecdn.net':
            return [original]
        # Some cached manifests already contain mirror URLs. Recover the
        # publisher route too, otherwise fallback silently has no alternative.
        if trusted and parsed.hostname == urlsplit(CONTENT_MIRROR).hostname:
            upstream = ('cdn.modrinth.com' if parsed.path.startswith('/data/') else
                        'edge.forgecdn.net' if parsed.path.startswith('/files/') else None)
            if upstream:
                return self.urls(parsed._replace(netloc=upstream).geturl())
        if trusted and parsed.hostname in ('cdn.modrinth.com', 'edge.forgecdn.net'):
            originals = [original]
            if parsed.hostname in ('edge.forgecdn.net', 'mediafilez.forgecdn.net'):
                alternate = 'mediafilez.forgecdn.net' if parsed.hostname == 'edge.forgecdn.net' else 'edge.forgecdn.net'
                originals.append(parsed._replace(netloc=alternate).geturl())
            content_source = self.content_source or self.source
            if content_source == '官方':
                return originals
            mirror = parsed._replace(netloc=urlsplit(CONTENT_MIRROR).netloc).geturl()
            if content_source in ('CurseForge', 'Modrinth'):
                return [*originals, mirror]
            return [mirror, *originals]
        from core.game_sources import source_urls
        return source_urls(self.source, original)

    def inside(self, relative):
        parts = Path(relative).parts
        if parts and parts[0] == '.buggcraft-downloads':
            from utils.storage_paths import game_cache
            root = _resolved(game_cache(self.root))
            target = _resolved(root.joinpath(*parts[1:]))
            if target == root or not target.is_relative_to(root):
                raise ValueError('下载缓存路径无效：' + str(relative))
            return target
        target = _resolved(self.root / relative)
        if target == self.root or not target.is_relative_to(self.root):
            raise ValueError(f"下载路径超出游戏目录：{relative} ({target!s}; root={self.root!s})")
        return target

    def fetch(self, url, relative, sha1=None, size=None, *, sha512=None, file_progress=None, _validate=None):
        self._file_event(relative, 'pending', total=size or 0)
        try:
            with download_lock(self.inside(relative), self.cancel):
                return self._fetch_resource(url, relative, sha1, size, sha512=sha512, file_progress=file_progress, _validate=_validate)
        except (DownloadCancelled, InterruptedError):
            self._file_event(relative, 'cancelled')
            raise
        except Exception as exc:
            self._file_event(relative, 'failed', error=str(exc))
            raise

    def _fetch_resource(self, url, relative, sha1, size, **options):
        parts = Path(relative).parts
        if (not self.shared_root or self.shared_root == self.root or not (sha1 or options.get('sha512'))
                or not parts or parts[0] not in ('libraries', 'assets')):
            return self._fetch_budgeted(url, relative, sha1, size, **options)
        shared = _resolved(self.shared_root / relative)
        if not shared.is_relative_to(self.shared_root):
            raise ValueError('共享资源路径超出游戏目录：' + str(relative))
        local = self.inside(relative)
        with download_lock(shared, self.cancel):
            # A cancelled workspace may hold a complete file not yet published.
            # Seed it first; _fetch still checks the expected size and digest.
            if local.is_file() and not shared.exists():
                self._link_resource(local, shared)
            self._fetch_budgeted(url, relative, sha1, size, _destination=shared, **options)
            self.check_cancelled()
            self._link_resource(shared, local)
        return local

    def _fetch_budgeted(self, *args, **options):
        # Acquire file locks before a network slot: a waiter must not starve
        # the writer holding the shared file and waiting for that same slot.
        with self.budget.reserve(self.cancel) if self.budget is not None else nullcontext():
            return self._fetch(*args, **options)

    @staticmethod
    def _link_resource(source, destination):
        from utils.path_helper import filesystem_path
        source, destination = filesystem_path(source), filesystem_path(destination)
        if destination.exists() and os.path.samefile(source, destination):
            return
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + '.buggcraft-cache-part')
        try:
            temporary.unlink(missing_ok=True)
            try:
                os.link(source, temporary)
            except OSError:
                shutil.copy2(source, temporary)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)

    def _file_event(self, relative, state, **values):
        if self.file_event:
            if 'url' in values:
                from utils.download_address import display_address
                values['url'] = display_address(values['url'])
            path = Path(relative).as_posix()
            self.file_event(dict(key=str(self.root / relative), path=path,
                                 name=self.file_names.get(path, Path(relative).name), state=state, **values))

    def _parallel_content(self, url, temporary, size, headers, timeout, relative, file_progress):
        """Use bounded ranges for large individual files; verify after joining.

        The original response remains available if a CDN lies about Range support.
        Batch installs already parallelize files and do not enter this path.
        """
        count = min(4, self.workers)
        if count < 2:
            return False
        parts = [temporary.with_name(temporary.name + f'.{index}') for index in range(count)]
        received = [0] * count
        lock, stopped = threading.Lock(), threading.Event()
        last_progress = 0.0

        def transfer(index):
            nonlocal last_progress
            start, end = size * index // count, size * (index + 1) // count - 1
            request_headers = dict(headers, Range=f'bytes={start}-{end}')
            with _DownloadSession(getattr(self, 'curseforge_key', ''),
                                  getattr(self, 'curseforge_fallbacks', None)) as session:
                with session.get(url, stream=True, timeout=timeout, headers=request_headers) as response, \
                        self.cancel.response(response) if isinstance(self.cancel, DownloadCancellation) else nullcontext():
                    response.raise_for_status()
                    if (response.status_code != 206 or
                            response.headers.get('Content-Range') != f'bytes {start}-{end}/{size}' or
                            response.headers.get('Content-Encoding', 'identity') not in ('', 'identity')):
                        raise ValueError('下载源不支持分段下载')
                    with parts[index].open('wb') as output:
                        for chunk in _download_chunks(response, True):
                            self.check_cancelled()
                            if stopped.is_set():
                                return
                            if chunk:
                                output.write(chunk)
                                with lock:
                                    received[index] += len(chunk)
                                    if received[index] > end - start + 1:
                                        raise ValueError('分段长度超出预期')
                                    now = time.monotonic()
                                    if now - last_progress >= 0.15:
                                        done = sum(received)
                                        file_progress(done, size)
                                        self._file_event(relative, 'downloading', done=done, total=size)
                                        last_progress = now
                    if received[index] != end - start + 1:
                        raise ValueError('分段下载不完整')

        try:
            with ThreadPoolExecutor(max_workers=count, thread_name_prefix='content-range') as pool:
                futures = [pool.submit(transfer, index) for index in range(count)]
                try:
                    for future in as_completed(futures):
                        future.result()
                finally:
                    stopped.set()
            self.check_cancelled()
            with temporary.open('wb') as output:
                for part in parts:
                    with part.open('rb') as source:
                        for chunk in iter(lambda: source.read(1024 * 1024), b''):
                            self.check_cancelled()
                            output.write(chunk)
            logger.info('download_parallel file=%s connections=%s bytes=%s', relative, count, size)
            return True
        except DownloadCancelled:
            raise
        except (requests.RequestException, OSError, ValueError) as exc:
            logger.info('download_parallel_fallback file=%s reason=%s', relative, exc)
            return False
        finally:
            if self.cancel.is_set():
                # Range workers can finish out of order. Only a contiguous
                # prefix can be resumed by the ordinary HTTP Range request.
                try:
                    with temporary.open('wb') as output:
                        for index, part in enumerate(parts):
                            expected = size * (index + 1) // count - size * index // count
                            length = part.stat().st_size if part.is_file() else 0
                            if not 0 < length <= expected:
                                break
                            with part.open('rb') as source:
                                shutil.copyfileobj(source, output)
                            if length < expected:
                                break
                except OSError:
                    logger.warning('download_parallel_checkpoint_failed file=%s', relative, exc_info=True)
            for part in parts:
                part.unlink(missing_ok=True)

    def _fetch(self, url, relative, sha1=None, size=None, *, sha512=None, file_progress=None, _validate=None,
               _destination=None):
        """Download into a temporary file; never publish truncated files."""
        from utils.path_helper import filesystem_path
        destination = self.inside(relative) if _destination is None else _destination
        # Cache roots can be deep, especially inside loader workspaces. Use
        # extended paths for both the artifact and its longer checkpoint names.
        target = filesystem_path(destination)
        self.check_cancelled()
        def verified(path, *, structure=False):
            if size is not None and path.stat().st_size != size:
                return False
            digests = {name: hashlib.new(name) for name, value in (('sha1', sha1), ('sha512', sha512)) if value}
            with path.open('rb') as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    self.check_cancelled()
                    for digest in digests.values():
                        digest.update(chunk)
            valid = all(digest.hexdigest().lower() == {'sha1': sha1, 'sha512': sha512}[name].lower()
                        for name, digest in digests.items())
            if valid and structure and _validate:
                try:
                    _validate(path)
                except ValueError:
                    return False
            return valid

        if target.is_file() and (sha1 or sha512) and verified(target, structure=True):
            with self._verified_lock:
                self._verified[str(relative)] = sha1
            length = target.stat().st_size
            self._file_event(relative, 'cached', done=length, total=length, error='')
            if file_progress:
                file_progress(length, length)
            return destination
        errors = []
        source_errors = []
        failures = {}
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".buggcraft-part")
        checkpoint = temporary.with_name(temporary.name + '.json')
        identity = {'sha1': sha1, 'sha512': sha512}

        def discard_partial():
            temporary.unlink(missing_ok=True)
            checkpoint.unlink(missing_ok=True)

        # Hashes bind partial bytes to the requested file, across workers and
        # application restarts. Never append an unrelated old download.
        try:
            saved = json.loads(checkpoint.read_text(encoding='utf-8'))
            saved_size = saved.get('size')
            if (not (sha1 or sha512) or saved.get('identity') != identity
                    or not isinstance(saved_size, int) or saved_size <= 0
                    or size is not None and saved_size != size
                    or not temporary.is_file() or temporary.stat().st_size > saved_size):
                discard_partial()
            elif size is None:
                size = saved_size
        except (OSError, ValueError, TypeError, AttributeError):
            discard_partial()

        def save_checkpoint(total):
            if (sha1 or sha512) and total:
                checkpoint.write_text(json.dumps({'identity': identity, 'size': total}), encoding='utf-8')

        if temporary.is_file() and size and temporary.stat().st_size == size:
            self._file_event(relative, 'verifying', done=size, total=size)
            if verified(temporary, structure=True):
                os.replace(temporary, target)
                checkpoint.unlink(missing_ok=True)
                self._file_event(relative, 'verified', done=size, total=size)
                if file_progress:
                    file_progress(size, size)
                with self._verified_lock:
                    self._verified[str(relative)] = sha1
                return destination
            discard_partial()
        content_source = self.content_source or self.source
        addresses = [url, *getattr(self, 'file_mirrors', {}).get(url, [])]
        if self.resolve_content_sources:
            from core.content_routes import resolve_download_urls
            self.check_cancelled()
            self.status(f'正在解析下载源 · {target.name}')
            addresses = resolve_download_urls(addresses, sha1, size, sha512=sha512,
                                               preference=content_source, cancel=self.cancel)
        candidates = list(dict.fromkeys(candidate for address in addresses
                                        for candidate in self.urls(address)))
        if content_source in ('CurseForge', 'Modrinth', 'MCIM'):
            from core.content_routes import provider
            candidates.sort(key=lambda candidate: provider(candidate) != content_source)
            if candidates and provider(candidates[0]) != content_source:
                self.status(f'{content_source} 未找到相同文件，使用可用来源 · {target.name}')
                logger.info('content_source_unavailable file=%s preference=%s', relative, content_source)
        elif content_source != '官方' and any(
                urlsplit(candidate).hostname in ('mod.mcimirror.top', 'cdn.modrinth.com',
                                                 'edge.forgecdn.net', 'mediafilez.forgecdn.net')
                for candidate in candidates):
            candidates = _rank_content_candidates(candidates, content_source)
        attempt_number = 0
        max_attempts = self.retries + 1

        def available(candidate):
            host = urlsplit(candidate).hostname
            if host == urlsplit(CONTENT_MIRROR).hostname and _CONTENT_HEALTH.blocked():
                return False
            with self._blocked_hosts_lock:
                return self._blocked_hosts.get(host, 0) <= time.monotonic()

        for source_index, candidate in enumerate(candidates):
            host = urlsplit(candidate).hostname
            content_mirror = host == urlsplit(CONTENT_MIRROR).hostname
            if attempt_number >= max_attempts:
                continue
            if content_mirror and _CONTENT_HEALTH.blocked():
                from utils.download_address import source_name
                failures[source_name(candidate) or host] = '暂时不可用（此前请求失败）'
                continue
            with self._blocked_hosts_lock:
                if self._blocked_hosts.get(host, 0) > time.monotonic():
                    from utils.download_address import source_name
                    failures[source_name(candidate) or host] = '暂时不可用（此前请求失败）'
                    continue
            # Switch between configured sources without spending the retry
            # budget on a broken mirror; retry the last viable source.
            alternatives = candidates[source_index + 1:]
            attempts = 1 if any(available(item) for item in alternatives) else max_attempts - attempt_number
            for attempt in range(attempts):
                self.check_cancelled()
                attempt_number += 1
                try:
                    offset = temporary.stat().st_size if temporary.exists() and (sha1 or sha512) and size else 0
                    self._file_event(relative, 'downloading', done=offset, total=size or 0,
                                     host=host or '', url=candidate, attempt=attempt_number, error='')
                    self.status(f'正在下载 {target.name} · {urlsplit(candidate).hostname} · 第 {attempt_number} 次')
                    logger.info('download_start file=%s host=%s attempt=%s', relative, urlsplit(candidate).hostname, attempt_number)
                    session = getattr(self._sessions, 'session', None)
                    if session is None:
                        session = _DownloadSession(getattr(self, 'curseforge_key', ''),
                                                   getattr(self, 'curseforge_fallbacks', None))
                        self._sessions.session = session
                    headers = {"User-Agent": USER_AGENT, 'Accept-Encoding': 'identity',
                               **getattr(self, 'request_headers', {})}
                    if offset:
                        headers['Range'] = f'bytes={offset}-'
                    # A mirror is an accelerator, so it gets a short first-byte
                    # budget and one attempt before trying the publisher.
                    timeout = (3, 4) if content_mirror else (8, 30)
                    with session.get(candidate, stream=True, timeout=timeout, headers=headers) as response, \
                            self.cancel.response(response) if isinstance(self.cancel, DownloadCancellation) else nullcontext():
                        response.raise_for_status()
                        final_host = urlsplit(response.url).hostname if isinstance(response.url, str) else host
                        if isinstance(response.url, str) and response.url != candidate:
                            logger.info('download_redirect file=%s from=%s to=%s', relative, host, final_host)
                            self._file_event(relative, 'downloading', done=offset, total=size or 0,
                                             host=final_host or host or '', url=response.url,
                                             attempt=attempt_number, error='')
                        if content_mirror and str(response.headers.get('Content-Type', '')).split(';')[0].lower() in ('text/html', 'application/xhtml+xml'):
                            _CONTENT_HEALTH.pause()
                            raise ValueError('MCIM 暂时返回了网页，正在切换备用下载源')
                        if response.status_code == 206:
                            content_range = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', response.headers.get('Content-Range', ''))
                            if (not offset or not content_range or int(content_range[1]) != offset
                                    or int(content_range[3]) != size or int(content_range[2]) != size - 1):
                                discard_partial()
                                raise ValueError(f'断点续传响应无效：{target.name}')
                        else:
                            offset = 0  # A server may ignore Range and send the whole file.
                        downloaded = offset
                        transfer_total = int(size if size is not None else response.headers.get('Content-Length') or 0)
                        if size is None and (sha1 or sha512) and transfer_total > 0:
                            size = transfer_total
                        save_checkpoint(size)
                        if offset:
                            self.status(f'正在续传 {target.name} · 已下载 {offset:,} / {size:,} 字节')
                            if file_progress:
                                file_progress(offset, size)
                        last_progress = 0.0
                        transfer_started = time.monotonic()
                        window_bytes = offset
                        parallel = (self.workers > 1 and getattr(self, 'parallel_content', True) and file_progress is not None
                                    and size is not None and size >= 8 * 1024 * 1024
                                    and (sha1 or sha512) and not offset and response.status_code == 200
                                    and response.headers.get('Accept-Ranges', '').lower() == 'bytes'
                                    and host in ('mod.mcimirror.top', 'cdn.modrinth.com', 'edge.forgecdn.net', 'mediafilez.forgecdn.net')
                                    and response.headers.get('Content-Encoding', 'identity') in ('', 'identity'))
                        # A cache miss may redirect MCIM back to the publisher.
                        # Reuse that resolved CDN URL rather than repeat four redirects.
                        range_url = response.url if final_host in ('cdn.modrinth.com', 'edge.forgecdn.net', 'mediafilez.forgecdn.net') else candidate
                        segmented = parallel and self._parallel_content(range_url, temporary, size, headers, timeout, relative, file_progress)
                        if segmented:
                            downloaded = size
                            chunks = ()
                        else:
                            chunks = _download_chunks(response, content_mirror)
                        with temporary.open('ab' if offset or segmented else 'wb') as output:
                            for chunk in chunks:
                                self.check_cancelled()
                                if chunk:
                                    output.write(chunk)
                                    downloaded += len(chunk)
                                    if size is not None and downloaded > size:
                                        raise ValueError(f'文件长度超出预期：{target.name}')
                                    now = time.monotonic()
                                    if downloaded == size or now - last_progress >= 0.15:
                                        if file_progress:
                                            file_progress(downloaded, transfer_total)
                                        self._file_event(relative, 'downloading', done=downloaded, total=transfer_total)
                                        last_progress = now
                                    elapsed = now - transfer_started
                                    if (content_mirror and elapsed >= 4 and downloaded != size
                                            and any(available(item) for item in alternatives)):
                                        if (downloaded - window_bytes) / elapsed < 64 * 1024:
                                            raise _SlowMirror('镜像传输速度过低')
                                        transfer_started, window_bytes = now, downloaded
                        expected = size if size is not None else response.headers.get("Content-Length")
                        if expected is not None and downloaded != int(expected):
                            raise requests.ConnectionError(f"文件下载中断：{target.name}，重试时继续下载")
                        self._file_event(relative, 'verifying', done=downloaded, total=downloaded)
                        if (sha1 or sha512) and not verified(temporary):
                            raise ValueError(f"文件校验失败：{target.name}")
                        if _validate:
                            _validate(temporary)
                    os.replace(temporary, target)
                    checkpoint.unlink(missing_ok=True)
                    self._file_event(relative, 'verified', done=downloaded, total=downloaded, host=final_host or host or '')
                    if file_progress:
                        file_progress(downloaded, downloaded)
                    logger.info('download_complete file=%s host=%s final_host=%s bytes=%s', relative, host, final_host, downloaded)
                    if file_progress:
                        self.status(f'已下载并校验 {target.name} · {final_host or host} · {downloaded} 字节')
                    with self._verified_lock:
                        self._verified[str(relative)] = sha1
                    return destination
                except DownloadCancelled:
                    if not (sha1 or sha512) or not size:
                        discard_partial()
                    raise
                except (requests.RequestException, OSError, ValueError) as exc:
                    retryable = isinstance(exc, (requests.ConnectionError, requests.Timeout,
                                                  requests.exceptions.ChunkedEncodingError)) or (
                        isinstance(exc, requests.HTTPError) and exc.response is not None
                        and exc.response.status_code in (408, 429, 500, 502, 503, 504))
                    # A source or a later attempt may still succeed; only the
                    # terminal failed event should surface an error in the UI.
                    self._file_event(relative, 'retrying', error='')
                    if isinstance(exc, OSError) and not isinstance(exc, requests.RequestException):
                        raise
                    errors.append(str(exc))
                    source_errors.append(exc)
                    from utils.download_address import source_name
                    failures[source_name(candidate) or host or '下载源'] = _source_failure_reason(exc)
                    logger.warning('download_retry file=%s host=%s attempt=%s error=%s', relative,
                                   urlsplit(candidate).hostname, attempt_number, exc)
                    # A rejected source cannot invalidate bytes bound to the
                    # expected hash. Bad ranges, hashes and disk errors do.
                    transient = isinstance(exc, (requests.ConnectionError, requests.Timeout,
                                                 requests.exceptions.ChunkedEncodingError, requests.HTTPError))
                    if not transient or not (sha1 or sha512) or not size:
                        discard_partial()
                    self.check_cancelled()
                    if content_mirror:
                        # Transport, stale-cache, HTTP and hash failures all
                        # fall through to the original URL, without repeatedly
                        # stalling the other files in this download task.
                        missing = (isinstance(exc, requests.HTTPError) and exc.response is not None
                                   and exc.response.status_code in (404, 410))
                        switch = any(available(item) for item in alternatives)
                        if not missing and (switch or not retryable or attempt == attempts - 1):
                            with self._blocked_hosts_lock:
                                self._blocked_hosts[host] = time.monotonic() + 60
                            if isinstance(exc, (requests.ConnectionError, requests.Timeout)) or (
                                    isinstance(exc, requests.HTTPError) and exc.response is not None
                                    and exc.response.status_code in (403, 429, 500, 502, 503, 504, 567)):
                                _CONTENT_HEALTH.pause()
                        if switch:
                            self.status(f'镜像 {host} 暂不可用或速度过低，正在切换原站继续下载 {target.name}')
                        elif not retryable or attempt == attempts - 1:
                            self.status(f'镜像 {host} 也暂不可用：{target.name}')
                        if switch or not retryable:
                            logger.info('download_source_switch file=%s from=%s reason=%s', relative, host, exc)
                            break
                    if isinstance(exc, requests.HTTPError) and exc.response is not None and exc.response.status_code in (403, 567):
                        # A rejected mirror should not delay every file in a pack.
                        with self._blocked_hosts_lock:
                            self._blocked_hosts[host] = time.monotonic() + 60
                        self.status(f'下载源 {host} 拒绝访问（HTTP {exc.response.status_code}），正在切换备用来源')
                        break
                    if (isinstance(exc, requests.HTTPError) and exc.response is not None
                            and 400 <= exc.response.status_code < 500
                            and exc.response.status_code not in (408, 429)):
                        # Missing cache entries and permanent client errors will
                        # not improve by retrying the same URL immediately.
                        break
                    if not retryable and attempt >= 2:
                        break
                    if attempt < attempts - 1 and self.cancel.wait(0.5 * (attempt + 1)):
                        self.check_cancelled()
        if not failures:
            for candidate in candidates:
                from utils.download_address import source_name
                failures[source_name(candidate) or '下载源'] = '暂时不可用（此前请求失败）'
        summary = '；'.join(f'{name}：{reason}' for name, reason in failures.items())
        raise DownloadSourcesExhausted(
            f'下载 {target.name} 失败：全部可用下载源均失败。{summary}。已下载进度保留，可稍后重试。',
            source_errors=source_errors)

    def fetch_json(self, url, relative, sha1=None, size=None, *, label='下载信息', valid=None):
        data = None

        def validate(path):
            nonlocal data
            try:
                data = json.loads(path.read_text(encoding='utf-8-sig'))
                if not isinstance(data, dict) or valid and not valid(data):
                    raise ValueError('unexpected metadata structure')
            except (ValueError, UnicodeDecodeError, KeyError, TypeError, AttributeError) as exc:
                logger.warning('download_metadata_invalid file=%s label=%s error=%s', relative, label, exc)
                raise ValueError(f'{label}不完整或格式错误（{Path(relative).name}），请重试或更换下载源。') from exc

        self.fetch(url, relative, sha1, size, _validate=validate)
        return data

    def manifest(self):
        self.status("正在获取 Minecraft 版本列表…")
        # Fetch to a per-request name so opening a list cannot race an install.
        import uuid
        relative = f".buggcraft-downloads/manifest-{uuid.uuid4().hex}.json"
        try:
            return self.fetch_json(MANIFEST_URL, relative, label='Minecraft 版本列表',
                                   valid=lambda value: isinstance(value.get('versions'), list))
        finally:
            self.inside(relative).unlink(missing_ok=True)

    def allowed(self, rules):
        if not rules:
            return True
        allowed = False
        for rule in rules:
            os_rule = rule.get("os", {})
            if os_rule.get("name", self.system) != self.system:
                continue
            if "version" in os_rule and not re.search(os_rule["version"], platform.version()):
                continue
            if "arch" in os_rule and not re.search(os_rule["arch"], platform.machine()):
                continue
            if any(value is not False for value in rule.get("features", {}).values()):
                continue
            allowed = rule.get("action") == "allow"
        return allowed

    def _batch(self, jobs, label, *, workers=None):
        # Dedupe shared objects before scheduling to avoid competing file writers.
        jobs = list({str(job[1]): job for job in jobs}.values())
        self.status(label)
        self.progress(0, len(jobs))
        if not jobs:
            return
        workers = self.workers if workers is None else normalize_concurrency(workers)
        # Batch workers already parallelize files; do not multiply each worker
        # into additional range transfers.
        self.parallel_content = False
        with ThreadPoolExecutor(max_workers=min(workers, len(jobs)), thread_name_prefix="minecraft-download") as pool:
            remaining = iter(jobs)
            pending = set()

            def refill():
                try:
                    job = next(remaining)
                except StopIteration:
                    return
                pending.add(pool.submit(self.fetch, *job))

            for _ in range(min(workers, len(jobs))):
                refill()
            try:
                completed = 0
                while pending:
                    done, _ = wait(pending, return_when=FIRST_COMPLETED)
                    for future in done:
                        pending.remove(future)
                        future.result()
                        self.check_cancelled()
                        completed += 1
                        self.progress(completed, len(jobs))
                        refill()
            except BaseException:
                for future in pending:
                    future.cancel()
                self.cancel.set()
                raise

    def install(self, version, *, identity=None):
        from core.modpacks import instance_name
        identity = instance_name(identity or version)
        instance_name(version)
        with download_lock(self.inside(f'versions/{identity}/.buggcraft-install'), self.cancel):
            return self._install(version, identity=identity)

    def _install(self, version, *, identity=None):
        self.status(f"正在准备 Minecraft {version}…")
        manifest = self.manifest()
        entry = next((item for item in manifest["versions"] if item["id"] == version), None)
        if entry is None:
            raise ValueError(f"未找到 Minecraft {version}")
        metadata = self.fetch_json(entry['url'], f'.buggcraft-downloads/{version}.json', entry.get('sha1'),
                                   label=f'Minecraft {version} 版本信息', valid=lambda value: value.get('id') == version)

        identity = identity or version
        if identity != version:
            metadata = dict(metadata, id=identity, clientVersion=version)
        self.install_metadata(identity, metadata)

    def install_metadata(self, version, metadata, *, preserve_client=False):
        """Repair a resolved local instance without looking up its display name."""
        if metadata.get('id') != version or not metadata.get('downloads', {}).get('client'):
            raise ValueError('实例缺少游戏核心下载信息')

        library_jobs, natives = [], []
        for library in metadata.get("libraries", []):
            if not self.allowed(library.get("rules")):
                continue
            downloads = library.get("downloads", {})
            artifact = downloads.get("artifact")
            if artifact and artifact.get("url"):
                library_jobs.append((artifact["url"], "libraries/" + artifact["path"], artifact.get("sha1"), artifact.get("size")))
            classifier = library.get("natives", {}).get(self.system)
            if classifier:
                classifier = classifier.replace("${arch}", "64" if platform.architecture()[0] == "64bit" else "32")
                native = downloads.get("classifiers", {}).get(classifier)
                if not native:
                    raise ValueError(f"缺少本机依赖：{library.get('name')}")
                relative = "libraries/" + native["path"]
                library_jobs.append((native["url"], relative, native.get("sha1"), native.get("size")))
                natives.append(relative)
        client = metadata["downloads"]["client"]
        client_relative = f"versions/{version}/{version}.jar"
        if preserve_client:
            # Loader and room JARs may be patched even when their resolved
            # metadata still carries the vanilla client download URL.
            existing_client = self.inside(client_relative)
            if not existing_client.is_file():
                raise FileNotFoundError('缺少游戏核心文件，请重新安装此游戏版本：' + str(existing_client))
            try:
                with zipfile.ZipFile(existing_client) as archive:
                    if not archive.infolist():
                        raise ValueError('游戏核心文件为空')
            except (OSError, zipfile.BadZipFile) as exc:
                raise ValueError('游戏核心文件已损坏，请重新安装此游戏版本') from exc
            with self._verified_lock:
                self._verified[client_relative] = _sha1(existing_client)
            jobs = []
        else:
            jobs = [(client["url"], client_relative, client.get("sha1"), client.get("size"))]
        logging = metadata.get("logging", {}).get("client", {}).get("file")
        if logging:
            jobs.append((logging["url"], "assets/log_configs/" + logging["id"], logging.get("sha1"), logging.get("size")))
        index = metadata.get("assetIndex")
        asset_jobs = []
        if index:
            assets = self.fetch_json(index['url'], 'assets/indexes/' + index['id'] + '.json',
                                     index.get('sha1'), index.get('size'), label='游戏资源索引',
                                     valid=lambda value: isinstance(value.get('objects'), dict))
            objects = assets["objects"]
            self.file_names.update({f"assets/objects/{obj['hash'][:2]}/{obj['hash']}": name
                                    for name, obj in objects.items()})
            asset_jobs = [
                (f"https://resources.download.minecraft.net/{obj['hash'][:2]}/{obj['hash']}",
                 f"assets/objects/{obj['hash'][:2]}/{obj['hash']}", obj["hash"], obj.get("size"))
                for obj in objects.values()
            ]
        # Interleave both hosts so the first 32 slots include game, libraries
        # and assets instead of letting a long library list starve assets.
        for position in range(max(len(library_jobs), len(asset_jobs))):
            if position < len(library_jobs):
                jobs.append(library_jobs[position])
            if position < len(asset_jobs):
                jobs.append(asset_jobs[position])
        self._batch(jobs, "正在并行下载游戏核心、依赖库和资源…")
        if index:
            # Early Minecraft versions look up assets by their logical names.
            if assets.get("virtual") or assets.get("map_to_resources"):
                import shutil
                for name, obj in objects.items():
                    self.check_cancelled()
                    source = self.inside(f"assets/objects/{obj['hash'][:2]}/{obj['hash']}")
                    roots = []
                    if assets.get("virtual"):
                        roots.append("assets/virtual/" + index["id"])
                    if assets.get("map_to_resources"):
                        roots.append("resources")
                    for root in roots:
                        destination = self.inside(root + "/" + name)
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(source, destination)

        self.status("正在完成安装并校验本机依赖…")
        for relative in natives:
            self.check_cancelled()
            with zipfile.ZipFile(self.inside(relative)) as archive:
                extract_zip(archive, self.inside(f"versions/{version}/natives"))
        natives_root = self.inside(f"versions/{version}/natives")
        if natives_root.is_dir():
            for path in natives_root.rglob('*'):
                if path.is_file() and not _temporary_jna_native(str(path.relative_to(self.root)), version):
                    self._verified[str(path.relative_to(self.root))] = _sha1(path)
        self.check_cancelled()
        # Publish the version only after every required file has passed validation.
        destination = self.inside(f"versions/{version}/{version}.json")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".json.buggcraft-part")
        temporary.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, destination)
        receipt = {
            'version': version,
            'files': [{'path': relative, 'sha1': sha1} for relative, sha1 in self._verified.items()
                      if not relative.startswith('.buggcraft-downloads')],
        }
        receipt['files'].append({'path': str(destination.relative_to(self.root)), 'sha1': _sha1(destination)})
        receipt_path = destination.parent / '.buggcraft-complete.json'
        receipt_tmp = receipt_path.with_suffix('.tmp')
        receipt_tmp.write_text(json.dumps(receipt), encoding='utf-8')
        os.replace(receipt_tmp, receipt_path)
        self.status("安装完成")
