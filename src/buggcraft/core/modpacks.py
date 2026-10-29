"""Validated CurseForge/Modrinth inspection and transactional instance import."""
from __future__ import annotations

from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextvars import copy_context
import hashlib
import json
import logging
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import threading
import time
import zipfile
from urllib.parse import urlsplit

from core.downloads import DownloadCancelled, MinecraftDownloader, use_download_budget
from core.loaders import install_loader
from core.loader_rules import validate_loaders
from core.curseforge import CurseForgeAPI, download_url, fallback_url
from utils.path_helper import filesystem_path as disk_path

MAX_EXPANDED = 8 * 1024 ** 3
MAX_ENTRIES = 50000


def safe_path(value):
    """Reject ambiguous paths on both Windows and Unix before touching disk."""
    if not isinstance(value, str) or not value or '\\' in value:
        raise ValueError('整合包路径无效')
    path = PurePosixPath(value)
    parts = value.rstrip('/').split('/')
    if path.is_absolute() or any(part in ('', '.', '..') or
            re.search(r'[<>:"|?*\x00-\x1f]', part) or part.endswith((' ', '.')) or
            re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', part)
            for part in parts):
        raise ValueError(f'整合包包含不安全路径：{value}')
    return path


def instance_name(value):
    path = safe_path(value)
    if len(path.parts) != 1 or len(value) > 100 or value != str(path):
        raise ValueError('实例名称必须是 1～100 个字符，不能包含路径或特殊文件名字符')
    return value


def suggested_name(archive):
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '-', Path(archive).stem).strip(' .')[:90]
    try:
        return instance_name(value)
    except ValueError:
        return 'Imported-Modpack'


_EXPORT_IGNORED_DIRECTORIES = {
    '.buggcraft-downloads', 'logs', 'crash-reports', 'screenshots', 'natives',
}
_BUGGCRAFT_RESOURCE_DIRECTORIES = {'mods', 'resourcepacks', 'shaderpacks'}
_BUGGCRAFT_DOWNLOAD_HOSTS = {
    'cdn.modrinth.com', 'github.com', 'raw.githubusercontent.com', 'gitlab.com',
    'edge.forgecdn.net', 'mediafilez.forgecdn.net',
}


def _valid_download_urls(value):
    """Return public HTTPS URLs accepted by the portable package format."""
    if not isinstance(value, list) or not 1 <= len(value) <= 16:
        return []
    result = []
    for url in value:
        if not isinstance(url, str) or len(url) > 8192 or re.search(r'[\s\x00-\x1f]', url):
            return []
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or parsed.hostname not in _BUGGCRAFT_DOWNLOAD_HOSTS
                or parsed.username or parsed.password or parsed.port not in (None, 443)):
            return []
        result.append(url)
    return result


