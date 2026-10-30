"""Version discovery and installation for supported Java Edition loaders."""
from __future__ import annotations

from contextlib import contextmanager, nullcontext
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
import hashlib
import logging
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

import minecraft_launcher_lib
import requests

from core.downloads import MinecraftDownloader, use_download_budget, verified_installation
from utils.download_locks import download_lock
from utils.http_identity import USER_AGENT
from utils.path_helper import filesystem_path


BMCLAPI = "https://bmclapi2.bangbang93.com"
_MAVEN_MIRROR = BMCLAPI + "/maven"
_PATCH_LOCK = threading.RLock()
logger = logging.getLogger(__name__)


class _QuietSubprocess:
    """Local facade for dependency installers; never patch global subprocess."""
    def __init__(self, original, cancel=None):
        self.original = original
        self.cancel = cancel

    def __getattr__(self, name):
        return getattr(self.original, name)

    def Popen(self, command, *args, **kwargs):
        if self.cancel is not None and self.cancel.is_set():
            raise InterruptedError('安装已取消')
        if os.name == 'nt':
            kwargs['creationflags'] = kwargs.get('creationflags', 0) | subprocess.CREATE_NO_WINDOW
        kwargs.setdefault('stdin', subprocess.DEVNULL)
        return self.original.Popen(command, *args, **kwargs)

    def check_output(self, command, **kwargs):
        kwargs.pop('check', None)
        kwargs['stdout'] = subprocess.PIPE
        return self.run(command, **kwargs).stdout

    def check_call(self, command, **kwargs):
        self.run(command, **kwargs)
        return 0

    def call(self, command, **kwargs):
        kwargs['check'] = False
        return self.run(command, **kwargs).returncode

    def run(self, command, **kwargs):
        if self.cancel is not None and self.cancel.is_set():
            raise InterruptedError('安装已取消')
        if os.name == 'nt':
            kwargs['creationflags'] = kwargs.get('creationflags', 0) | subprocess.CREATE_NO_WINDOW
        kwargs.setdefault('stdin', subprocess.DEVNULL)
        # Forge processors previously inherited the console and ignored failures.
        if not kwargs.get('capture_output'):
            kwargs.setdefault('stdout', subprocess.PIPE)
            kwargs.setdefault('stderr', subprocess.STDOUT)
        kwargs.setdefault('check', True)
        try:
            result = self.original.run(command, **kwargs)
        except subprocess.CalledProcessError as exc:
            output = exc.stdout or exc.stderr or ''
            if isinstance(output, bytes):
                output = output.decode('utf-8', errors='replace')
            logger.error('Installer processor failed: exit=%s\n%s', exc.returncode, output[-12000:])
            raise RuntimeError(f'依赖处理器运行失败（退出码 {exc.returncode}）：{output[-2000:]}') from exc
        if result.stdout:
            output = result.stdout.decode('utf-8', errors='replace') if isinstance(result.stdout, bytes) else str(result.stdout)
            logger.info('Installer processor output:\n%s', output[-12000:])
        return result


def _source_mode(source):
    if source == "官方":
        return "official"
    if source == "BMCLAPI":
        return "mirror"
    if source == "自动（官方优先，失败切换镜像）":
        return "official_first"
    return "auto"


def _source_urls(source, official, mirror):
    from core.game_sources import source_urls
    return source_urls(source, official, mirror)


def _response(url):
    response = requests.get(url, timeout=(8, 20), headers={"User-Agent": USER_AGENT})
    try:
        response.raise_for_status()
    except Exception:
        response.close()
        raise
    return response


def _json_versions(url):
    value = _response_json(url, '加载器版本列表')
    if not isinstance(value, list):
        raise ValueError("加载器版本服务返回了无效数据")
    return value


def _response_json(url, label):
    response = _response(url)
    try:
        return response.json()
    except (ValueError, UnicodeDecodeError) as exc:
        logger.warning('loader_metadata_invalid url=%s error=%s', url, exc)
        raise ValueError(label + '不完整或格式错误，请重试或更换下载源。') from exc
    finally:
        close = getattr(response, 'close', None)
        if close:
            close()


def _maven_versions(url):
    response = _response(url)
    try:
        root = ET.fromstring(response.content)
        return [node.text for node in root.findall("./versioning/versions/version") if node.text]
    finally:
        response.close()


