"""Validated CurseForge pack inspection and transactional instance import."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import threading
import zipfile

from core.downloads import DownloadCancelled, MinecraftDownloader
from core.loaders import install_loader
from core.loader_rules import validate_loaders
from core.curseforge import CurseForgeAPI, download_url, fallback_url

MAX_EXPANDED = 8 * 1024 ** 3
MAX_ENTRIES = 50000


def disk_path(path):
    """Use Windows extended paths for deeply nested author-supplied configs."""
    path = Path(path).absolute()
    value = str(path)
    if os.name == 'nt' and not value.startswith('\\\\?\\'):
        value = '\\\\?\\UNC\\' + value[2:] if value.startswith('\\\\') else '\\\\?\\' + value
    return Path(value)


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
        try:
            info = archive.getinfo('manifest.json')
        except KeyError as exc:
            raise ValueError('暂只支持 CurseForge 整合包（ZIP 根目录需包含 manifest.json）') from exc
        if info.file_size > 4 * 1024 ** 2:
            raise ValueError('整合包清单过大')
        manifest = json.loads(archive.read(info).decode('utf-8-sig'))
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
        for start in range(0, len(project_ids), 50):
            projects.update({item['id']: item for item in self.post('/mods', {'modIds': project_ids[start:start+50]})})
        for start in range(0, len(file_ids), 50):
            files.update({item['id']: item for item in self.post('/mods/files', {'fileIds': file_ids[start:start+50]})})
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
    def __init__(self, directory, source='自动', java=None, cancel=None, status=None, progress=None, api_key=None):
        self.root = Path(directory).resolve()
        self.source, self.java = source, java
        self.cancel = cancel if cancel is not None else threading.Event()
        self.status = status or (lambda value: None)
        self.progress = progress or (lambda done, total: None)
        self.client = CurseForgeClient(api_key, self.cancel)

    def check(self):
        if self.cancel.is_set():
            raise DownloadCancelled('整合包导入已取消，已校验下载会在重试时复用')

    def install(self, archive_path, identity):
        instance_name(identity)
        info = inspect_pack(archive_path)
        target = disk_path(self.root / 'versions' / identity)
        if target.exists():
            raise ValueError('该实例名称已存在，请更换名称；整合包导入不会覆盖已有实例')
        self.check()
        self.progress(0, 0)
        self.status('[1/5] 正在解析 CurseForge 文件清单…')
        jobs = self.client.resolve(info.files) if info.files else []
        self.check()
        digest = hashlib.sha256()
        with open(archive_path, 'rb') as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b''):
                self.check()
                digest.update(chunk)
        archive_hash = digest.hexdigest()
        cache = self.root / '.buggcraft-downloads' / 'modpacks' / archive_hash
        cache.mkdir(parents=True, exist_ok=True)
        downloader = MinecraftDownloader(cache / 'files', source=self.source, cancel=self.cancel,
                                         status=self.status, progress=self.progress)
        downloader.curseforge_key = self.client.api_key
        downloader.curseforge_fallbacks = getattr(self.client, 'fallback_urls', {})
        downloader._batch(jobs, '[2/5] 正在下载并校验整合包模组和资源…')
        self.check()
        self.progress(0, 0)
        self.status('[3/5] 正在安装 Minecraft 和加载器…')
        if info.loader:
            installed = install_loader(info.loader, info.minecraft, info.loader_version, str(self.root), self.java,
                {'setStatus': lambda value: self.status('[3/5] ' + str(value)),
                 'setProgress': lambda done: self.progress(done, -1),
                 'setMax': lambda total: self.progress(-1, total)}, self.cancel, source=self.source)
        else:
            MinecraftDownloader(self.root, source=self.source, cancel=self.cancel,
                                 status=self.status, progress=self.progress).install(info.minecraft)
            installed = info.minecraft
        instance_name(installed)
        if not (self.root / 'versions' / installed / (installed + '.json')).is_file():
            raise ValueError('加载器安装未生成有效版本文件')
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
                prefix = info.overrides.rstrip('/') + '/'
                overrides = [item for item in archive.infolist() if item.filename.startswith(prefix) and not item.is_dir()]
                downloaded = {relative.casefold(): (sha1, size) for url, relative, sha1, size in jobs}
                for index, item in enumerate(overrides):
                    self.check()
                    relative = safe_path(item.filename[len(prefix):])
                    if relative.parts[0].casefold().startswith('.buggcraft') or relative.parts[0].casefold() in ('natives', identity.casefold() + '.json', identity.casefold() + '.jar'):
                        raise ValueError(f'整合包不能覆盖启动器元数据：{relative}')
                    destination = stage.joinpath(*relative.parts)
                    if destination.exists():
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
            self.progress(0, 0)
            self.status('[5/5] 正在保存独立游戏实例…')
            metadata = {'id': identity, 'inheritsFrom': installed, 'jar': jar,
                        'buggcraftModpack': {'name': info.name, 'version': info.version, 'minecraft': info.minecraft,
                                            'loader': info.loader, 'loaderVersion': info.loader_version,
                                            'archiveSha256': archive_hash, 'recommendedRam': info.recommended_ram}}
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
            self.status('整合包导入完成')
            return identity
        finally:
            if stage.exists():
                shutil.rmtree(stage)