def export_pack(directory, identity, destination, *, name=None, version='1.0.0', mode='compact',
                game_directory=None, progress=None, cancel=None):
    """Export an installed instance as the launcher's portable ``.buggpack``.

    Store a versioned manifest and portable files under ``files/``. Compact
    packages reference known, unchanged downloadable content; standard packages
    embed all portable content. Minecraft and its loader are installed on import.
    """
    def check():
        if cancel is not None and cancel.is_set():
            raise DownloadCancelled('导出已取消')

    check()
    if progress:
        progress('正在整理实例文件…', 0, 0)
    instance_name(identity)
    if mode not in ('compact', 'standard'):
        raise ValueError('导出模式必须是 compact 或 standard')
    root = Path(directory).resolve() / 'versions' / identity
    metadata_path = root / f'{identity}.json'
    if not root.is_dir() or not metadata_path.is_file():
        raise ValueError('找不到要导出的游戏实例或版本信息。')
    try:
        metadata = json.loads(metadata_path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError) as exc:
        raise ValueError('实例版本信息无法读取，不能导出。') from exc
    if not isinstance(metadata, dict):
        raise ValueError('实例版本信息格式无效，不能导出。')
    pack_metadata = metadata.get('buggcraftModpack')
    if not isinstance(pack_metadata, dict):
        pack_metadata = {}
    from hookup.rooms import instance_metadata
    content_root = Path(game_directory).resolve() if game_directory else root
    if content_root not in (root, Path(directory).resolve()):
        raise ValueError('游戏内容目录必须是实例目录或当前 Minecraft 目录。')
    detected = instance_metadata(directory, identity, content_root)
    minecraft = pack_metadata.get('minecraft') or detected['version']
    if not isinstance(minecraft, str) or not re.fullmatch(r'[A-Za-z0-9_.+-]{1,64}', minecraft):
        raise ValueError('无法确定实例的 Minecraft 版本，不能导出。')
    loader_names = {'forge': 'Forge', 'neoforge': 'NeoForge', 'fabric': 'Fabric', 'quilt': 'Quilt'}
    loader = pack_metadata.get('loader') or loader_names.get(detected['loader'], '')
    loader_version = pack_metadata.get('loaderVersion') or detected['loader_version']
    if loader and (loader not in ('Forge', 'NeoForge', 'Fabric', 'Quilt') or
                   not isinstance(loader_version, str) or
                   not re.fullmatch(r'[A-Za-z0-9_.+-]{1,64}', loader_version)):
        raise ValueError('实例加载器信息无效，不能导出。')
    dependency_names = {'Forge': 'forge', 'NeoForge': 'neoforge',
                        'Fabric': 'fabric-loader', 'Quilt': 'quilt-loader'}
    dependencies = {'minecraft': minecraft}
    if loader:
        dependencies[dependency_names[loader]] = loader_version
    pack_name = str(name or pack_metadata.get('name') or identity).strip()
    if not pack_name or len(pack_name) > 200:
        raise ValueError('整合包名称无效。')
    destination = Path(destination).expanduser().resolve()
    if destination.suffix.lower() not in ('.buggpack', '.zip'):
        destination = destination.with_suffix('.buggpack')
    if destination == root or destination.is_relative_to(root):
        raise ValueError('导出文件不能放在正在导出的实例目录内。')
    if destination == metadata_path or destination.is_dir():
        raise ValueError('导出位置无效。')
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError('导出文件已存在，请选择其他文件名。')

    manifest = {
        'format': 'buggcraft',
        'formatVersion': 1,
        'name': pack_name,
        'version': str(version),
        'minecraft': minecraft,
        'loader': loader,
        'loaderVersion': loader_version,
        'dependencies': dependencies,
        'recommendedRam': pack_metadata.get('recommendedRam', 0),
        'exportMode': mode,
        'files': [],
    }
    resource_records = {}
    records = pack_metadata.get('resources', [])
    if isinstance(records, list):
        for record in records:
            if isinstance(record, dict) and isinstance(record.get('path'), str):
                resource_records[record['path'].replace('\\', '/').casefold()] = record
    from core.content_records import read_records
    resource_records.update({record['path'].casefold(): record for record in read_records(content_root)})
    resource_records.update({record['path'].casefold(): record for record in read_records(root)})
    created = False
    try:
        archive = zipfile.ZipFile(destination, 'x', compression=zipfile.ZIP_DEFLATED,
                                  compresslevel=6)
        created = True
        with archive:
            entries = []
            included = 0
            externalized = 0
            sources = {}
            for path in root.rglob('*'):
                check()
                if path.is_file() and not path.is_symlink():
                    sources[path.relative_to(root).as_posix().casefold()] = path
            # Non-isolated launch profiles use the shared .minecraft content
            # folders. Include those portable files when the version folder
            # does not contain its own copy.
            for folder in (() if content_root == root else (
                    'mods', 'resourcepacks', 'shaderpacks', 'config',
                    'defaultconfigs', 'kubejs', 'scripts', 'saves')):
                shared = content_root / folder
                if shared.is_dir():
                    for path in shared.rglob('*'):
                        check()
                        if path.is_file() and not path.is_symlink():
                            relative_name = path.relative_to(Path(directory).resolve()).as_posix()
                            sources.setdefault(relative_name.casefold(), path)
            portable = []
            for relative_key in sorted(sources):
                check()
                source = sources[relative_key]
                if not source.is_file() or source.is_symlink():
                    continue
                try:
                    relative = source.relative_to(root)
                except ValueError:
                    relative = source.relative_to(Path(directory).resolve())
                if (relative.name in (f'{identity}.json', f'{identity}.jar', 'buggcraft-modpack.json')
                        or relative.parts[0] in _EXPORT_IGNORED_DIRECTORIES
                        or relative.parts[0].startswith('.buggcraft')):
                    continue
                safe_path(relative.as_posix())
                portable.append((source, relative, source.stat().st_size))
            total = sum(size * 2 for _, _, size in portable)
            done, last_report = 0, 0.

            def report(label, amount=0, force=False):
                nonlocal done, last_report
                done += amount
                now = time.monotonic()
                if progress and (force or now - last_report >= .08):
                    progress(label, done, total)
                    last_report = now

            for source, relative, size in portable:
                check()
                report('正在检查 ' + relative.as_posix(), force=True)
                digest = hashlib.sha256()
                sha1 = hashlib.sha1()
                with source.open('rb') as input_stream:
                    for chunk in iter(lambda: input_stream.read(1024 * 1024), b''):
                        check()
                        digest.update(chunk)
                        sha1.update(chunk)
                        report('正在检查 ' + relative.as_posix(), len(chunk))
                relative_name = relative.as_posix()
                size = source.stat().st_size
                record = resource_records.get(relative_name.casefold())
                downloads = _valid_download_urls(record.get('downloads')) if isinstance(record, dict) else []
                external = (mode == 'compact'
                            and relative.parts[0].casefold() in _BUGGCRAFT_RESOURCE_DIRECTORIES
                            and downloads and isinstance(record, dict) and record.get('size') == size
                            and (record.get('sha1') or record.get('sha256'))
                            and (not record.get('sha1') or str(record.get('sha1')).lower() == sha1.hexdigest())
                            and (not record.get('sha256') or str(record.get('sha256')).lower() == digest.hexdigest()))
                entry = {'path': relative_name, 'size': size, 'sha256': digest.hexdigest(),
                         'sha1': sha1.hexdigest(), 'embedded': not external}
                if external:
                    entry['downloads'] = downloads
                    externalized += 1
                    report('已整理 ' + relative_name, size)
                else:
                    report('正在打包 ' + relative_name, force=True)
                    archive_name = 'files/' + relative_name
                    with source.open('rb') as input_stream, archive.open(archive_name, 'w') as output_stream:
                        for chunk in iter(lambda: input_stream.read(1024 * 1024), b''):
                            check()
                            output_stream.write(chunk)
                            report('正在打包 ' + relative_name, len(chunk))
                    included += 1
                entries.append(entry)
            manifest['files'] = entries
            archive.writestr('buggcraft.pack.json',
                             json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
            check()
        if progress:
            progress('整合包已导出', max(total, 1), max(total, 1))
    except Exception:
        if created:
            destination.unlink(missing_ok=True)
        raise
    return {'path': str(destination), 'name': pack_name, 'minecraft': minecraft,
            'loader': loader, 'loader_version': loader_version, 'files': included,
            'external_files': externalized, 'mode': mode}


@dataclass(frozen=True)
class PackInfo:
    name: str
    version: str
    minecraft: str
    loader: str
    loader_version: str
    overrides: str
    files: tuple
    recommended_ram: int
    expanded_bytes: int
    source: str = 'CurseForge'
    override_layers: tuple = ()


def _inspect_modrinth(manifest, expanded, path):
    if not isinstance(manifest, dict) or type(manifest.get('formatVersion')) is not int or manifest['formatVersion'] != 1 or manifest.get('game') != 'minecraft':
        raise ValueError('不支持的 Modrinth 整合包清单版本')
    dependencies = manifest.get('dependencies')
    mapping = {'forge': 'Forge', 'neoforge': 'NeoForge', 'fabric-loader': 'Fabric', 'quilt-loader': 'Quilt'}
    if not isinstance(dependencies, dict) or not re.fullmatch(r'[A-Za-z0-9_.+-]{1,64}', str(dependencies.get('minecraft', ''))):
        raise ValueError('整合包 Minecraft 版本无效')
    parsed = []
    for key, value in dependencies.items():
        if key == 'minecraft':
            continue
        if key not in mapping or not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.+-]{1,64}', value):
            raise ValueError('整合包包含暂不支持的依赖：' + str(key))
        parsed.append((mapping[key], value))
    validate_loaders([name for name, version in parsed])
    files = manifest.get('files')
    if not isinstance(files, list) or len(files) > 10000:
        raise ValueError('整合包文件清单无效')
    refs, names, total = [], set(), 0
    hosts = {'cdn.modrinth.com', 'github.com', 'raw.githubusercontent.com', 'gitlab.com',
             'edge.forgecdn.net', 'mediafilez.forgecdn.net'}
    for item in files:
        if not isinstance(item, dict):
            raise ValueError('Modrinth 文件条目无效')
        relative = str(safe_path(item.get('path')))
        if relative.casefold() in names:
            raise ValueError('整合包包含重名下载文件：' + relative)
        names.add(relative.casefold())
        hashes = item.get('hashes')
        if not isinstance(hashes, dict) or any(not isinstance(hashes.get(key), str) or
                not re.fullmatch('[0-9a-fA-F]{' + str(length) + '}', hashes[key]) for key, length in (('sha1', 40), ('sha512', 128))):
            raise ValueError('Modrinth 文件缺少有效 SHA1/SHA512 校验值')
        urls = item.get('downloads')
        if not isinstance(urls, list) or not 1 <= len(urls) <= 16:
            raise ValueError('Modrinth 文件下载地址无效')
        for url in urls:
            if not isinstance(url, str) or len(url) > 8192 or re.search(r'[\s\x00-\x1f]', url):
                raise ValueError('Modrinth 文件下载地址无效')
            parsed_url = urlsplit(url)
            if (parsed_url.scheme != 'https' or parsed_url.hostname not in hosts or parsed_url.username
                    or parsed_url.password or parsed_url.port not in (None, 443)):
                raise ValueError('Modrinth 文件下载地址不属于受支持的 HTTPS 来源')
        if type(item.get('fileSize')) is not int or item['fileSize'] < 0:
            raise ValueError('Modrinth 文件大小无效')
        total += item['fileSize']
        if total + expanded > MAX_EXPANDED:
            raise ValueError('整合包展开和下载总大小超过 8 GiB')
        env = item.get('env', {})
        if not isinstance(env, dict) or any(value not in ('required', 'optional', 'unsupported') for value in env.values()):
            raise ValueError('Modrinth 文件环境声明无效')
        if env.get('client') == 'unsupported':
            continue
        refs.append(dict(item, path=relative, hashes={key: hashes[key].lower() for key in ('sha1', 'sha512')}))
    return PackInfo(str(manifest.get('name') or Path(path).stem), str(manifest.get('versionId', '')),
                    dependencies['minecraft'], *(parsed[0] if parsed else ('', '')), 'overrides',
                    tuple(refs), 0, expanded, 'Modrinth', ('overrides', 'client-overrides'))


