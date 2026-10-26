"""Verified Minecraft downloads without UI dependencies or global HTTP patches."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import re
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlsplit

import requests
from urllib3.exceptions import HTTPError as TransportError
from urllib3.response import HTTPResponse

from utils.archives import extract_zip
from utils.download_locks import download_lock
from utils.http_identity import USER_AGENT


MANIFEST_URL = "https://launchermeta.mojang.com/mc/game/version_manifest_v2.json"
MIRROR = "https://bmclapi2.bangbang93.com"
CONTENT_MIRROR = 'https://mod.mcimirror.top'
logger = logging.getLogger(__name__)


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


class _SlowMirror(requests.ConnectionError):
    """Keep verified-size partial data when switching away from a slow mirror."""


def _download_chunks(response, mirror):
    # read1 yields currently available bytes. iter_content waits to fill its
    # buffer, hiding a server that keeps the socket alive with tiny trickles.
    if mirror and isinstance(response.raw, HTTPResponse) and hasattr(response.raw, 'read1'):
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
            target = _resolved(root / item['path'])
            if not target.is_relative_to(root) or not target.is_file():
                return False
            if item.get('sha1') and _sha1(target) != item['sha1']:
                return False
        return True
    except (OSError, ValueError, KeyError, TypeError):
        return False


class MinecraftDownloader:
    def __init__(self, directory, source="自动", cancel=None, status=None, progress=None, file_event=None):
        self.root = _resolved(directory)
        self.source = source
        self.content_source = None
        self.cancel = cancel if cancel is not None else threading.Event()
        self.status = status or (lambda message: None)
        self.progress = progress or (lambda current, maximum: None)
        self.file_event = file_event
        self.file_names = {}
        self._sessions = threading.local()
        self._verified = {}
        self._verified_lock = threading.Lock()
        self._blocked_hosts = {}
        self._blocked_hosts_lock = threading.Lock()
        self.system = {"Windows": "windows", "Darwin": "osx"}.get(platform.system(), "linux")

    def check_cancelled(self):
        if self.cancel.is_set():
            raise DownloadCancelled("下载已取消，已校验文件会保留，重试时继续使用")

    def urls(self, original):
        parsed = urlsplit(original)
        # MCIM serves content files; BMCLAPI serves the game and its libraries.
        # Both settings share this router, including every URL in an MRPACK.
        trusted = (parsed.scheme == 'https' and parsed.port in (None, 443)
                   and not parsed.username and not parsed.password)
        # Some cached manifests already contain mirror URLs. Recover the
        # publisher route too, otherwise fallback silently has no alternative.
        if trusted and parsed.hostname == urlsplit(CONTENT_MIRROR).hostname:
            upstream = ('cdn.modrinth.com' if parsed.path.startswith('/data/') else
                        'edge.forgecdn.net' if parsed.path.startswith('/files/') else None)
            if upstream:
                return self.urls(parsed._replace(netloc=upstream).geturl())
        if trusted and parsed.hostname in ('cdn.modrinth.com', 'edge.forgecdn.net', 'mediafilez.forgecdn.net'):
            originals = [original]
            if parsed.hostname in ('edge.forgecdn.net', 'mediafilez.forgecdn.net'):
                alternate = 'mediafilez.forgecdn.net' if parsed.hostname == 'edge.forgecdn.net' else 'edge.forgecdn.net'
                originals.append(parsed._replace(netloc=alternate).geturl())
            content_source = self.content_source or self.source
            if content_source == '官方':
                return originals
            # The MCIM guide explicitly excludes mediafilez from rewriting.
            if parsed.hostname == 'mediafilez.forgecdn.net':
                return originals
            return [parsed._replace(netloc=urlsplit(CONTENT_MIRROR).netloc).geturl(), *originals]
        replacements = {
            "launchermeta.mojang.com": "",
            "piston-meta.mojang.com": "",
            "launcher.mojang.com": "",
            "piston-data.mojang.com": "",
            "resources.download.minecraft.net": "/assets",
            "libraries.minecraft.net": "/maven",
        }
        if parsed.hostname not in replacements or self.source == "官方":
            return [original]
        mirror = MIRROR + replacements[parsed.hostname] + parsed.path
        if parsed.query:
            mirror += "?" + parsed.query
        return [mirror, original] if self.source == "BMCLAPI" else [original, mirror]

    def inside(self, relative):
        target = _resolved(self.root / relative)
        if target == self.root or not target.is_relative_to(self.root):
            raise ValueError(f"下载路径超出游戏目录：{relative} ({target!s}; root={self.root!s})")
        return target

    def fetch(self, url, relative, sha1=None, size=None, *, sha512=None, file_progress=None):
        self._file_event(relative, 'pending', total=size or 0)
        try:
            with download_lock(self.inside(relative), self.cancel):
                return self._fetch(url, relative, sha1, size, sha512=sha512, file_progress=file_progress)
        except (DownloadCancelled, InterruptedError):
            self._file_event(relative, 'cancelled')
            raise
        except Exception as exc:
            self._file_event(relative, 'failed', error=str(exc))
            raise

    def _file_event(self, relative, state, **values):
        if self.file_event:
            path = Path(relative).as_posix()
            self.file_event(dict(key=str(self.root / relative), path=path,
                                 name=self.file_names.get(path, Path(relative).name), state=state, **values))

    def _parallel_content(self, url, temporary, size, headers, timeout, relative, file_progress):
        """Use four bounded ranges for large individual files; verify after joining.

        The original response remains available if a CDN lies about Range support.
        Batch installs already parallelize files and do not enter this path.
        """
        parts = [temporary.with_name(temporary.name + f'.{index}') for index in range(4)]
        received = [0] * 4
        lock, stopped = threading.Lock(), threading.Event()
        last_progress = 0.0

        def transfer(index):
            nonlocal last_progress
            start, end = size * index // 4, size * (index + 1) // 4 - 1
            request_headers = dict(headers, Range=f'bytes={start}-{end}')
            with _DownloadSession(getattr(self, 'curseforge_key', ''),
                                  getattr(self, 'curseforge_fallbacks', None)) as session:
                with session.get(url, stream=True, timeout=timeout, headers=request_headers) as response:
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
            with ThreadPoolExecutor(max_workers=4, thread_name_prefix='content-range') as pool:
                futures = [pool.submit(transfer, index) for index in range(4)]
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
            logger.info('download_parallel file=%s connections=4 bytes=%s', relative, size)
            return True
        except DownloadCancelled:
            raise
        except (requests.RequestException, OSError, ValueError) as exc:
            logger.info('download_parallel_fallback file=%s reason=%s', relative, exc)
            return False
        finally:
            for part in parts:
                part.unlink(missing_ok=True)

    def _fetch(self, url, relative, sha1=None, size=None, *, sha512=None, file_progress=None):
        """Download into a temporary file; never publish truncated files."""
        target = self.inside(relative)
        self.check_cancelled()
        def verified(path):
            if size is not None and path.stat().st_size != size:
                return False
            digests = {name: hashlib.new(name) for name, value in (('sha1', sha1), ('sha512', sha512)) if value}
            with path.open('rb') as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    self.check_cancelled()
                    for digest in digests.values():
                        digest.update(chunk)
            return all(digest.hexdigest().lower() == {'sha1': sha1, 'sha512': sha512}[name].lower()
                       for name, digest in digests.items())

        if target.is_file() and (sha1 or sha512) and verified(target):
            with self._verified_lock:
                self._verified[str(target.relative_to(self.root))] = sha1
            length = target.stat().st_size
            self._file_event(relative, 'cached', done=length, total=length, error='')
            if file_progress:
                file_progress(length, length)
            return target
        errors = []
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".buggcraft-part")
        candidates = list(dict.fromkeys(candidate for address in [url, *getattr(self, 'file_mirrors', {}).get(url, [])]
                                        for candidate in self.urls(address)))
        if (self.content_source or self.source) != '官方':
            # Try all supplied domestic mirrors before falling back overseas.
            candidates.sort(key=lambda value: urlsplit(value).hostname != urlsplit(CONTENT_MIRROR).hostname)
        for candidate in candidates:
            host = urlsplit(candidate).hostname
            content_mirror = host == urlsplit(CONTENT_MIRROR).hostname
            if content_mirror and _CONTENT_HEALTH.blocked():
                continue
            with self._blocked_hosts_lock:
                if self._blocked_hosts.get(host, 0) > time.monotonic():
                    continue
            attempts = 1 if content_mirror else 3
            for attempt in range(attempts):
                if self.cancel.is_set():
                    temporary.unlink(missing_ok=True)
                self.check_cancelled()
                try:
                    self._file_event(relative, 'downloading', done=0, total=size or 0,
                                     host=host or '', attempt=attempt + 1, error='')
                    self.status(f'正在下载 {target.name} · {urlsplit(candidate).hostname} · 第 {attempt + 1} 次')
                    logger.info('download_start file=%s host=%s attempt=%s', relative, urlsplit(candidate).hostname, attempt + 1)
                    session = getattr(self._sessions, 'session', None)
                    if session is None:
                        session = _DownloadSession(getattr(self, 'curseforge_key', ''),
                                                   getattr(self, 'curseforge_fallbacks', None))
                        self._sessions.session = session
                    offset = temporary.stat().st_size if temporary.exists() and (sha1 or sha512) and size else 0
                    headers = {"User-Agent": USER_AGENT, 'Accept-Encoding': 'identity',
                               **getattr(self, 'request_headers', {})}
                    if offset:
                        headers['Range'] = f'bytes={offset}-'
                    # A mirror is an accelerator, so it gets a short first-byte
                    # budget and one attempt before trying the publisher.
                    timeout = (3, 4) if content_mirror else (8, 30)
                    with session.get(candidate, stream=True, timeout=timeout, headers=headers) as response:
                        response.raise_for_status()
                        final_host = urlsplit(response.url).hostname if isinstance(response.url, str) else host
                        if content_mirror and str(response.headers.get('Content-Type', '')).split(';')[0].lower() in ('text/html', 'application/xhtml+xml'):
                            _CONTENT_HEALTH.pause()
                            raise ValueError('MCIM 暂时返回了网页，正在切换备用下载源')
                        if response.status_code == 206:
                            content_range = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', response.headers.get('Content-Range', ''))
                            if (not offset or not content_range or int(content_range[1]) != offset
                                    or int(content_range[3]) != size or int(content_range[2]) != size - 1):
                                temporary.unlink(missing_ok=True)
                                raise ValueError(f'断点续传响应无效：{target.name}')
                        else:
                            offset = 0  # A server may ignore Range and send the whole file.
                        downloaded = offset
                        transfer_total = int(size if size is not None else response.headers.get('Content-Length') or 0)
                        last_progress = 0.0
                        transfer_started = time.monotonic()
                        window_bytes = offset
                        parallel = (file_progress is not None and size is not None and size >= 8 * 1024 * 1024
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
                                    if content_mirror and elapsed >= 4 and downloaded != size:
                                        if (downloaded - window_bytes) / elapsed < 64 * 1024:
                                            raise _SlowMirror('镜像持续低速，切换原站并继续下载')
                                        transfer_started, window_bytes = now, downloaded
                        expected = size if size is not None else response.headers.get("Content-Length")
                        if expected is not None and downloaded != int(expected):
                            raise ValueError(f"文件长度不完整：{target.name}")
                        self._file_event(relative, 'verifying', done=downloaded, total=downloaded)
                        if (sha1 or sha512) and not verified(temporary):
                            raise ValueError(f"文件校验失败：{target.name}")
                    os.replace(temporary, target)
                    self._file_event(relative, 'verified', done=downloaded, total=downloaded, host=final_host or host or '')
                    if file_progress:
                        file_progress(downloaded, downloaded)
                    logger.info('download_complete file=%s host=%s final_host=%s bytes=%s', relative, host, final_host, downloaded)
                    if file_progress:
                        self.status(f'已下载并校验 {target.name} · {final_host or host} · {downloaded} 字节')
                    with self._verified_lock:
                        self._verified[str(target.relative_to(self.root))] = sha1
                    return target
                except DownloadCancelled:
                    temporary.unlink(missing_ok=True)
                    raise
                except (requests.RequestException, OSError, ValueError) as exc:
                    self._file_event(relative, 'retrying', error=str(exc))
                    errors.append(str(exc))
                    logger.warning('download_retry file=%s host=%s attempt=%s error=%s', relative,
                                   urlsplit(candidate).hostname, attempt + 1, exc)
                    # Only transport interruptions retain a verified-size partial;
                    # bad hashes, disk errors and HTTP errors restart cleanly.
                    if not isinstance(exc, (requests.ConnectionError, requests.Timeout, requests.exceptions.ChunkedEncodingError)):
                        temporary.unlink(missing_ok=True)
                    if self.cancel.is_set():
                        temporary.unlink(missing_ok=True)
                    self.check_cancelled()
                    if content_mirror:
                        # Transport, stale-cache, HTTP and hash failures all
                        # fall through to the original URL, without repeatedly
                        # stalling the other files in this download task.
                        missing = (isinstance(exc, requests.HTTPError) and exc.response is not None
                                   and exc.response.status_code in (404, 410))
                        if not missing:
                            with self._blocked_hosts_lock:
                                self._blocked_hosts[host] = time.monotonic() + 60
                            if isinstance(exc, (requests.ConnectionError, requests.Timeout)) or (
                                    isinstance(exc, requests.HTTPError) and exc.response is not None
                                    and exc.response.status_code in (403, 429, 500, 502, 503, 504, 567)):
                                _CONTENT_HEALTH.pause()
                        self.status(f'镜像 {host} 暂不可用或速度过低，正在切换原站继续下载 {target.name}')
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
                    if attempt < attempts - 1 and self.cancel.wait(0.5 * (attempt + 1)):
                        temporary.unlink(missing_ok=True)
                        self.check_cancelled()
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"下载 {target.name} 失败：{errors[-1] if errors else url}")

    def manifest(self):
        self.status("正在获取 Minecraft 版本列表…")
        # Fetch to a per-request name so opening a list cannot race an install.
        import uuid
        path = self.fetch(MANIFEST_URL, f".buggcraft-downloads/manifest-{uuid.uuid4().hex}.json")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data.get("versions"), list):
                raise ValueError("版本列表格式不正确")
            return data
        finally:
            path.unlink(missing_ok=True)

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

    def _batch(self, jobs, label):
        # Dedupe shared objects before scheduling to avoid competing file writers.
        jobs = list({str(job[1]): job for job in jobs}.values())
        self.status(label)
        self.progress(0, len(jobs))
        if not jobs:
            return
        with ThreadPoolExecutor(max_workers=8, thread_name_prefix="minecraft-download") as pool:
            futures = [pool.submit(self.fetch, *job) for job in jobs]
            try:
                for completed, future in enumerate(as_completed(futures), 1):
                    future.result()
                    self.check_cancelled()
                    self.progress(completed, len(jobs))
            except BaseException:
                for future in futures:
                    future.cancel()
                self.cancel.set()
                raise

    def install(self, version):
        if not version or version in (".", "..") or any(c in version for c in '/\\:'):
            raise ValueError("无效的游戏版本")
        with download_lock(self.inside(f'versions/{version}/.buggcraft-install'), self.cancel):
            return self._install(version)

    def _install(self, version):
        self.status(f"正在准备 Minecraft {version}…")
        manifest = self.manifest()
        entry = next((item for item in manifest["versions"] if item["id"] == version), None)
        if entry is None:
            raise ValueError(f"未找到 Minecraft {version}")
        metadata_path = self.fetch(entry["url"], f".buggcraft-downloads/{version}.json", entry.get("sha1"))
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata.get("id") != version:
            raise ValueError("版本元数据与所选版本不一致")

        self.install_metadata(version, metadata)

    def install_metadata(self, version, metadata):
        """Repair a resolved local instance without looking up its display name."""
        if metadata.get('id') != version or not metadata.get('downloads', {}).get('client'):
            raise ValueError('实例缺少游戏核心下载信息')

        jobs, natives = [], []
        for library in metadata.get("libraries", []):
            if not self.allowed(library.get("rules")):
                continue
            downloads = library.get("downloads", {})
            artifact = downloads.get("artifact")
            if artifact and artifact.get("url"):
                jobs.append((artifact["url"], "libraries/" + artifact["path"], artifact.get("sha1"), artifact.get("size")))
            classifier = library.get("natives", {}).get(self.system)
            if classifier:
                classifier = classifier.replace("${arch}", "64" if platform.architecture()[0] == "64bit" else "32")
                native = downloads.get("classifiers", {}).get(classifier)
                if not native:
                    raise ValueError(f"缺少本机依赖：{library.get('name')}")
                relative = "libraries/" + native["path"]
                jobs.append((native["url"], relative, native.get("sha1"), native.get("size")))
                natives.append(relative)
        client = metadata["downloads"]["client"]
        jobs.append((client["url"], f"versions/{version}/{version}.jar", client.get("sha1"), client.get("size")))
        logging = metadata.get("logging", {}).get("client", {}).get("file")
        if logging:
            jobs.append((logging["url"], "assets/log_configs/" + logging["id"], logging.get("sha1"), logging.get("size")))
        self._batch(jobs, "正在下载游戏客户端和依赖库…")

        index = metadata.get("assetIndex")
        if index:
            index_path = self.fetch(index["url"], "assets/indexes/" + index["id"] + ".json", index.get("sha1"), index.get("size"))
            assets = json.loads(index_path.read_text(encoding="utf-8"))
            objects = assets["objects"]
            self.file_names.update({f"assets/objects/{obj['hash'][:2]}/{obj['hash']}": name
                                    for name, obj in objects.items()})
            self._batch([
                (f"https://resources.download.minecraft.net/{obj['hash'][:2]}/{obj['hash']}",
                 f"assets/objects/{obj['hash'][:2]}/{obj['hash']}", obj["hash"], obj.get("size"))
                for obj in objects.values()
            ], "正在下载游戏资源…")
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
                if path.is_file():
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
