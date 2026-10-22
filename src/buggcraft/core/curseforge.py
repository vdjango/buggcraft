"""CurseForge metadata through the public gateway, or a user's own API key."""
import os
import re
import threading
from urllib.parse import urlsplit

import requests

from core.downloads import DownloadCancelled


OFFICIAL_API = 'https://api.curseforge.com/v1'
PUBLIC_API = 'https://download.bugg.icu/api/curseforge/v1'
CLASSES = {'mod': 6, 'resourcepack': 12, 'shader': 6552, 'modpack': 4471}
LOADERS = {'forge': 1, 'fabric': 4, 'quilt': 5, 'neoforge': 6}
ROUTE = re.compile(r'/mods(?:/search|/files|/[1-9][0-9]*(?:/files(?:/[1-9][0-9]*)?)?)?')


class CurseForgeAPI:
    def __init__(self, api_key=None, cancel=None):
        self.api_key = api_key or os.environ.get('BUGGCRAFT_CURSEFORGE_API_KEY', '')
        self.cancel = cancel if cancel is not None else threading.Event()

    def request(self, method, route, params=None, body=None):
        if not ROUTE.fullmatch(route):
            raise ValueError('不支持的 CurseForge 接口')
        if self.cancel.is_set():
            raise DownloadCancelled('内容查询已取消')
        endpoint = OFFICIAL_API if self.api_key else PUBLIC_API
        headers = {'User-Agent': 'Buggcraft/1.0', 'Accept': 'application/json'}
        if self.api_key:
            headers['x-api-key'] = self.api_key
        call = requests.get if method == 'GET' else requests.post
        options = {'params': params} if method == 'GET' else {'json': body}
        try:
            # Metadata redirects are not needed; never forward a private key.
            with call(endpoint + route, headers=headers, timeout=(8, 30),
                      allow_redirects=False, **options) as response:
                if response.status_code in (401, 403):
                    raise ValueError('CurseForge 下载授权无效或暂不可用，请检查个人密钥或稍后重试。')
                if response.status_code == 429:
                    raise ValueError('CurseForge 请求过于频繁，请稍后重试。')
                if response.status_code != 200:
                    raise ValueError('CurseForge 资源服务暂不可用，请稍后重试或切换 Modrinth。')
                payload = response.json()
        except requests.RequestException:
            raise ValueError('无法连接 CurseForge 资源服务，请检查网络或切换 Modrinth。') from None
        if self.cancel.is_set():
            raise DownloadCancelled('内容查询已取消')
        if not isinstance(payload, dict) or not isinstance(payload.get('data'), (dict, list)):
            raise ValueError('CurseForge 返回格式无效')
        return payload['data']

    def get(self, route, params=None):
        return self.request('GET', route, params=params)

    def post(self, route, body):
        data = self.request('POST', route, body=body)
        if not isinstance(data, list):
            raise ValueError('CurseForge 返回的文件清单无效')
        return data


def content_file(item):
    """Convert an authorized file to the launcher's verified download format."""
    if item.get('isAvailable') is False or item.get('isServerPack') or item.get('isEarlyAccessContent'):
        raise ValueError('此 CurseForge 文件不支持自动下载')
    url = item.get('downloadUrl')
    parsed = urlsplit(url or '')
    if (parsed.scheme != 'https' or parsed.username or parsed.password or
            not (parsed.hostname or '').endswith('.forgecdn.net') or parsed.port not in (None, 443)):
        raise ValueError('作者未开放自动下载，或 CurseForge 文件下载地址不可用。请到项目页面下载。')
    hashes = item.get('hashes') or []
    if not isinstance(hashes, list):
        raise ValueError('CurseForge 文件校验信息无效')
    sha1 = next((entry.get('value') for entry in hashes
                 if isinstance(entry, dict) and entry.get('algo') == 1), '')
    if not isinstance(sha1, str) or not re.fullmatch('[0-9a-fA-F]{40}', sha1):
        raise ValueError('CurseForge 文件缺少有效 SHA-1，不能自动安装')
    if type(item.get('fileLength')) is not int or item['fileLength'] <= 0:
        raise ValueError('CurseForge 文件大小无效')
    project_id, file_id = item.get('modId'), item.get('id')
    if type(project_id) is not int or type(file_id) is not int or min(project_id, file_id) <= 0:
        raise ValueError('CurseForge 文件标识无效')
    return {'url': url, 'filename': item.get('fileName'), 'size': item['fileLength'],
            'hashes': {'sha1': sha1.lower()}, 'primary': True,
            'curseforge_project_id': project_id, 'curseforge_file_id': file_id}


def fallback_url(project_id, file_id):
    return PUBLIC_API + f'/download/{int(project_id)}/{int(file_id)}'


class CurseForgeContentClient(CurseForgeAPI):
    def search(self, query, kind, game_version='', loader='', limit=20):
        if kind not in CLASSES:
            raise ValueError('不支持的内容类型')
        params = {'gameId': 432, 'classId': CLASSES[kind], 'searchFilter': query or '',
                  'pageSize': max(1, min(int(limit), 50)), 'sortField': 2, 'sortOrder': 'desc'}
        if game_version:
            params['gameVersion'] = game_version
        if loader and game_version and kind in ('mod', 'modpack'):
            if loader.lower() not in LOADERS:
                return []
            params['modLoaderType'] = LOADERS[loader.lower()]
        data = self.get('/mods/search', params)
        if not isinstance(data, list):
            raise ValueError('CurseForge 返回的项目列表无效')
        return [{'project_id': str(item['id']), 'title': item.get('name', ''),
                 'description': item.get('summary', ''), 'source': 'CurseForge'}
                for item in data if isinstance(item, dict) and type(item.get('id')) is int
                and item.get('gameId') == 432 and item.get('classId') == CLASSES[kind]]

    def versions(self, project_id, game_version='', loader='', kind='mod'):
        if kind not in CLASSES or not re.fullmatch('[1-9][0-9]*', str(project_id)):
            raise ValueError('CurseForge 项目信息无效')
        project = self.get('/mods/' + str(project_id))
        if (not isinstance(project, dict) or project.get('id') != int(project_id) or
                project.get('gameId') != 432 or project.get('classId') != CLASSES[kind]):
            raise ValueError('CurseForge 项目与所选内容类型不符')
        if project.get('allowModDistribution') is False:
            raise ValueError('作者未开放第三方自动下载，请到 CurseForge 项目页面下载。')
        params = {'pageSize': 50}
        if game_version:
            params['gameVersion'] = game_version
        if loader and kind in ('mod', 'modpack'):
            if loader.lower() not in LOADERS:
                return []
            params['modLoaderType'] = LOADERS[loader.lower()]
        data = self.get('/mods/' + str(project_id) + '/files', params)
        if not isinstance(data, list):
            raise ValueError('CurseForge 返回的文件列表无效')
        versions = []
        for item in data:
            if not isinstance(item, dict) or item.get('modId') != int(project_id):
                continue
            tags = item.get('gameVersions') or []
            if game_version and game_version not in tags:
                continue
            if loader and kind in ('mod', 'modpack') and loader.casefold() not in {str(t).casefold() for t in tags}:
                continue
            try:
                file = content_file(item)
            except ValueError:
                continue
            versions.append({'id': str(item['id']), 'project_id': str(project_id),
                             'name': item.get('displayName') or item.get('fileName'),
                             'date_published': item.get('fileDate', ''), 'source': 'CurseForge',
                             'files': [file]})
        return versions