def _inspect_buggcraft(manifest, archive, expanded, path):
    if (not isinstance(manifest, dict) or manifest.get('format') != 'buggcraft' or
            manifest.get('formatVersion') != 1):
        raise ValueError('不支持的 Buggcraft 整合包清单版本')
    minecraft = manifest.get('minecraft')
    if not isinstance(minecraft, str) or not re.fullmatch(r'[A-Za-z0-9_.+-]{1,64}', minecraft):
        raise ValueError('整合包 Minecraft 版本无效')
    loader = manifest.get('loader') or ''
    loader_version = manifest.get('loaderVersion') or ''
    if loader and (loader not in ('Forge', 'NeoForge', 'Fabric', 'Quilt') or
                   not isinstance(loader_version, str) or
                   not re.fullmatch(r'[A-Za-z0-9_.+-]{1,64}', loader_version)):
        raise ValueError('整合包加载器信息无效')
    files = manifest.get('files')
    if not isinstance(files, list) or len(files) > MAX_ENTRIES:
        raise ValueError('Buggcraft 文件清单无效')
    names, refs, total = set(), [], 0
    for item in files:
        if not isinstance(item, dict):
            raise ValueError('Buggcraft 文件条目无效')
        relative = str(safe_path(item.get('path')))
        if relative.casefold() in names or relative.casefold().startswith('.buggcraft'):
            raise ValueError('Buggcraft 文件路径重复或保留')
        names.add(relative.casefold())
        size, digest = item.get('size'), item.get('sha256')
        if type(size) is not int or size < 0 or not re.fullmatch(r'[0-9a-fA-F]{64}', str(digest or '')):
            raise ValueError('Buggcraft 文件缺少有效 SHA-256 校验值')
        sha1 = item.get('sha1')
        if sha1 is not None and not re.fullmatch(r'[0-9a-fA-F]{40}', str(sha1)):
            raise ValueError('Buggcraft file has an invalid SHA-1')
        embedded = item.get('embedded', True)
        if not isinstance(embedded, bool):
            raise ValueError('Buggcraft embedded flag is invalid')
        if not embedded:
            downloads = _valid_download_urls(item.get('downloads'))
            if not downloads or not sha1:
                raise ValueError('External Buggcraft files require HTTPS downloads and SHA-1')
            total += size
            if total + expanded > MAX_EXPANDED:
                raise ValueError('Package expanded and download size exceeds 8 GiB')
            hashes = {'sha256': digest.lower(), 'sha1': str(sha1).lower()}
            if item.get('sha512') is not None:
                if not re.fullmatch(r'[0-9a-fA-F]{128}', str(item['sha512'])):
                    raise ValueError('Buggcraft file has an invalid SHA-512')
                hashes['sha512'] = str(item['sha512']).lower()
            refs.append({'path': relative, 'fileSize': size, 'hashes': hashes,
                         'downloads': downloads, 'embedded': False})
            continue
        archive_name = 'files/' + relative
        try:
            member = archive.getinfo(archive_name)
        except KeyError as exc:
            raise ValueError('Buggcraft 缺少文件：' + relative) from exc
        if member.file_size != size:
            raise ValueError('Buggcraft 文件大小校验失败：' + relative)
        current = hashlib.sha256()
        with archive.open(member) as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                current.update(chunk)
        if current.hexdigest().lower() != digest.lower():
            raise ValueError('Buggcraft 文件 SHA-256 校验失败：' + relative)
        hashes = {'sha256': digest.lower()}
        if sha1:
            hashes['sha1'] = str(sha1).lower()
        refs.append({'path': relative, 'fileSize': size, 'hashes': hashes,
                     'archivePath': archive_name, 'embedded': True})
    archive_files = {item.filename for item in archive.infolist() if not item.is_dir()}
    expected = {'buggcraft.pack.json'} | {item['archivePath'] for item in refs if item.get('archivePath')}
    if archive_files != expected:
        raise ValueError('Buggcraft 包含清单之外的文件')
    ram = manifest.get('recommendedRam', 0)
    return PackInfo(str(manifest.get('name') or Path(path).stem), str(manifest.get('version', '')),
                    minecraft, loader, loader_version, 'files', tuple(refs),
                    ram if type(ram) is int and 0 <= ram <= 1048576 else 0,
                    expanded, 'Buggcraft', ('files',))


