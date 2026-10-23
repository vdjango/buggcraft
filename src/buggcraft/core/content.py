"""Content catalogues and verified installation from their original publishers."""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlsplit

import requests

from core.downloads import DownloadCancelled, _DownloadSession
from core.curseforge import CurseForgeContentClient, fallback_url

API = 'https://api.modrinth.com/v2'
KINDS = {'mod': 'mods', 'resourcepack': 'resourcepacks', 'shader': 'shaderpacks', 'modpack': 'modpacks'}


def _json_param(value):
    return json.dumps(value, separators=(',', ':'))


class ModrinthClient:
    def __init__(self, cancel=None):
        self.cancel = cancel if cancel is not None else threading.Event()

    def _get(self, path, params=None):
        if self.cancel.is_set():
            raise DownloadCancelled('内容下载已取消')
        with requests.get(API + path, params=params, timeout=(8, 30),
                          headers={'User-Agent': 'Buggcraft/1.0'}) as response:
            response.raise_for_status()
            data = response.json()
        if self.cancel.is_set():
            raise DownloadCancelled('内容查询已取消')
        if not isinstance(data, (dict, list)):
            raise ValueError('Modrinth 返回格式无效')
        return data

    def search(self, query, kind, game_version='', loader='', limit=20, offset=0):
        if kind not in KINDS:
            raise ValueError('不支持的内容类型')
        facets = [[f'project_type:{kind}']]
        if game_version:
            facets.append([f'versions:{game_version}'])
        if loader and kind in ('mod', 'modpack'):
            facets.append([f'categories:{loader.lower()}'])
        data = self._get('/search', {'query': query or '', 'limit': max(1, min(int(limit), 100)), 'offset': max(0, int(offset)),
                                     'facets': _json_param(facets), 'index': 'relevance'})
        return data.get('hits', []) if isinstance(data, dict) else []

    def versions(self, project_id, game_version='', loader='', kind='mod'):
        params = {}
        if game_version:
            params['game_versions'] = _json_param([game_version])
        if loader and kind in ('mod', 'modpack'):
            params['loaders'] = _json_param([loader.lower()])
        data = self._get('/project/' + str(project_id) + '/version', params)
        return data if isinstance(data, list) else []

    def project(self, project_id, kind='mod'):
        data = self._get('/project/' + str(project_id))
        if not isinstance(data, dict):
            raise ValueError('Modrinth 项目详情无效')
        license = data.get('license') or {}
        return dict(data, license_name=license.get('name') or license.get('id') or '未声明',
                    website_url='https://modrinth.com/' + kind + '/' + str(data.get('slug') or project_id))


class ContentCatalogue:
    SOURCES = ('自动', 'Modrinth', 'CurseForge')

    def __init__(self, cancel=None):
        self.cancel = cancel if cancel is not None else threading.Event()
        self.clients = {'Modrinth': ModrinthClient(self.cancel),
                        'CurseForge': CurseForgeContentClient(cancel=self.cancel)}
        self.warnings = []

    def search(self, query, kind, game_version='', loader='', source='自动', progress=None,
               offset=0, limit=20, page_info=False):
        if source not in self.SOURCES:
            raise ValueError('不支持的资源来源')
        names = list(self.clients) if source == '自动' else [source]
        self.warnings = []
        hits, successful, by_source, warnings, has_more = [], 0, {}, [], False
        # Catalogues contain different projects, not interchangeable file mirrors.
        with ThreadPoolExecutor(max_workers=len(names)) as pool:
            futures = {pool.submit(self.clients[name].search, query, kind, game_version, loader, limit, offset): name
                       for name in names}
            for future in as_completed(futures):
                name = futures[future]
                try:
                    records = future.result()
                    successful += 1
                    has_more = has_more or len(records) >= limit
                    by_source[name] = [dict(record, source=name) for record in records]
                    hits = [record for provider in names for record in by_source.get(provider, [])]
                except DownloadCancelled:
                    raise
                except (requests.RequestException, ValueError):
                    if source != '自动':
                        raise
                    warnings.append(name + ' 暂不可用')
                if progress is not None and hits:
                    progress(list(hits))
        if not successful:
            raise ValueError('资源来源暂不可用，请检查网络后重试。')
        self.warnings = warnings
        return {'hits': hits, 'has_more': has_more, 'warnings': warnings} if page_info else hits

    def versions(self, project, game_version='', loader='', kind='mod', offset=0, page_info=False):
        if not isinstance(project, dict) or project.get('source') not in self.clients:
            raise ValueError('请重新选择资源项目')
        name = project['source']
        options = {'offset': offset} if name == 'CurseForge' and offset else {}
        if page_info and name == 'CurseForge':
            options['page_info'] = True
        data = self.clients[name].versions(project['project_id'], game_version, loader, kind, **options)
        records = data.get('versions', []) if isinstance(data, dict) else data
        versions = [dict(version, source=name) for version in records]
        return dict(data, versions=versions) if isinstance(data, dict) else (
            {'versions': versions, 'has_more': False, 'next_offset': 0} if page_info else versions)

    def project(self, project, kind='mod'):
        if not isinstance(project, dict) or project.get('source') not in self.clients:
            raise ValueError('请重新选择资源项目')
        return self.clients[project['source']].project(project['project_id'], kind)