def _load_records(label, candidates, normalize, minecraft_version):
    errors = []
    for url, load in candidates:
        try:
            versions = normalize(load(url))
            if versions:
                return versions
            logger.warning('loader_catalogue_empty loader=%s game=%s url=%s', label, minecraft_version, url)
        except Exception as exc:
            errors.append(exc)
            logger.warning('loader_catalogue_failed loader=%s game=%s url=%s',
                           label, minecraft_version, url, exc_info=True)
    if not errors:
        raise ValueError(f"{label} 暂无适用于 Minecraft {minecraft_version} 的版本")
    raise RuntimeError(f"暂时无法获取 {label} 版本列表，请重新加载或在设置中切换下载源。") from errors[-1]


def _sorted_versions(versions):
    def order(version):
        release, *extra = re.split(r'[-+]', version, maxsplit=1)
        suffix = extra[0] if extra else ''
        numbers = tuple(int(part) for part in release.split('.'))
        suffix_order = tuple((1, int(part)) if part.isdigit() else (0, part)
                             for part in re.split(r'(\d+)', suffix))
        return numbers, '-' not in version, suffix_order
    return sorted({version for version in versions if isinstance(version, str)
                   and re.fullmatch(r'\d+(?:\.\d+)*(?:[-+][A-Za-z0-9_.+-]+)?', version)},
                  key=order, reverse=True)


def _meta_versions(records):
    return _sorted_versions(item['loader']['version'] for item in records
                            if isinstance(item, dict) and isinstance(item.get('loader'), dict)
                            and isinstance(item['loader'].get('version'), str))


def _neoforge_versions(records, minecraft_version):
    # NeoForge's version suffix uses .0 for Minecraft releases such as 1.21.
    match = re.fullmatch(r'1\.(\d+)(?:\.(\d+))?', minecraft_version)
    prefix = f'{match[1]}.{match[2] or 0}.' if match else minecraft_version + '.'
    versions = []
    for item in records:
        if isinstance(item, dict):
            if item.get('mcversion') != minecraft_version:
                continue
            item = item.get('version')
        if isinstance(item, str) and item.startswith(prefix):
            versions.append(item)
    return _sorted_versions(versions)


def _forge_versions(records, minecraft_version):
    """Normalize official Maven coordinates and BMCLAPI's per-game build objects."""
    prefix = minecraft_version + "-"
    versions = []
    for record in records:
        if isinstance(record, str):
            if not record.startswith(prefix):
                continue
            version = record[len(prefix):]
        elif isinstance(record, dict):
            if record.get("mcversion") != minecraft_version:
                continue
            version = record.get("version")
            if not isinstance(version, str):
                continue
            branch = record.get("branch")
            if isinstance(branch, str) and branch:
                version += "-" + branch
        else:
            continue
        if version and re.fullmatch(r"[A-Za-z0-9_.+-]+", version):
            versions.append(version)
    # Maven lists are commonly oldest first; do not offer an old build by default.
    def order(version):
        return tuple((1, int(part)) if part.isdigit() else (0, part)
                     for part in re.split(r"(\d+)", version))
    return sorted(set(versions), key=order, reverse=True)


def _installed_forge_version(directory, minecraft_version, loader_version):
    expected = f"{minecraft_version}-forge-{loader_version}"
    versions = Path(directory) / "versions"
    if (versions / expected / f"{expected}.json").is_file():
        return expected
    coordinate = f"net.minecraftforge:forge:{minecraft_version}-{loader_version}"
    if versions.is_dir():
        for folder in sorted(versions.iterdir(), key=lambda item: item.name.casefold()):
            try:
                metadata = json.loads((folder / f"{folder.name}.json").read_text(encoding="utf-8"))
                if any(isinstance(library, dict) and isinstance(library.get("name"), str)
                       and (library["name"] == coordinate or library["name"].startswith(coordinate + ":"))
                       for library in metadata.get("libraries", [])):
                    return folder.name
            except (OSError, ValueError, TypeError, AttributeError):
                continue
    # The worker checks that this metadata really exists before publishing success.
    return expected


def loader_instance_id(loader, minecraft_version, loader_version):
    from core.modpacks import instance_name
    return instance_name(f'{minecraft_version}-{loader}-{loader_version}')