def inspect_pack(path):
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        expanded = sum(item.file_size for item in members)
        if len(members) > MAX_ENTRIES or expanded > MAX_EXPANDED:
            raise ValueError('整合包过大：最多 50000 个文件、展开后最多 8 GiB')
        seen = set()
        for item in members:
            normalized = str(safe_path(item.filename)).casefold()
            if normalized in seen or stat.S_ISLNK(item.external_attr >> 16) or item.flag_bits & 1:
                raise ValueError(f'整合包包含重复、链接或加密文件：{item.filename}')
            seen.add(normalized)
        manifests = [name for name in ('buggcraft.pack.json', 'manifest.json', 'modrinth.index.json')
                     if name in archive.namelist()]
        if len(manifests) != 1:
            raise ValueError('整合包根目录需包含唯一的 manifest.json（CurseForge）或 modrinth.index.json（Modrinth）')
        info = archive.getinfo(manifests[0])
        if info.file_size > 4 * 1024 ** 2:
            raise ValueError('整合包清单过大')
        manifest = json.loads(archive.read(info).decode('utf-8-sig'))
        if manifests[0] == 'buggcraft.pack.json':
            return _inspect_buggcraft(manifest, archive, expanded, path)
        if manifests[0] == 'modrinth.index.json':
            return _inspect_modrinth(manifest, expanded, path)
    if not isinstance(manifest, dict) or manifest.get('manifestType') != 'minecraftModpack' \
            or manifest.get('manifestVersion') != 1:
        raise ValueError('不支持的 CurseForge 整合包清单版本')
    minecraft = manifest.get('minecraft', {})
    if not isinstance(minecraft, dict) or not re.fullmatch(r'[A-Za-z0-9_.+-]{1,64}', str(minecraft.get('version', ''))):
        raise ValueError('整合包 Minecraft 版本无效')
    loaders = minecraft.get('modLoaders', [])
    if not isinstance(loaders, list):
        raise ValueError('整合包加载器清单无效')
    parsed = []
    mapping = {'forge': 'Forge', 'neoforge': 'NeoForge', 'fabric': 'Fabric', 'quilt': 'Quilt'}
    for loader in loaders:
        match = re.fullmatch(r'(forge|neoforge|fabric|quilt)-([A-Za-z0-9_.+-]{1,64})',
                             str(loader.get('id', '')) if isinstance(loader, dict) else '')
        if not match:
            raise ValueError('整合包包含暂不支持的加载器')
        parsed.append((mapping[match[1]], match[2]))
    validate_loaders([name for name, version in parsed])
    files = manifest.get('files', [])
    if not isinstance(files, list) or len(files) > 10000:
        raise ValueError('整合包文件清单无效')
    refs = []
    for item in files:
        if not isinstance(item, dict) or any(type(item.get(key)) is not int or item[key] <= 0
                                              for key in ('projectID', 'fileID')):
            raise ValueError('整合包模组项目或文件 ID 无效')
        # Install optional entries too: this preserves the author's exported set.
        ref = (item['projectID'], item['fileID'])
        if ref not in refs:
            refs.append(ref)
    overrides = str(safe_path(manifest.get('overrides', 'overrides')))
    ram = minecraft.get('recommendedRam', 0)
    return PackInfo(str(manifest.get('name', Path(path).stem)), str(manifest.get('version', '')),
                    minecraft['version'], *(parsed[0] if parsed else ('', '')), overrides,
                    tuple(refs), ram if type(ram) is int and 0 <= ram <= 1048576 else 0, expanded)


