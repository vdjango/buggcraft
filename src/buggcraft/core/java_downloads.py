"""Portable Java catalogues and verified, private runtime installations."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
import hashlib
import json
import logging
import os
from pathlib import Path
import platform
import re
import tarfile
import tempfile
import threading
from urllib.parse import quote, urlsplit
import zipfile

import requests

from config.javafinder import JavaPathFinder
from utils.archives import extract_zip
from utils.download_locks import download_lock
from utils.http_identity import USER_AGENT

logger = logging.getLogger(__name__)
SOURCES = ('自动（国内优先）', '清华镜像', 'Adoptium 官方', 'Azul 官方')
MAJORS = (8, 11, 16, 17, 21, 25)
TUNA = 'https://mirrors.tuna.tsinghua.edu.cn/Adoptium'
_HEADERS = {'User-Agent': USER_AGENT}
_MAX_ARCHIVE = 512 * 1024 ** 2


def java_platform():
    system = {'Windows': 'windows', 'Darwin': 'mac', 'Linux': 'linux'}.get(platform.system())
    machine = platform.machine().lower()
    architecture = {'amd64': 'x64', 'x86_64': 'x64', 'arm64': 'aarch64',
                    'aarch64': 'aarch64', 'x86': 'x86', 'i386': 'x86', 'i686': 'x86'}.get(machine)
    if not system or not architecture:
        raise ValueError('此系统或处理器架构暂不支持自动下载 Java，请手动添加。')
    return system, architecture


def _json(url, **kwargs):
    with requests.get(url, headers=_HEADERS, timeout=(8, 20), **kwargs) as response:
        response.raise_for_status()
        return response.json()


@dataclass(frozen=True)
class JavaPackage:
    vendor: str
    major: int
    version: str
    system: str
    architecture: str
    kind: str
    name: str
    checksum: str
    size: int
    urls: tuple

    def record(self):
        return dict(asdict(self), id=self.checksum, title=f'{self.vendor} Java {self.version}',
                    description=f'{self.kind.upper()} · {self.system} / {self.architecture}',
                    sizeText=f'{self.size / 1024 ** 2:.1f} MiB' if self.size else '大小以下载为准')


def _package(vendor, major, version, system, architecture, kind, name, checksum, size, urls):
    if (not re.fullmatch(r'[A-Za-z0-9_.+-]+', name) or not name.endswith(('.zip', '.tar.gz'))
            or not re.fullmatch(r'[0-9a-fA-F]{64}', checksum or '')
            or type(size) is not int or not 0 <= size <= _MAX_ARCHIVE
            or any(urlsplit(url).scheme != 'https' or urlsplit(url).username for url in urls)):
        raise ValueError('Java 服务返回了无效的压缩包或校验信息')
    return JavaPackage(vendor, major, str(version), system, architecture, kind, name,
                       checksum.lower(), size, tuple(urls))


def _temurin(major, system, architecture, kind, source):
    rows = _json(f'https://api.adoptium.net/v3/assets/latest/{major}/hotspot',
                 params=dict(architecture=architecture, image_type=kind, os=system, vendor='eclipse'))
    packages = []
    for row in rows:
        binary = row.get('binary', {})
        if (binary.get('architecture'), binary.get('os'), binary.get('image_type')) != (architecture, system, kind):
            continue
        package, version = binary.get('package', {}), row.get('version', {})
        if version.get('major') != major or row.get('release_type', 'ga') != 'ga':
            continue
        official, name = package.get('link', ''), package.get('name', '')
        if urlsplit(official).hostname != 'github.com':
            continue
        mirror = f'{TUNA}/{major}/{kind}/{architecture}/{system}/{quote(name)}'
        urls = [official] if source == 'Adoptium 官方' else [mirror]
        if source == SOURCES[0]:
            urls.append(official)
        packages.append(_package('Eclipse Temurin', major, version.get('semver', major), system,
            architecture, kind, name, package.get('checksum'), package.get('size', 0), urls))
    return packages


def _azul(major, system, architecture, kind):
    arch = 'arm' if architecture == 'aarch64' else 'x86'
    bits = 32 if architecture == 'x86' else 64
    rows = _json('https://api.azul.com/metadata/v1/zulu/packages/', params=dict(
        java_version=major, os={'mac': 'macos'}.get(system, system), arch=arch, hw_bitness=bits,
        archive_type='zip' if system == 'windows' else 'tar.gz', java_package_type=kind,
        javafx_bundled='false', latest='true', release_status='ga', availability_types='CA'))
    # Azul can return multiple PSU/CPU updates; offer the newest stable release.
    rows = sorted(rows, key=lambda row: row.get('java_version', []), reverse=True)
    for row in rows:
        identity = row.get('package_uuid', '')
        if not re.fullmatch(r'[0-9a-f-]{36}', identity):
            continue
        data = _json('https://api.azul.com/metadata/v1/zulu/packages/' + identity)
        if (data.get('java_version', [0])[0] != major or data.get('release_status') != 'ga'
                or data.get('java_package_type') != kind or data.get('arch') != arch
                or data.get('hw_bitness') != bits or data.get('os') != {'mac': 'macos'}.get(system, system)):
            continue
        url = data.get('download_url', '')
        if urlsplit(url).hostname != 'cdn.azul.com':
            continue
        return [_package('Azul Zulu', major, '.'.join(map(str, data['java_version'])), system,
            architecture, kind, data.get('name', ''), data.get('sha256_hash'), 0, [url])]
    return []


def catalogue(major, source=SOURCES[0], kind='jre'):
    if type(major) is not int or not 8 <= major <= 99 or kind not in ('jre', 'jdk') or source not in SOURCES:
        raise ValueError('Java 下载条件无效')
    system, architecture = java_platform()
    providers = [lambda: _temurin(major, system, architecture, kind, source)]
    if source == 'Azul 官方':
        providers = [lambda: _azul(major, system, architecture, kind)]
    elif source == SOURCES[0]:
        providers.append(lambda: _azul(major, system, architecture, kind))
    packages, errors = [], []
    with ThreadPoolExecutor(max_workers=2) as pool:
        for future in [pool.submit(provider) for provider in providers]:
            try:
                packages.extend(future.result())
            except Exception as exc:
                logger.warning('Java catalogue provider unavailable: %s', exc)
                errors.append(str(exc))
    if not packages and kind == 'jre':
        return catalogue(major, source, 'jdk')
    if not packages:
        raise RuntimeError('未找到此平台的 Java 压缩包。请更换来源或重试。' + ('\n' + '\n'.join(errors) if errors else ''))
    return packages


def _cancelled(cancel):
    if cancel is not None and cancel.is_set():
        raise InterruptedError('Java 安装已取消')


def _probe(directory, expected):
    executable = 'java.exe' if os.name == 'nt' else 'java'
    for path in Path(directory).rglob(executable):
        if path.parent.name != 'bin' or not path.is_file():
            continue
        raw, parsed = JavaPathFinder()._get_java_version(str(path))
        actual = (parsed[1] if parsed[0] == 1 else parsed[0]) if parsed else 0
        if actual == expected:
            return str(path), raw, list(parsed)
    raise ValueError(f'下载的运行环境未通过 Java {expected} 启动校验')


def install(package, root, cancel=None, report=None):
    """Publish atomically after SHA-256, archive and executable validation."""
    report = report or (lambda text, done, total: None)
    cancel = cancel or threading.Event()
    system, architecture = java_platform()
    if (package.system, package.architecture) != (system, architecture):
        raise ValueError('Java 压缩包与当前系统架构不匹配')
    root = Path(root).resolve()
    destination = root / package.checksum
    root.mkdir(parents=True, exist_ok=True)
    with download_lock(destination, cancel):
        _cancelled(cancel)
        if destination.is_dir():
            return _probe(destination, package.major)
        with tempfile.TemporaryDirectory(prefix='.install-', dir=root) as temporary:
            workspace = Path(temporary)
            archive = workspace / package.name
            errors = []
            for url in package.urls:
                _cancelled(cancel)
                report('正在下载 ' + package.name + ' · ' + str(urlsplit(url).hostname), 0, package.size)
                try:
                    digest, done = hashlib.sha256(), 0
                    with requests.get(url, headers=_HEADERS, stream=True, timeout=(8, 30)) as response:
                        response.raise_for_status()
                        total = package.size or int(response.headers.get('Content-Length', 0))
                        if total > _MAX_ARCHIVE:
                            raise ValueError('Java 压缩包超过下载大小限制')
                        with archive.open('wb') as target:
                            for block in response.iter_content(256 * 1024):
                                _cancelled(cancel)
                                done += len(block)
                                if done > _MAX_ARCHIVE:
                                    raise ValueError('Java 压缩包超过下载大小限制')
                                target.write(block)
                                digest.update(block)
                                report('正在下载 ' + package.name, done, total)
                    if digest.hexdigest() != package.checksum or package.size and done != package.size:
                        raise ValueError('Java 压缩包校验失败，请更换来源后重试')
                    break
                except InterruptedError:
                    raise
                except Exception as exc:
                    errors.append(str(exc))
                    logger.warning('Java download failed: %s: %s', url, exc)
            else:
                raise RuntimeError('Java 下载失败：' + '；'.join(errors))
            _cancelled(cancel)
            report('校验通过，正在解压并验证 Java…', 0, 0)
            extracted = workspace / 'runtime'
            extracted.mkdir()
            if archive.name.endswith('.zip'):
                with zipfile.ZipFile(archive) as value:
                    extract_zip(value, extracted)
            else:
                with tarfile.open(archive, 'r:gz') as value:
                    members = value.getmembers()
                    if len(members) > 50000 or sum(item.size for item in members) > 2 * 1024 ** 3:
                        raise ValueError('Java 压缩包超过解压限制')
                    value.extractall(extracted, filter='data')
            result = _probe(extracted, package.major)
            _cancelled(cancel)
            relative = Path(result[0]).relative_to(extracted)
            (extracted / 'buggcraft-runtime.json').write_text(json.dumps(dict(
                vendor=package.vendor, major=package.major, version=package.version,
                checksum=package.checksum, executable=str(relative)), ensure_ascii=False), encoding='utf-8')
            # On Windows an exiting JVM or antivirus can briefly retain a file
            # handle. Keep the verified runtime private until it can be moved.
            for attempt in range(31):
                _cancelled(cancel)
                try:
                    extracted.rename(destination)
                    break
                except PermissionError:
                    if os.name != 'nt' or attempt == 30:
                        raise
                    if attempt == 0:
                        report('正在完成 Java 安装…', 0, 0)
                    cancel.wait(min(0.5, 0.05 * 2 ** min(attempt, 4)))
            report(f'Java {package.version} 已安装并验证', 1, 1)
            return str(destination / relative), result[1], result[2]


def register(settings, entry):
    path, raw, parsed = entry
    entries = settings.get_setting('java.installations', []) or []
    entries = [item for item in entries if isinstance(item, (list, tuple)) and item
               and isinstance(item[0], str) and os.path.normcase(item[0]) != os.path.normcase(path)]
    settings.set_setting('java.installations', entries + [[path, raw, parsed]])
    # The automatic choice needs a real fallback path once the first runtime
    # has been downloaded. Keep explicit per-game Java selections untouched.
    selected = settings.get_version_setting('java.path')
    name = str(settings.get_version_setting('java.name') or '')
    if not selected and name.startswith('使用推荐的 Java 版本'):
        settings.set_version_setting('java.path', path)
    settings.save_settings()


def install_available(packages, root, cancel=None, report=None):
    errors = []
    for package in packages:
        _cancelled(cancel)
        try:
            return package, install(package, root, cancel, report)
        except InterruptedError:
            raise
        except Exception as exc:
            errors.append(f'{package.vendor}: {exc}')
            if report:
                report(f'{package.vendor} 暂不可用，正在尝试备用来源…', 0, 0)
    raise RuntimeError('可用 Java 来源均安装失败：' + '；'.join(errors))