def _flatten_forge_version(directory, installed, minecraft_version, before_versions, identity=None):
    """Publish a loader as one standalone version and discard fresh intermediates."""
    from core.launch_preparation import (exclude_version_jar_from_bootstrap_scan,
                                         resolved_metadata, version_chain)

    root = Path(directory)
    versions = root / 'versions'
    chain = version_chain(root, installed)
    resolved = resolved_metadata(chain)
    core_owner = next((metadata.get('jar') for _, metadata in chain if metadata.get('jar')), chain[-1][0])
    core_jar = versions / core_owner / (core_owner + '.jar')
    if not core_jar.is_file():
        raise FileNotFoundError(str(core_jar))
    resolved.pop('inheritsFrom', None)
    resolved.pop('jar', None)
    identity = identity or installed
    resolved['id'] = identity
    resolved['clientVersion'] = minecraft_version
    exclude_version_jar_from_bootstrap_scan(resolved, identity)
    target = versions / identity
    target.mkdir(parents=True, exist_ok=True)
    if core_jar.resolve() != (target / (identity + '.jar')).resolve():
        shutil.copyfile(core_jar, target / (identity + '.jar'))
    for name, _ in reversed(chain):
        natives = versions / name / 'natives'
        if natives.is_dir() and natives.resolve() != (target / 'natives').resolve():
            shutil.copytree(natives, target / 'natives', dirs_exist_ok=True)
    (target / (identity + '.json')).write_text(
        json.dumps(resolved, ensure_ascii=False, indent=2), encoding='utf-8')

    created = {name for name, _ in chain} - set(before_versions) - {identity}
    referenced = set()
    for metadata_path in versions.glob('*/*.json'):
        if metadata_path.parent.name in created:
            continue
        try:
            metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if isinstance(metadata, dict):
            referenced.update(value for key in ('inheritsFrom', 'jar')
                              if isinstance((value := metadata.get(key)), str))
    for _ in chain:
        for name, metadata in chain:
            if name in referenced:
                referenced.update(value for key in ('inheritsFrom', 'jar')
                                  if isinstance((value := metadata.get(key)), str))
    for name in created - referenced:
        path = versions / name
        if path.parent.resolve() == versions.resolve() and not path.is_symlink():
            shutil.rmtree(path, ignore_errors=True)
    # Case-only loader names share a folder on Windows. Remove the old named
    # profile only when it is a distinct file on this filesystem.
    if installed != identity and (versions / installed).resolve() == target.resolve():
        for suffix in ('.json', '.jar'):
            old, current = target / (installed + suffix), target / (identity + suffix)
            if old.exists() and old.resolve() != current.resolve():
                old.unlink()
    return identity


def available_versions(loader, minecraft_version, source="自动（镜像优先，失败切换官方）"):
    if not minecraft_version:
        raise ValueError("请先选择 Minecraft 版本")
    if loader == "Forge":
        official = "https://maven.minecraftforge.net/net/minecraftforge/forge/maven-metadata.xml"
        mirror = BMCLAPI + "/forge/minecraft/" + minecraft_version
        candidates = []
        for url in _source_urls(source, official, mirror):
            candidates.append((url, _maven_versions if urlsplit(url).path.endswith('.xml') else _json_versions))
        result = _load_records("Forge", candidates,
                               lambda records: _forge_versions(records, minecraft_version), minecraft_version)
    elif loader in ("Fabric", "Quilt"):
        root = "v2" if loader == "Fabric" else "v3"
        official_host = "meta.fabricmc.net" if loader == "Fabric" else "meta.quiltmc.org"
        official = f"https://{official_host}/{root}/versions/loader/{minecraft_version}"
        mirror_name = "fabric-meta" if loader == "Fabric" else "quilt-meta"
        mirror = f"{BMCLAPI}/{mirror_name}/{root}/versions/loader/{minecraft_version}"
        candidates = [(url, _json_versions) for url in _source_urls(source, official, mirror)]
        result = _load_records(loader, candidates, _meta_versions, minecraft_version)
    elif loader == "NeoForge":
        match = re.fullmatch(r"(\d+)\.(\d+)(?:\.(\d+))?", minecraft_version)
        if not (match and ((int(match[1]) == 1 and (int(match[2]), int(match[3] or 0)) >= (20, 2))
                           or int(match[1]) >= 26)):
            raise ValueError("NeoForge 官方安装器从 Minecraft 1.20.2 起提供")
        official = "https://maven.neoforged.net/releases/net/neoforged/neoforge/maven-metadata.xml"
        mirror = BMCLAPI + "/neoforge/list/" + minecraft_version
        candidates = [(url, _maven_versions if urlsplit(url).path.endswith('.xml') else _json_versions)
                      for url in _source_urls(source, official, mirror)]
        result = _load_records("NeoForge", candidates,
                               lambda records: _neoforge_versions(records, minecraft_version), minecraft_version)
    else:
        raise ValueError(f"不支持的加载器：{loader}")
    if not result:
        raise ValueError(f"{loader} 暂无适用于 Minecraft {minecraft_version} 的版本")
    return result