class CurseForgeClient(CurseForgeAPI):
    def resolve(self, refs):
        self.fallback_urls = {}
        projects, files = {}, {}
        project_ids = list(dict.fromkeys(project for project, file in refs))
        file_ids = list(dict.fromkeys(file for project, file in refs))
        requests = ([('/mods', {'modIds': project_ids[start:start+50]}, projects)
                     for start in range(0, len(project_ids), 50)] +
                    [('/mods/files', {'fileIds': file_ids[start:start+50]}, files)
                     for start in range(0, len(file_ids), 50)])
        if requests:
            with ThreadPoolExecutor(max_workers=min(4, len(requests)), thread_name_prefix='pack-metadata') as pool:
                futures = {pool.submit(self.post, route, body): destination for route, body, destination in requests}
                for future in as_completed(futures):
                    futures[future].update({item['id']: item for item in future.result()})
        jobs, names = [], set()
        for project_id, file_id in refs:
            project, item = projects.get(project_id, {}), files.get(file_id, {})
            link = f'https://www.curseforge.com/minecraft/mc-mods/{project_id}/files/{file_id}'
            if item.get('modId') != project_id:
                raise ValueError(f'CurseForge 文件缺失或项目不匹配（项目 {project_id}，文件 {file_id}）：{link}')
            folder = {6: 'mods', 12: 'resourcepacks', 6552: 'shaderpacks'}.get(project.get('classId'))
            if not folder:
                raise ValueError(f'暂不支持该 CurseForge 内容类别：项目 {project_id}')
            name = item.get('fileName', '')
            if len(safe_path(name).parts) != 1 or len(name) > 255 or name != str(safe_path(name)):
                raise ValueError('CurseForge 返回的文件名无效')
            relative = folder + '/' + name
            if relative.casefold() in names:
                raise ValueError(f'整合包包含重名下载文件：{name}')
            names.add(relative.casefold())
            url = download_url(item)
            sha1 = next((entry.get('value') for entry in item.get('hashes', []) if entry.get('algo') == 1), '')
            if not re.fullmatch('[0-9a-fA-F]{40}', sha1) or type(item.get('fileLength')) is not int or item['fileLength'] <= 0:
                raise ValueError(f'CurseForge 文件缺少校验信息：{name}')
            jobs.append((url, relative, sha1.lower(), item['fileLength']))
            # Restricted redistribution never goes through our file proxy.
            # The player's direct public-CDN download still uses exact hashes.
            if project.get('allowModDistribution') is not False:
                self.fallback_urls[url] = fallback_url(project_id, file_id)
        return jobs


