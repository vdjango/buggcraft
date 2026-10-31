"""Resolve publisher alternatives only when their file hashes and sizes match."""
import logging
import os
import re
import threading
import time
from contextvars import ContextVar
from urllib.parse import urlsplit

import requests

from core.downloads import DownloadCancelled
from utils.http_identity import USER_AGENT

logger = logging.getLogger(__name__)
_CACHE = {}
_LOCK = threading.Lock()
_DEADLINE = ContextVar('content_lookup_deadline', default=None)


def provider(url):
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or parsed.port not in (None, 443)
                or parsed.username or parsed.password):
            return ''
        if parsed.hostname == 'cdn.modrinth.com':
            return 'Modrinth'
        if parsed.hostname in ('edge.forgecdn.net', 'mediafilez.forgecdn.net'):
            return 'CurseForge'
    except ValueError:
        pass
    return ''


def _check(cancel):
    if cancel.is_set():
        raise DownloadCancelled('内容查询已取消')


def _get(url, cancel, params=None, headers=None):
    _check(cancel)
    deadline = _DEADLINE.get()
    remaining = deadline - time.monotonic() if deadline is not None else 8
    if remaining <= 0:
        return {}
    try:
        with requests.get(url, params=params,
                          headers={'User-Agent': USER_AGENT, 'Accept': 'application/json', **(headers or {})},
                          timeout=(min(3, remaining), min(5, remaining)), allow_redirects=False) as response:
            if response.status_code != 200:
                return {}
            result = response.json()
        _check(cancel)
        return result if isinstance(result, dict) else {}
    except (requests.RequestException, ValueError, OSError):
        _check(cancel)
        logger.info('content_alternative_unavailable host=%s', urlsplit(url).hostname)
        return {}


def _modrinth(sha1, sha512, size, cancel):
    algorithm, digest = ('sha1', sha1) if sha1 else ('sha512', sha512)
    version = _get('https://api.modrinth.com/v2/version_file/' + digest,
                   cancel, {'algorithm': algorithm})
    for file in version.get('files', []) or []:
        if not isinstance(file, dict) or file.get('size') != size:
            continue
        hashes = file.get('hashes') or {}
        if not isinstance(hashes, dict) or any(
                expected and str(hashes.get(key, '')).lower() != expected
                for key, expected in (('sha1', sha1), ('sha512', sha512))):
            continue
        if provider(file.get('url', '')) == 'Modrinth':
            return file, version
    return {}, {}


def _curseforge(version, file, cancel):
    project_id = version.get('project_id', '')
    sha1 = (file.get('hashes') or {}).get('sha1', '')
    if not re.fullmatch('[A-Za-z0-9]{8}', str(project_id)) or not re.fullmatch('[0-9a-fA-F]{40}', sha1):
        return ''
    project = _get('https://api.modrinth.com/v2/project/' + project_id, cancel)
    slug = project.get('slug')
    if not isinstance(slug, str) or not slug:
        return ''
    from core.curseforge import CLASSES, OFFICIAL_API, PUBLIC_API, download_url
    key = os.environ.get('BUGGCRAFT_CURSEFORGE_API_KEY', '')
    endpoint, headers = (OFFICIAL_API, {'x-api-key': key}) if key else (PUBLIC_API, {})
    kind = project.get('project_type', 'mod')
    if kind == 'resourcepack' and 'shader' in (project.get('categories') or []):
        kind = 'shader'
    params = {'gameId': 432, 'classId': CLASSES.get(kind, 6),
              'searchFilter': slug, 'pageSize': 3, 'sortField': 6, 'sortOrder': 'desc'}
    projects = _get(endpoint + '/mods/search', cancel, params, headers).get('data') or []
    if not isinstance(projects, list):
        return ''
    for record in projects[:3]:
        identifier = record.get('id') if isinstance(record, dict) else None
        if type(identifier) is not int or identifier <= 0 or record.get('gameId') != 432:
            continue
        params = {'pageSize': 50}
        games = version.get('game_versions') or []
        if games and isinstance(games[-1], str):
            params['gameVersion'] = games[-1]
        for offset in (0, 50):
            _check(cancel)
            rows = _get(endpoint + f'/mods/{identifier}/files', cancel,
                        {**params, 'index': offset}, headers).get('data') or []
            if not isinstance(rows, list):
                break
            for item in rows:
                if (not isinstance(item, dict) or item.get('fileLength') != file.get('size')
                        or item.get('isAvailable') is False or item.get('isEarlyAccessContent')):
                    continue
                hashes = item.get('hashes') or []
                if not any(isinstance(value, dict) and value.get('algo') == 1
                           and str(value.get('value', '')).lower() == sha1.lower() for value in hashes):
                    continue
                try:
                    url = download_url(item)
                except ValueError:
                    continue
                if provider(url) == 'CurseForge':
                    return url
            if len(rows) < 50:
                break
    return ''


def resolve_download_urls(addresses, sha1, size, *, sha512=None, preference='自动测速', cancel):
    """Honor the selected publisher. Only our source can follow it."""
    _check(cancel)
    addresses = list(dict.fromkeys(addresses))
    if preference in ('自动', '自动测速', '自动（CurseForge 优先）'):
        preference = 'CurseForge'
    if preference in ('CurseForge', 'Modrinth'):
        selected = [url for url in addresses if provider(url) in (preference, '')]
        if preference == 'Modrinth' and not any(provider(url) == 'Modrinth' for url in selected) and (sha1 or sha512):
            # Only an explicit Modrinth choice may query its hash index.
            file, _version = _modrinth(sha1, sha512, size, cancel)
            if file:
                selected.insert(0, file['url'])
        return selected
    return addresses