def _maven_mirror_url(url):
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname:
        return None
    if parsed.hostname.endswith((
        "minecraft.net", "minecraftforge.net", "fabricmc.net", "quiltmc.org",
        "neoforged.net",
    )):
        path = parsed.path
        # BMCLAPI exposes Maven coordinates below /maven directly; the
        # NeoForge/Forge publishers include /releases in their public URL.
        if path.startswith('/releases/'):
            path = path[len('/releases'):]
        return _MAVEN_MIRROR + path + (("?" + parsed.query) if parsed.query else "")
    return None


def _download_urls(url, source):
    from core.game_sources import source_urls
    return source_urls(source, url)


class _LoaderSession:
    """Bound third-party loader HTTP calls without changing global requests."""
    def __init__(self, session=None, cancel=None):
        self.session = session or requests
        self.cancel = cancel

    def get(self, url, **kwargs):
        if self.cancel is not None and self.cancel.is_set():
            raise InterruptedError('安装已取消')
        kwargs.setdefault('timeout', (8, 20))
        return self.session.get(url, **kwargs)


def _routed_downloader(download_file, source, cancel=None, file_event=None, retries=2):
    def download(url, path, callback=None, sha1=None, lzma_compressed=False, session=None,
                 minecraft_directory=None, overwrite=False):
        with download_lock(path, cancel):
            return perform(url, path, callback, sha1, lzma_compressed, session, minecraft_directory, overwrite)

    def perform(url, path, callback=None, sha1=None, lzma_compressed=False, session=None,
                minecraft_directory=None, overwrite=False):
        path = os.fspath(path)
        report_file = file_event or (callback or {}).get('fileEvent')
        def emit(state, **values):
            if report_file:
                report_file(dict(key=str(Path(path).resolve()), name=Path(path).name,
                                 path=Path(path).name, state=state, **values))
        if os.path.isfile(path) and not overwrite:
            if sha1 is None or _file_sha1(path) == sha1.lower():
                emit('cached', done=os.path.getsize(path), total=os.path.getsize(path), error='')
                return False
            os.remove(path)
        if report_file and not lzma_compressed:
            root = Path(minecraft_directory).resolve() if minecraft_directory else Path(path).resolve().parent
            downloader = MinecraftDownloader(root, source=source, cancel=cancel,
                status=(callback or {}).get('setStatus'), file_event=report_file, retries=retries)
            downloader.urls = lambda address: _download_urls(address, source)
            target = Path(path).resolve().relative_to(root)
            try:
                downloader.fetch(url, target, sha1)
            finally:
                session = getattr(downloader._sessions, 'session', None)
                if session is not None:
                    session.close()
            return True
        emit('downloading', done=0, total=0)
        errors = []
        for candidate in _download_urls(url, source):
            try:
                result = download_file(candidate, path, callback, sha1, lzma_compressed,
                                       _LoaderSession(session, cancel), minecraft_directory, overwrite)
                if result:
                    emit('verified', done=os.path.getsize(path), total=os.path.getsize(path))
                    return True
                if os.path.isfile(path) and sha1 and _file_sha1(path) == sha1.lower():
                    return False
            except Exception as exc:
                errors.append(f"{candidate}: {exc}")
            if os.path.isfile(path):
                os.remove(path)
        if errors:
            emit('failed', error=errors[-1])
            raise RuntimeError("加载器文件下载失败：" + "；".join(errors))
        return False

    return download