class ModpackImporter:
    def __init__(self, directory, source='自动', java=None, cancel=None, status=None, progress=None, api_key=None,
                 content_source=None, file_event=None):
        self.root = Path(directory).resolve()
        self.source, self.java = source, java
        self.content_source = content_source
        self.cancel = cancel if cancel is not None else threading.Event()
        self.status = status or (lambda value: None)
        self.progress = progress or (lambda done, total: None)
        self.file_event = file_event
        self.client = CurseForgeClient(api_key, self.cancel, mirror=content_source or '官方')

    def check(self):
        if self.cancel.is_set():
            raise DownloadCancelled('整合包导入已取消，已校验下载会在重试时复用')

    def install(self, archive_path, identity, *, expected_archive_sha256=None, archive_identified=None):
        with use_download_budget():
            return self._install(archive_path, identity, expected_archive_sha256=expected_archive_sha256,
                                 archive_identified=archive_identified)

    def _install(self, archive_path, identity, *, expected_archive_sha256=None, archive_identified=None):
        instance_name(identity)
        info = inspect_pack(archive_path)
        target = disk_path(self.root / 'versions' / identity)
        if target.exists():
            raise ValueError('该实例名称已存在，请更换名称；整合包导入不会覆盖已有实例')
        self.check()
        self.progress(0, 0)
        self.status('[1/5] 正在解析 ' + info.source + ' 文件清单…')
        digest = hashlib.sha256()
        with open(archive_path, 'rb') as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b''):
                self.check()
                digest.update(chunk)
        archive_hash = digest.hexdigest()
        if expected_archive_sha256 and archive_hash != expected_archive_sha256:
            raise ValueError('原整合包文件已被替换，无法继续上次任务。请恢复原文件；新整合包请使用新的实例名称导入。')
        if archive_identified:
            archive_identified(archive_hash)
        if info.source == 'Modrinth':
            jobs = [(item['downloads'][0], item['path'], item['hashes']['sha1'].lower(), item['fileSize']) for item in info.files]
            for _, relative, _, _ in jobs:
                first = safe_path(relative).parts[0].casefold()
                if first.startswith('.buggcraft') or first in ('natives', 'buggcraft-modpack.json', identity.casefold() + '.json', identity.casefold() + '.jar'):
                    raise ValueError('整合包不能覆盖启动器元数据：' + relative)
        elif info.source == 'Buggcraft':
            # Compact exports keep verified downloadable resources outside the
            # archive. Embedded entries are copied from the package itself.
            jobs = [(item['downloads'][0], item['path'], item['hashes']['sha1'], item['fileSize'])
                    for item in info.files if not item.get('embedded', True)]
        else:
            jobs = self.client.resolve(info.files) if info.files else []
        self.check()
        cache = self.root / '.buggcraft-downloads' / 'modpacks' / archive_hash
        cache.mkdir(parents=True, exist_ok=True)
        downloading = threading.Event()
        downloading.set()
        progress_lock = threading.Lock()
        download_progress = [0, len(jobs)]

        def report_download(done, total):
            with progress_lock:
                download_progress[:] = [done, total]
                if not downloading.is_set():
                    self.progress(done, total)

        downloader = MinecraftDownloader(cache / 'files', source=self.source, cancel=self.cancel,
                                         status=self.status, progress=report_download, file_event=self.file_event)
        downloader.content_source = self.content_source
        downloader.curseforge_key = self.client.api_key
        downloader.curseforge_fallbacks = getattr(self.client, 'fallback_urls', {})
        if info.source in ('Modrinth', 'Buggcraft'):
            downloader.file_mirrors = {item['downloads'][0]: item['downloads'][1:]
                                       for item in info.files if item.get('downloads')}
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix='modpack-resources') as pool:
            future = pool.submit(downloader._batch, jobs, '[2/5] 正在下载并校验整合包模组和资源…')
            try:
                self.check()
                self.progress(0, 0)
                self.status('[3/5] 正在并行安装 Minecraft 和加载器…')
                from utils.download_locks import download_lock
                with download_lock(self.root / '.buggcraft-loader-install', self.cancel):
                    resources = self._resource_records(info, jobs, downloader)
                    return self._install_instance(archive_path, identity, info, archive_hash, cache, downloader,
                                                  jobs, resources, target, future, downloading, download_progress)
            except BaseException:
                self.cancel.set()
                raise

    def _verify_external_files(self, info, downloader):
        if info.source in ('Modrinth', 'Buggcraft'):
            for item in info.files:
                if info.source == 'Buggcraft' and item.get('embedded', True):
                    continue
                self.check()
                algorithm = 'sha512' if info.source == 'Modrinth' else 'sha256'
                digest = hashlib.new(algorithm)
                with downloader.inside(item['path']).open('rb') as source:
                    for chunk in iter(lambda: source.read(1024 * 1024), b''):
                        self.check()
                        digest.update(chunk)
                if digest.hexdigest().lower() != item['hashes'][algorithm].lower():
                    error = info.source + ' 文件 ' + algorithm.upper() + ' 校验失败'
                    downloader._file_event(item['path'], 'failed', error=error)
                    downloader.inside(item['path']).unlink(missing_ok=True)
                    raise ValueError(error + '：' + item['path'])

    def _install_vanilla(self, version):
        MinecraftDownloader(self.root, source=self.source, cancel=self.cancel,
                            status=self.status, progress=self.progress,
                            file_event=self.file_event).install(version)

    def _resource_records(self, info, jobs, downloader):
        """Persist verified download metadata for a later compact export."""
        if info.source == 'Buggcraft':
            return [dict(path=item['path'], size=item['fileSize'],
                         sha1=item['hashes'].get('sha1'), sha256=item['hashes'].get('sha256'),
                         sha512=item['hashes'].get('sha512'), downloads=item.get('downloads', []))
                    for item in info.files]
        if info.source == 'Modrinth':
            return [dict(path=item['path'], size=item['fileSize'],
                         sha1=item['hashes'].get('sha1'), sha512=item['hashes'].get('sha512'),
                         downloads=item.get('downloads', [])) for item in info.files]
        fallbacks = getattr(downloader, 'curseforge_fallbacks', {}) or {}
        return [dict(path=relative, size=size, sha1=sha1,
                     downloads=[url] + ([fallbacks[url]] if fallbacks.get(url) else []))
                for url, relative, sha1, size in jobs]

    def _install_instance(self, archive_path, identity, info, archive_hash, cache, downloader, jobs,
                          resources, target, future, downloading, download_progress):
        # Loader setup and intermediate cleanup form one transaction. Other
        # modpack tasks can still fetch their resources concurrently.
        versions_root = self.root / 'versions'
        before_versions = {item.name for item in versions_root.iterdir()} if versions_root.exists() else set()
        receipt = cache / ('intermediates-' + hashlib.sha256(identity.encode()).hexdigest() + '.json')
        # A failed loader/extraction may already have written vanilla and loader
        # profiles. Keep their ownership across retry, but only if untouched
        # since the previous attempt; existing or changed installs stay intact.
        try:
            previous = json.loads(receipt.read_text(encoding='utf-8'))
            if isinstance(previous, dict):
                for name, stamp in previous.items():
                    if (stamp is not None and name in before_versions
                            and self._intermediate_stamp(versions_root / name) == stamp):
                        before_versions.discard(name)
        except (OSError, ValueError):
            pass
        try:
            return self._assemble_instance(archive_path, identity, info, archive_hash, cache,
                                           downloader, jobs, resources, target, before_versions,
                                           future, downloading, download_progress)
        finally:
            try:
                if target.exists():
                    receipt.unlink(missing_ok=True)
                elif versions_root.exists():
                    created = {item.name: self._intermediate_stamp(item) for item in versions_root.iterdir()
                               if item.name not in before_versions and item.is_dir() and not item.is_symlink()}
                    receipt.write_text(json.dumps(created), encoding='utf-8')
            except OSError:
                logging.getLogger(__name__).warning('Could not retain intermediate installation ownership', exc_info=True)

    @staticmethod
    def _intermediate_stamp(directory):
        try:
            if directory.is_symlink():
                return None
            return [[item.relative_to(directory).as_posix(), item.stat().st_size, item.stat().st_mtime_ns]
                    for item in sorted(directory.rglob('*'))]
        except OSError:
            return None

    def _assemble_instance(self, archive_path, identity, info, archive_hash, cache, downloader, jobs, resources,
                           target, before_versions, future, downloading, download_progress):
        # Modrinth and Buggcraft publish stronger hashes than the transfer's
        # SHA-1 check. The vanilla game can download alongside package files,
        # but the loader installer waits for their stronger hash verification.
        if info.source in ('Modrinth', 'Buggcraft'):
            with ThreadPoolExecutor(max_workers=1, thread_name_prefix='pack-vanilla') as pool:
                vanilla = pool.submit(copy_context().run, self._install_vanilla, info.minecraft)
                try:
                    future.result()
                    self._verify_external_files(info, downloader)
                    self.check()
                    vanilla.result()
                except BaseException:
                    self.cancel.set()
                    raise
        if info.loader:
            installed = install_loader(info.loader, info.minecraft, info.loader_version, str(self.root), self.java,
                {'setStatus': lambda value: self.status('[3/5] ' + str(value)),
                 'setProgress': lambda done: self.progress(done, -1),
                 'setMax': lambda total: self.progress(-1, total),
                 'fileEvent': self.file_event}, self.cancel, source=self.source)
        else:
            if info.source not in ('Modrinth', 'Buggcraft'):
                self._install_vanilla(info.minecraft)
            installed = info.minecraft
        instance_name(installed)
        if not (self.root / 'versions' / installed / (installed + '.json')).is_file():
            raise ValueError('加载器安装未生成有效版本文件')
        downloading.clear()
        if not future.done():
            self.status('[3/5] 正在等待整合包模组和资源下载完成…')
            self.progress(*download_progress)
        future.result()
        if info.source not in ('Modrinth', 'Buggcraft'):
            self._verify_external_files(info, downloader)
        self.check()
        stage = disk_path(tempfile.mkdtemp(prefix='instance-', dir=cache))
        try:
            for url, relative, sha1, size in jobs:
                self.check()
                destination = stage / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(downloader.inside(relative), destination)
            self.progress(0, 0)
            self.status('[4/5] 正在解压整合包配置…')
            with zipfile.ZipFile(archive_path) as archive:
                prefixes = [layer.rstrip('/') + '/' for layer in info.override_layers or (info.overrides,)]
                overrides = [(item, prefix) for prefix in prefixes for item in archive.infolist()
                             if item.filename.startswith(prefix) and not item.is_dir()]
                downloaded = {relative.casefold(): (sha1, size) for url, relative, sha1, size in jobs}
                for index, (item, prefix) in enumerate(overrides):
                    self.check()
                    relative = safe_path(item.filename[len(prefix):])
                    if relative.parts[0].casefold().startswith('.buggcraft') or relative.parts[0].casefold() in ('natives', 'buggcraft-modpack.json', identity.casefold() + '.json', identity.casefold() + '.jar'):
                        raise ValueError(f'整合包不能覆盖启动器元数据：{relative}')
                    destination = stage.joinpath(*relative.parts)
                    if destination.exists() and info.source != 'Modrinth':
                        expected = downloaded.get(str(relative).casefold())
                        digest = hashlib.sha1()
                        with archive.open(item) as source:
                            for chunk in iter(lambda: source.read(1024 * 1024), b''):
                                self.check()
                                digest.update(chunk)
                        if not expected or (digest.hexdigest(), item.file_size) != expected:
                            raise ValueError(f'整合包覆盖了已校验的下载文件：{relative}')
                        # Some exports bundle an exact copy of a manifest file.
                        # Reading it above also validates the ZIP member CRC.
                        self.progress(index + 1, len(overrides))
                        continue
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(item) as source, destination.open('wb') as output:
                        while chunk := source.read(1024 * 1024):
                            self.check()
                            output.write(chunk)
                    self.progress(index + 1, len(overrides))
            jar, seen = installed, set()
            while True:
                instance_name(jar)
                if jar in seen:
                    raise ValueError('加载器版本继承存在循环')
                seen.add(jar)
                parent = json.loads((self.root / 'versions' / jar / (jar + '.json')).read_text(encoding='utf-8'))
                if parent.get('jar'):
                    jar = instance_name(parent['jar'])
                    break
                if not parent.get('inheritsFrom'):
                    break
                jar = parent['inheritsFrom']
            # Publish the pack as one ordinary launcher version. Keeping an
            # alias with inheritsFrom makes launchers that scan versions offer
            # the vanilla and loader intermediary entries as separate games.
            # Resolve the full loader chain now, then place its client JAR and
            # flattened metadata beside the imported pack.
            from core.launch_preparation import resolved_metadata, version_chain
            chain = version_chain(self.root, installed)
            resolved = resolved_metadata(chain)
            core_jar = self.root / 'versions' / jar / (jar + '.jar')
            if not core_jar.is_file():
                raise FileNotFoundError(f'缺少游戏核心：{core_jar}')
            resolved.pop('inheritsFrom', None)
            resolved.pop('jar', None)
            resolved['id'] = identity
            resolved['clientVersion'] = info.minecraft
            shutil.copyfile(core_jar, stage / (identity + '.jar'))
            # Older Minecraft releases load extracted natives from their version
            # directory. Move these into the combined instance before cleanup.
            for name, _ in reversed(chain):
                natives = self.root / 'versions' / name / 'natives'
                if natives.is_dir():
                    shutil.copytree(natives, stage / 'natives', dirs_exist_ok=True)
            self.progress(0, 0)
            self.status('[5/5] 正在保存独立游戏实例…')
            metadata = resolved
            metadata['buggcraftModpack'] = {'name': info.name, 'version': info.version, 'minecraft': info.minecraft,
                                            'loader': info.loader, 'loaderVersion': info.loader_version,
                                            'archiveSha256': archive_hash, 'recommendedRam': info.recommended_ram,
                                            'source': info.source, 'resources': resources}
            # Display metadata is optional for aliases. Include it when available
            # for compatibility with other launchers, without inventing dates.
            for key in ('type', 'time', 'releaseTime'):
                value = parent.get(key)
                if isinstance(value, str) and value:
                    metadata[key] = value
            (stage / (identity + '.json')).write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
            (stage / 'buggcraft-modpack.json').write_text(json.dumps(metadata['buggcraftModpack'], ensure_ascii=False, indent=2), encoding='utf-8')
            self.check()
            target.parent.mkdir(parents=True, exist_ok=True)
            # rename refuses an existing target on Windows; an explicit check also
            # protects existing empty instance directories on other platforms.
            if target.exists():
                raise ValueError('实例名称已被占用，请换名重试')
            # A newly written mod JAR may briefly remain open in a Windows
            # virus scanner. Keep publication atomic and wait only briefly.
            for attempt in range(31):
                self.check()
                if target.exists():
                    raise ValueError('实例名称已被占用，请换名重试')
                try:
                    stage.rename(target)
                    break
                except PermissionError:
                    if attempt == 30:
                        raise
                    if attempt == 0:
                        self.status('[5/5] 文件暂被占用，正在等待 Windows 释放后保存实例…')
                    if self.cancel.wait(0.5):
                        self.check()
            # The loader installation may have created one vanilla and one
            # loader directory. Remove only those created by this transaction,
            # and retain any that another installed version still inherits.
            self._remove_unused_intermediates(target, before_versions, chain)
            self.status('整合包导入完成')
            return identity
        finally:
            if stage.exists():
                shutil.rmtree(stage)

    def _remove_unused_intermediates(self, target, before_versions, chain):
        versions = disk_path(self.root / 'versions')
        created = {name for name, _ in chain} - before_versions - {target.name}
        referenced = set()
        for metadata_path in versions.glob('*/*.json'):
            if metadata_path.parent.name in created or metadata_path.parent.name == target.name:
                continue
            try:
                metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                continue
            if not isinstance(metadata, dict):
                continue
            for key in ('inheritsFrom', 'jar'):
                value = metadata.get(key)
                if isinstance(value, str):
                    referenced.add(value)
        # Preserve transitive ancestors of a concurrently published alias too.
        for _ in chain:
            for name, metadata in chain:
                if name in referenced:
                    referenced.update(value for key in ('inheritsFrom', 'jar')
                                      if isinstance(value := metadata.get(key), str))
        for name in created - referenced:
            path = (versions / name).resolve()
            if path.parent != versions.resolve() or (versions / name).is_symlink():
                continue
            shutil.rmtree(path, ignore_errors=True)
