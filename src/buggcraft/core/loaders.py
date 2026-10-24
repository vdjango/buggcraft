"""Version discovery and installation for supported Java Edition loaders."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import logging
import json
import os
import re
import subprocess
import tempfile
import threading
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlsplit

import minecraft_launcher_lib
import requests

from core.downloads import MinecraftDownloader
from utils.download_locks import download_lock
from utils.http_identity import USER_AGENT


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
    return "auto"


def _source_urls(source, official, mirror):
    mode = _source_mode(source)
    if mode == "official" or not mirror:
        return [official]
    if mode == "mirror":
        return [mirror]
    return [official, mirror]


def _response(url):
    response = requests.get(url, timeout=(8, 20), headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    return response


def _json_versions(url):
    value = _response(url).json()
    if not isinstance(value, list):
        raise ValueError("加载器版本服务返回了无效数据")
    return value


def _maven_versions(url):
    root = ET.fromstring(_response(url).content)
    return [node.text for node in root.findall("./versioning/versions/version") if node.text]


def _load_records(label, candidates):
    errors = []
    for url, load in candidates:
        try:
            return load(url)
        except Exception as exc:
            errors.append(f"{url}: {exc}")
    raise RuntimeError(f"无法获取 {label} 版本列表：{'；'.join(errors)}")


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


def available_versions(loader, minecraft_version, source="自动（官方优先，失败切换镜像）"):
    if not minecraft_version:
        raise ValueError("请先选择 Minecraft 版本")
    if loader == "Forge":
        official = "https://maven.minecraftforge.net/net/minecraftforge/forge/maven-metadata.xml"
        mirror = BMCLAPI + "/forge/minecraft/" + minecraft_version
        candidates = []
        for url in _source_urls(source, official, mirror):
            candidates.append((url, _maven_versions if url == official else _json_versions))
        records = _load_records("Forge", candidates)
        result = _forge_versions(records, minecraft_version)
    elif loader in ("Fabric", "Quilt"):
        root = "v2" if loader == "Fabric" else "v3"
        official_host = "meta.fabricmc.net" if loader == "Fabric" else "meta.quiltmc.org"
        official = f"https://{official_host}/{root}/versions/loader/{minecraft_version}"
        mirror_name = "fabric-meta" if loader == "Fabric" else "quilt-meta"
        mirror = f"{BMCLAPI}/{mirror_name}/{root}/versions/loader/{minecraft_version}"
        candidates = [(url, _json_versions) for url in _source_urls(source, official, mirror)]
        records = _load_records(loader, candidates)
        result = [str(item["loader"]["version"]) for item in records
                  if isinstance(item, dict) and item.get("loader", {}).get("version")]
    elif loader == "NeoForge":
        match = re.fullmatch(r"1\.(\d+)\.(\d+)", minecraft_version)
        if not match or tuple(map(int, match.groups())) < (20, 2):
            raise ValueError("NeoForge 官方安装器从 Minecraft 1.20.2 起提供")
        prefix = f"{match.group(1)}.{match.group(2)}."
        official = "https://maven.neoforged.net/releases/net/neoforged/neoforge/maven-metadata.xml"
        mirror = _MAVEN_MIRROR + "/net/neoforged/neoforge/maven-metadata.xml"
        candidates = [(url, _maven_versions) for url in _source_urls(source, official, mirror)]
        result = [version for version in _load_records("NeoForge", candidates)
                  if version.startswith(prefix)]
        result.reverse()
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
        return _MAVEN_MIRROR + parsed.path + (("?" + parsed.query) if parsed.query else "")
    return None


def _download_urls(url, source):
    parsed = urlsplit(url)
    replacements = {
        "launchermeta.mojang.com": "",
        "piston-meta.mojang.com": "",
        "launcher.mojang.com": "",
        "piston-data.mojang.com": "",
        "resources.download.minecraft.net": "/assets",
        "libraries.minecraft.net": "/maven",
    }
    mirror = _maven_mirror_url(url)
    if not mirror and parsed.hostname in replacements:
        mirror = BMCLAPI + replacements[parsed.hostname] + parsed.path
        if parsed.query:
            mirror += "?" + parsed.query
    if _source_mode(source) == "official" or not mirror:
        return [url]
    if _source_mode(source) == "mirror":
        return [mirror]
    return [url, mirror]


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


def _routed_downloader(download_file, source, cancel=None):
    def download(url, path, callback=None, sha1=None, lzma_compressed=False, session=None,
                 minecraft_directory=None, overwrite=False):
        with download_lock(path, cancel):
            return perform(url, path, callback, sha1, lzma_compressed, session, minecraft_directory, overwrite)

    def perform(url, path, callback=None, sha1=None, lzma_compressed=False, session=None,
                minecraft_directory=None, overwrite=False):
        path = os.fspath(path)
        if os.path.isfile(path) and not overwrite:
            if sha1 is None or _file_sha1(path) == sha1.lower():
                return False
            os.remove(path)
        errors = []
        for candidate in _download_urls(url, source):
            try:
                result = download_file(candidate, path, callback, sha1, lzma_compressed,
                                       _LoaderSession(session, cancel), minecraft_directory, overwrite)
                if result:
                    return True
                if os.path.isfile(path) and sha1 and _file_sha1(path) == sha1.lower():
                    return False
            except Exception as exc:
                errors.append(f"{candidate}: {exc}")
            if os.path.isfile(path):
                os.remove(path)
        if errors:
            raise RuntimeError("加载器文件下载失败：" + "；".join(errors))
        return False

    return download


def _file_sha1(path):
    digest = hashlib.sha1()
    with open(path, "rb") as source_file:
        for chunk in iter(lambda: source_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _profile_loader(loader, minecraft_version, loader_version, directory, callback, cancel, source):
    """Install Fabric/Quilt from their launcher metadata without a second JVM install."""
    root = Path(directory).resolve()
    api, host, mirror_name = ('v2', 'meta.fabricmc.net', 'fabric-meta') if loader == 'Fabric' else (
        'v3', 'meta.quiltmc.org', 'quilt-meta')
    suffix = f'/{api}/versions/loader/{minecraft_version}/{loader_version}/profile/json'
    metadata = None
    errors = []
    for url in _source_urls(source, 'https://' + host + suffix, BMCLAPI + '/' + mirror_name + suffix):
        try:
            metadata = _response(url).json()
            break
        except Exception as exc:
            errors.append(str(exc))
    if not isinstance(metadata, dict):
        raise RuntimeError('无法获取加载器安装信息：' + '；'.join(errors))
    identity = f'{loader.lower()}-loader-{loader_version}-{minecraft_version}'
    if metadata.get('id') != identity or metadata.get('inheritsFrom') != minecraft_version:
        raise ValueError('加载器安装信息与所选版本不一致')
    downloader = MinecraftDownloader(root, source=source, cancel=cancel, status=callback['setStatus'])
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
        # Route loader Maven hosts through the chosen source, as for Forge.
        candidates = _download_urls(url, source)
        last_error = None
        for candidate in candidates:
            try:
                callback['setStatus']('安装 ' + loader + ' 依赖：' + filename)
                downloader.fetch(candidate, 'libraries/' + relative, digest,
                                 artifact_info.get('size', item.get('size')))
                last_error = None
                break
            except Exception as exc:
                last_error = exc
        if last_error:
            raise last_error
        callback['setMax'](len(metadata['libraries']))
        callback['setProgress'](index + 1)
    path = root / 'versions' / identity / (identity + '.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.json.part')
    temporary.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf8')
    temporary.replace(path)
    return identity


@contextmanager
def _use_download_source(source, cancel=None):
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
                    module.download_file = _routed_downloader(original, source, cancel)
            yield
        finally:
            for module, original in process_modules:
                module.subprocess = original
            for module, original in originals:
                module.download_file = original


def _neo_forge(version, directory, java, callback, cancel, source):
    root = Path(directory).resolve()
    official = f"https://maven.neoforged.net/releases/net/neoforged/neoforge/{version}/neoforge-{version}-installer.jar"
    mirror = f"{_MAVEN_MIRROR}/net/neoforged/neoforge/{version}/neoforge-{version}-installer.jar"
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="buggcraft-neoforge-") as folder:
        installer = Path(folder) / "neoforge-installer.jar"
        errors = []
        for installer_url in _source_urls(source, official, mirror):
            callback["setStatus"]("正在下载 NeoForge 安装器…")
            try:
                response = requests.get(installer_url, stream=True, timeout=(8, 30),
                                        headers={"User-Agent": USER_AGENT})
                response.raise_for_status()
                total = int(response.headers.get("Content-Length", "0") or 0)
                callback["setMax"](total)
                current = 0
                with response, installer.open("wb") as output:
                    for block in response.iter_content(128 * 1024):
                        if cancel.is_set():
                            raise InterruptedError("安装已取消")
                        if block:
                            output.write(block)
                            current += len(block)
                            callback["setProgress"](current)
                break
            except InterruptedError:
                raise
            except Exception as exc:
                installer.unlink(missing_ok=True)
                errors.append(f"{installer_url}: {exc}")
        else:
            raise RuntimeError("NeoForge 安装器下载失败：" + "；".join(errors))
        if cancel.is_set():
            raise InterruptedError("安装已取消")
        command = [java, "-jar", str(installer), "--installClient", "--installDir", str(root)]
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
                   source="自动（官方优先，失败切换镜像）"):
    # Installers also write shared profiles and extract native files, outside
    # fetch(). Serialize this mutation phase per game root; resource downloads
    # and modpack file batches remain parallel.
    with download_lock(Path(directory) / '.buggcraft-loader-install', cancel):
        return _install_loader(loader, minecraft_version, loader_version, directory, java, callback, cancel, source)


def _install_loader(loader, minecraft_version, loader_version, directory, java, callback, cancel, source):
    def report(name):
        def checked(value):
            if cancel.is_set():
                raise InterruptedError("安装已取消")
            callback[name](value)
        return checked

    monitored = {"setStatus": report("setStatus"), "setProgress": report("setProgress"),
                 "setMax": report("setMax")}
    downloader = MinecraftDownloader(
        directory, source=source, cancel=cancel,
        status=monitored["setStatus"],
        progress=lambda current, maximum: (monitored["setMax"](maximum),
                                            monitored["setProgress"](current)),
    )
    downloader.install(minecraft_version)
    if cancel.is_set():
        raise InterruptedError("安装已取消")
    if loader in ('Fabric', 'Quilt'):
        return _profile_loader(loader, minecraft_version, loader_version, directory, monitored, cancel, source)
    if loader == "NeoForge":
        return _neo_forge(loader_version, directory, java, callback, cancel, source)
    with _use_download_source(source, cancel):
        if loader == "Forge":
            forge_version = f"{minecraft_version}-{loader_version}"
            callback["setStatus"](f"安装 Forge {forge_version}")
            minecraft_launcher_lib.forge.install_forge_version(forge_version, directory,
                                                                callback=monitored, java=java)
            return _installed_forge_version(directory, minecraft_version, loader_version)
    raise ValueError(f"不支持的加载器：{loader}")