def _file_sha1(path):
    digest = hashlib.sha1()
    with open(path, "rb") as source_file:
        for chunk in iter(lambda: source_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _profile_loader(loader, minecraft_version, loader_version, directory, callback, cancel, source, publish=True):
    """Install Fabric/Quilt from their launcher metadata without a second JVM install."""
    root = Path(directory).resolve()
    api, host, mirror_name = ('v2', 'meta.fabricmc.net', 'fabric-meta') if loader == 'Fabric' else (
        'v3', 'meta.quiltmc.org', 'quilt-meta')
    suffix = f'/{api}/versions/loader/{minecraft_version}/{loader_version}/profile/json'
    metadata = None
    errors = []
    for url in _source_urls(source, 'https://' + host + suffix, BMCLAPI + '/' + mirror_name + suffix):
        try:
            metadata = _response_json(url, loader + ' 安装信息')
            break
        except Exception as exc:
            errors.append(str(exc))
    if not isinstance(metadata, dict):
        raise RuntimeError('无法获取加载器安装信息：' + '；'.join(errors))
    identity = f'{loader.lower()}-loader-{loader_version}-{minecraft_version}'
    if metadata.get('id') != identity or metadata.get('inheritsFrom') != minecraft_version:
        raise ValueError('加载器安装信息与所选版本不一致')
    downloader = MinecraftDownloader(root, source=source, cancel=cancel, status=callback['setStatus'],
                                     file_event=callback.get('fileEvent'),
                                     retries=callback.get('downloadRetries', 2))
    downloader.urls = lambda address: _download_urls(address, source)
    jobs = []
    for index, item in enumerate(metadata.get('libraries', [])):
        if cancel.is_set():
            raise InterruptedError('安装已取消')
        coordinate = item.get('name', '').split(':')
        if len(coordinate) not in (3, 4) or any(not re.fullmatch('[A-Za-z0-9_.+-]+', p) for p in coordinate):
            raise ValueError('加载器依赖坐标无效')
        group, artifact, version = coordinate[:3]
        filename = artifact + '-' + version + ('-' + coordinate[3] if len(coordinate) == 4 else '') + '.jar'
        relative = '/'.join([group.replace('.', '/'), artifact, version, filename])
        artifact_info = item.get('downloads', {}).get('artifact', {})
        url = artifact_info.get('url') or item.get('url', 'https://libraries.minecraft.net/').rstrip('/') + '/' + relative
        digest = artifact_info.get('sha1') or item.get('sha1')
        jobs.append((url, 'libraries/' + relative, digest, artifact_info.get('size', item.get('size'))))
    callback['setMax'](len(jobs))
    downloader.progress = lambda done, total: callback['setProgress'](done)
    downloader._batch(jobs, '正在并行下载 ' + loader + ' 依赖…')
    if not publish:
        return identity, metadata
    return _publish_profile(root, identity, metadata)


def _publish_profile(root, identity, metadata):
    path = root / 'versions' / identity / (identity + '.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.json.part')
    temporary.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf8')
    temporary.replace(path)
    return identity


@contextmanager
def _use_download_source(source, cancel=None, file_event=None, retries=2):
    """Route minecraft-launcher-lib downloads through the source selected in settings."""
    modules = [minecraft_launcher_lib._helper, minecraft_launcher_lib.install,
               minecraft_launcher_lib.forge, minecraft_launcher_lib.fabric,
               minecraft_launcher_lib.quilt]
    with _PATCH_LOCK:
        originals = []
        process_modules = []
        try:
            for module in modules:
                process = getattr(module, 'subprocess', None)
                if process is not None:
                    process_modules.append((module, process))
                    module.subprocess = _QuietSubprocess(process, cancel)
                original = getattr(module, "download_file", None)
                if original:
                    originals.append((module, original))
                    module.download_file = _routed_downloader(original, source, cancel, file_event, retries)
            yield
        finally:
            for module, original in process_modules:
                module.subprocess = original
            for module, original in originals:
                module.download_file = original


def _prefetch_neoforge_libraries(installer, root, callback, cancel, source):
    try:
        with zipfile.ZipFile(installer) as archive:
            profile = json.loads(archive.read('install_profile.json'))
    except (KeyError, OSError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        raise RuntimeError('NeoForge 安装器缺少有效的 install_profile.json') from exc
    libraries = profile.get('libraries') if isinstance(profile, dict) else None
    if not isinstance(libraries, list) or not libraries:
        raise RuntimeError('NeoForge 安装器没有可下载的依赖列表')

    downloader = MinecraftDownloader(root, source=source, cancel=cancel,
                                     status=callback['setStatus'],
                                     file_event=callback.get('fileEvent'),
                                     retries=callback.get('downloadRetries', 2))
    downloader.urls = lambda url: _download_urls(url, source)
    callback['setMax'](len(libraries))
    jobs = []
    for index, library in enumerate(libraries):
        if cancel.is_set():
            raise InterruptedError('安装已取消')
        artifact = (library.get('downloads') or {}).get('artifact') if isinstance(library, dict) else None
        library_name = library.get('name', 'unknown') if isinstance(library, dict) else 'unknown'
        if not isinstance(artifact, dict):
            raise RuntimeError('NeoForge 依赖缺少 artifact 信息：' + str(library_name))
        url = artifact.get('url', '')
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or parsed.hostname not in ('maven.neoforged.net', 'libraries.minecraft.net'):
            raise RuntimeError('NeoForge 依赖地址不受支持：' + str(url))
        digest = artifact.get('sha1', '')
        size = artifact.get('size')
        artifact_path = artifact.get('path', '')
        if not isinstance(artifact_path, str):
            raise RuntimeError('NeoForge 依赖路径无效：' + str(library_name))
        relative = PurePosixPath(artifact_path)
        if (not re.fullmatch(r'[0-9a-fA-F]{40}', digest) or not isinstance(size, int) or size < 0
                or not relative.parts or relative.is_absolute() or '..' in relative.parts):
            raise RuntimeError('NeoForge 依赖缺少有效路径、SHA-1 或文件大小：' + str(library_name))
        target = 'libraries/' + relative.as_posix()
        downloader.inside(target)
        jobs.append((url, target, digest, size))
    downloader.progress = lambda done, total: callback['setProgress'](done)
    downloader._batch(jobs, '正在并行下载 NeoForge 依赖…')


def _neo_forge(version, directory, java, callback, cancel, source):
    root = Path(directory).resolve()
    official = f"https://maven.neoforged.net/releases/net/neoforged/neoforge/{version}/neoforge-{version}-installer.jar"
    root.mkdir(parents=True, exist_ok=True)
    from utils.storage_paths import temporary_directory
    with tempfile.TemporaryDirectory(prefix="neoforge-", dir=temporary_directory()) as folder:
        downloader = MinecraftDownloader(root, source=source, cancel=cancel,
            status=callback['setStatus'], file_event=callback.get('fileEvent'),
            retries=callback.get('downloadRetries', 6))
        def progress(current, total):
            callback['setMax'](total)
            callback['setProgress'](current)
        callback['setStatus']('正在下载 NeoForge 安装器…')
        installer = downloader.fetch(official,
            f'.buggcraft-downloads/neoforge-{version}-installer.jar', file_progress=progress)
        if cancel.is_set():
            raise InterruptedError("安装已取消")
        # The third-party installer uses hard-coded Maven URLs and ignores
        # the launcher's selected source. Populate its verified library cache
        # through the normal source router before invoking it.
        _prefetch_neoforge_libraries(installer, root, callback, cancel, source)
        # The official client installer requires a vanilla launcher profile
        # even for a fresh third-party launcher root. Seed only an absent
        # profile; existing vanilla/Microsoft Store profiles belong to users.
        profiles = root / 'launcher_profiles.json'
        if not profiles.exists() and not (root / 'launcher_profiles_microsoft_store.json').exists():
            with profiles.open('x', encoding='utf-8') as profile_file:
                json.dump({'profiles': {}, 'settings': {}}, profile_file)
        # Forge's client installer accepts the target directory as the
        # argument of --installClient. --installDir is a server/legacy flag
        # and makes current NeoForge installers fail before doing any work.
        command = [java, "-jar", str(installer), "--installClient", str(root)]
        callback["setStatus"]("正在运行 NeoForge 安装器…")
        process = subprocess.Popen(command, cwd=str(root), stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        try:
            while True:
                if cancel.is_set():
                    raise InterruptedError("安装已取消")
                try:
                    output, _ = process.communicate(timeout=0.2)
                    break
                except subprocess.TimeoutExpired:
                    continue
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            if process.stdout:
                process.stdout.close()
        from utils.storage_paths import game_cache
        installer_log = game_cache(root) / ('neoforge-' + version + '-installer.log')
        installer_log.parent.mkdir(parents=True, exist_ok=True)
        installer_log.write_text(output, encoding='utf-8')
        callback["setStatus"]('NeoForge 安装器日志：' + str(installer_log))
        for line in output.splitlines()[-30:]:
            callback["setStatus"](line[:500])
        if process.returncode:
            raise RuntimeError(f"NeoForge 安装器退出码 {process.returncode}: {output[-1500:]}")
    installed_id = f"neoforge-{version}"
    metadata = root / "versions" / installed_id / f"{installed_id}.json"
    if not metadata.is_file():
        candidates = list((root / "versions").glob(f"*{version}*/*.json"))
        if not candidates:
            raise RuntimeError("安装器已退出，但没有生成可启动的 NeoForge 版本")
        metadata = candidates[0]
        installed_id = metadata.stem
    return installed_id


def install_loader(loader, minecraft_version, loader_version, directory, java, callback, cancel,
                   source="自动（官方优先，失败切换镜像）", *, target_identity=None, before_versions=None):
    # Installers also write shared profiles and extract native files, outside
    # fetch(). Serialize this mutation phase per game root; resource downloads
    # and modpack file batches remain parallel.
    with use_download_budget():
        with download_lock(Path(directory) / '.buggcraft-loader-install', cancel):
            return _install_loader(loader, minecraft_version, loader_version, directory, java, callback, cancel,
                                   source, target_identity=target_identity, before_versions=before_versions)


def _install_loader(loader, minecraft_version, loader_version, directory, java, callback, cancel, source,
                    *, target_identity=None, before_versions=None):
    identity = target_identity or loader_instance_id(loader, minecraft_version, loader_version)
    from core.modpacks import instance_name
    instance_name(identity)
    versions = Path(directory) / 'versions'
    snapshot = {folder.name for folder in versions.iterdir() if folder.is_dir()} if versions.is_dir() else set()
    before = set(snapshot if before_versions is None else before_versions)
    from utils.storage_paths import game_cache
    cache = game_cache(directory)
    cache.mkdir(parents=True, exist_ok=True)
    receipt = cache / ('loader-intermediates-' + hashlib.sha256(identity.encode()).hexdigest() + '.json')
    from core.modpacks import ModpackImporter
    stamp = ModpackImporter._intermediate_stamp
    try:
        previous = json.loads(receipt.read_text(encoding='utf-8'))
        for name, value in previous.items():
            if (isinstance(name, str) and name in before and value is not None
                    and stamp(versions / name) == value):
                before.discard(name)
    except (OSError, ValueError, AttributeError):
        pass
    completed = False
    try:
        result = _run_loader_install(loader, minecraft_version, loader_version, directory, java, callback,
                                    cancel, source, identity, before)
        completed = True
        return result
    finally:
        # Remember only untouched intermediates owned by this attempt. A retry
        # may remove these; preexisting instances and edited folders stay intact.
        created = {folder.name: stamp(folder) for folder in versions.iterdir()
                   if folder.is_dir() and folder.name not in before} if versions.is_dir() else {}
        if created and not completed:
            receipt.write_text(json.dumps(created), encoding='utf-8')
        else:
            receipt.unlink(missing_ok=True)


def _run_loader_install(loader, minecraft_version, loader_version, directory, java, callback, cancel,
                        source, identity, before_versions, *, _workspace=False):
    if loader in ('Forge', 'NeoForge', 'Fabric', 'Quilt') and not _workspace:
        return _install_native_loader_isolated(loader, minecraft_version, loader_version, directory,
            java, callback, cancel, source, identity)
    target_identity = identity
    def report(name):
        def checked(value):
            if cancel.is_set():
                raise InterruptedError("安装已取消")
            callback[name](value)
        return checked

    monitored = {"setStatus": report("setStatus"), "setProgress": report("setProgress"),
                 "setMax": report("setMax")}
    if callback.get('fileEvent'):
        monitored['fileEvent'] = callback['fileEvent']
    monitored['downloadRetries'] = callback.get('downloadRetries', 6)
    downloader = MinecraftDownloader(
        directory, source=source, cancel=cancel,
        status=monitored["setStatus"],
        file_event=monitored.get('fileEvent'),
        retries=monitored['downloadRetries'],
        progress=lambda current, maximum: (monitored["setMax"](maximum),
                                            monitored["setProgress"](current)),
    )
    def ensure_vanilla():
        if not verified_installation(directory, minecraft_version):
            downloader.install(minecraft_version)
        elif cancel.is_set():
            raise InterruptedError("安装已取消")

    if loader in ('Fabric', 'Quilt'):
        # Metadata and Maven artifacts need only the selected version. Fetch
        # them while the vanilla client, libraries and assets are downloading,
        # but publish the loader profile only after both sides succeed.
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix='loader-prefetch') as pool:
            future = pool.submit(copy_context().run, _profile_loader, loader, minecraft_version,
                                 loader_version, directory, monitored, cancel, source, False)
            errors = []

            def stop_on_failure(completed):
                try:
                    completed.result()
                except BaseException as exc:
                    errors.append(exc)
                    cancel.set()

            future.add_done_callback(stop_on_failure)
            try:
                ensure_vanilla()
                if cancel.is_set():
                    raise InterruptedError("安装已取消")
                _upstream_identity, metadata = future.result()
            except BaseException:
                cancel.set()
                if errors:
                    raise errors[0]
                raise
        metadata = dict(metadata, id=target_identity)
        installed = _publish_profile(Path(directory).resolve(), target_identity, metadata)
        return _flatten_forge_version(directory, installed, minecraft_version, before_versions)
    ensure_vanilla()
    if cancel.is_set():
        raise InterruptedError("安装已取消")
    if loader in ('Forge', 'NeoForge'):
        from core.java_runtime import prepare_installer_java
        java = prepare_installer_java(loader, directory, minecraft_version, java, monitored, cancel)
    if loader == "NeoForge":
        installed = _neo_forge(loader_version, directory, java, callback, cancel, source)
        return _flatten_forge_version(directory, installed, minecraft_version, before_versions, identity)
    with _use_download_source(source, cancel, callback.get('fileEvent'),
                              callback.get('downloadRetries', 6)):
        if loader == "Forge":
            forge_version = f"{minecraft_version}-{loader_version}"
            callback["setStatus"](f"安装 Forge {forge_version}")
            minecraft_launcher_lib.forge.install_forge_version(forge_version, directory,
                                                                callback=monitored, java=java)
            installed = _installed_forge_version(directory, minecraft_version, loader_version)
            return _flatten_forge_version(directory, installed, minecraft_version, before_versions, identity)
    raise ValueError(f"不支持的加载器：{loader}")


def _link_install_cache(source, destination, cancel, *, replace=False):
    """Reuse immutable cached files without giving installers a user's versions."""
    source, destination = filesystem_path(source), filesystem_path(destination)
    if not source.is_dir():
        return
    for path in source.rglob('*'):
        if cancel.is_set():
            raise InterruptedError('安装已取消')
        if not path.is_file() or path.is_symlink() or '.buggcraft-part' in path.name:
            continue
        target = destination / path.relative_to(source)
        if target.exists():
            if not replace or os.path.samefile(path, target) or _file_sha1(path) == _file_sha1(target):
                continue
            # A repaired file in the workspace must replace the broken shared
            # cache too; publish atomically without truncating another reader.
            with download_lock(target, cancel):
                temporary = target.with_name(target.name + '.buggcraft-cache-part')
                temporary.unlink(missing_ok=True)
                try:
                    try:
                        os.link(path, temporary)
                    except OSError:
                        shutil.copy2(path, temporary)
                    os.replace(temporary, target)
                finally:
                    temporary.unlink(missing_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(path, target)
        except FileExistsError:
            pass
        except OSError:
            if not target.exists():
                shutil.copy2(path, target)


def _install_native_loader_isolated(loader, minecraft_version, loader_version, directory, java,
                                    callback, cancel, source, identity):
    root = Path(directory)
    from utils.storage_paths import game_cache
    work = game_cache(root) / ('loader-' + hashlib.sha256(identity.encode()).hexdigest()[:16])
    work.mkdir(parents=True, exist_ok=True)
    for name in ('libraries', 'assets'):
        _link_install_cache(root / name, work / name, cancel)
    base = root / 'versions' / minecraft_version
    if verified_installation(root, minecraft_version):
        staged_base = work / 'versions' / minecraft_version
        staged_base.mkdir(parents=True, exist_ok=True)
        # Profiles are writable installer inputs. Copy them, and never traverse
        # the user's mods/saves/config or let a hard link mutate their profile.
        for filename in (minecraft_version + '.json', minecraft_version + '.jar', '.buggcraft-complete.json'):
            source_file = base / filename
            if source_file.is_file():
                destination = staged_base / filename
                destination.unlink(missing_ok=True)
                shutil.copy2(source_file, destination)
        if (base / 'natives').is_dir():
            shutil.copytree(base / 'natives', staged_base / 'natives', dirs_exist_ok=True)
    completed = False
    try:
        installed = _run_loader_install(loader, minecraft_version, loader_version, str(work), java,
            callback, cancel, source, identity, set(), _workspace=True)
        target = root / 'versions' / identity
        if target.exists():
            raise FileExistsError('实例名称已被占用，请选择新名称：' + identity)
        target.parent.mkdir(parents=True, exist_ok=True)
        from utils.storage_paths import publish_directory
        publish_directory(work / 'versions' / installed, target)
        completed = True
        return identity
    finally:
        # A cancelled installation still contributes its completed cache files.
        # The private versions remain available to its next retry.
        cache_cancel = threading.Event()
        for name in ('libraries', 'assets'):
            _link_install_cache(work / name, root / name, cache_cancel, replace=True)
        if completed:
            shutil.rmtree(work, ignore_errors=True)