def _safe_file_name(name):
    if not isinstance(name, str) or not name or len(name) > 255 or Path(name).name != name:
        raise ValueError('远程文件名无效')
    if name in ('.', '..') or re.search(r'[<>:"/\\|?*\x00-\x1f]', name) or name.endswith((' ', '.')) \
            or re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', name):
        raise ValueError('远程文件名包含不安全字符')
    return name


def instance_environment(directory, identity):
    """Resolve an instance's inherited Minecraft version and loader libraries."""
    root = Path(directory).resolve() / 'versions'
    current, seen, loader = identity, set(), ''
    while current:
        _safe_file_name(current)
        if current in seen or len(seen) >= 32:
            raise ValueError('实例版本继承存在循环或层级过多')
        seen.add(current)
        metadata = json.loads((root / current / (current + '.json')).read_text(encoding='utf-8'))
        names = ' '.join(str(lib.get('name', '')).lower() for lib in metadata.get('libraries', [])
                         if isinstance(lib, dict))
        for marker, value in (('net.neoforged:', 'neoforge'), ('net.minecraftforge:', 'forge'),
                              ('net.fabricmc:fabric-loader:', 'fabric'), ('org.quiltmc:quilt-loader:', 'quilt')):
            if marker in names:
                loader = loader or value
        if not metadata.get('inheritsFrom'):
            return current, loader
        current = metadata['inheritsFrom']
    raise ValueError('实例缺少有效版本元数据')


def download_content(version, target_root, kind, cancel=None, status=None, progress=None):
    """Download one selected version, preserving its source and expected hashes."""
    if kind not in KINDS:
        raise ValueError('不支持的内容下载类型')
    cancel = cancel if cancel is not None else threading.Event()
    status = status or (lambda value: None)
    progress = progress or (lambda current, maximum: None)
    files = version.get('files') if isinstance(version, dict) else None
    if not isinstance(files, list) or not files:
        raise ValueError('项目版本没有可下载文件')
    destination = Path(target_root).resolve() / KINDS[kind]
    destination.mkdir(parents=True, exist_ok=True)
    # A version may also publish source/debug jars; install its primary artifact.
    primary = [item for item in files if isinstance(item, dict) and item.get('primary') is True]
    if len(primary) > 1 or not primary and len(files) != 1:
        raise ValueError('项目没有唯一主文件，无法确定应安装的文件')
    jobs = []
    for item in primary or files:
        if not isinstance(item, dict) or not item.get('url'):
            continue
        parsed = urlsplit(str(item['url']))
        if parsed.scheme != 'https' or parsed.username or parsed.password or not parsed.hostname:
            raise ValueError('资源来源返回了不安全的下载地址')
        name = _safe_file_name(item.get('filename') or Path(item['url']).name)
        hashes = item.get('hashes') or {}
        sha512 = hashes.get('sha512')
        sha1 = hashes.get('sha1')
        if not sha512 and not sha1:
            raise ValueError(f'文件缺少校验值：{name}')
        if sha512 and (not isinstance(sha512, str) or not re.fullmatch('[0-9a-fA-F]{128}', sha512)) \
                or sha1 and (not isinstance(sha1, str) or not re.fullmatch('[0-9a-fA-F]{40}', sha1)):
            raise ValueError(f'文件校验值格式无效：{name}')
        if type(item.get('size')) is not int or item['size'] <= 0:
            raise ValueError(f'文件大小无效：{name}')
        jobs.append((item['url'], destination / name, sha512, sha1, item.get('size')))
    if not jobs:
        raise ValueError('项目版本没有有效下载文件')
    progress(0, len(jobs))
    for index, (url, target, sha512, sha1, size) in enumerate(jobs, 1):
        if cancel.is_set():
            raise DownloadCancelled('内容下载已取消')
        status(f'正在下载 {target.name}')
        if not target.resolve().is_relative_to(Path(target_root).resolve()):
            raise ValueError('内容目录超出目标实例')
        temporary = target.with_name(target.name + '.buggcraft-part')
        session = None
        get = requests.get
        project_id, file_id = item.get('curseforge_project_id'), item.get('curseforge_file_id')
        if version.get('source') == 'CurseForge' and type(project_id) is int and type(file_id) is int:
            session = _DownloadSession(os.environ.get('BUGGCRAFT_CURSEFORGE_API_KEY', ''),
                                       {url: fallback_url(project_id, file_id)})
            get = session.get
        try:
            with get(url, stream=True, timeout=(8, 30),
                              headers={'User-Agent': 'Buggcraft/1.0'}) as response:
                response.raise_for_status()
                d512, d1, count = hashlib.sha512(), hashlib.sha1(), 0
                with temporary.open('wb') as output:
                    for chunk in response.iter_content(128 * 1024):
                        if cancel.is_set():
                            raise DownloadCancelled('内容下载已取消')
                        if chunk:
                            output.write(chunk); d512.update(chunk); d1.update(chunk); count += len(chunk)
                if (sha512 and d512.hexdigest().lower() != sha512.lower()) or (sha1 and d1.hexdigest().lower() != sha1.lower()):
                    raise ValueError(f'文件校验失败：{target.name}')
                if size is not None and count != int(size):
                    raise ValueError(f'文件长度不完整：{target.name}')
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
            if session is not None:
                session.close()
        progress(index, len(jobs))
    status('内容安装完成')
    return [str(path) for _, path, *_ in jobs]
