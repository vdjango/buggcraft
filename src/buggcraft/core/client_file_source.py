"""Public cached-file lookup reused by room sync and pack repair, no login."""
import os
import json
import re
import ipaddress
from urllib.parse import urlsplit

import requests

_origin = os.environ.get('BUGGCRAFT_RESOURCE_ORIGIN', 'https://mirror.bugg.icu').rstrip('/')


def mapped_url(value):
    """Accept an exact public HTTPS route returned by our verified hash lookup."""
    try:
        url = urlsplit(value)
        host = url.hostname or ''
        if (not isinstance(value,str) or len(value)>2048 or url.scheme!='https'
                or '.' not in host or host.endswith(('.localhost','.local','.internal'))
                or url.username or url.password or url.port not in (None,443)
                or url.query or url.fragment or any(c in value for c in ('\\','\r','\n','\x00'))
                or any(part in ('.','..') for part in url.path.split('/'))):
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            return True
    except (TypeError,ValueError):
        return False


def set_origin(value):
    global _origin
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.path or parsed.query or parsed.fragment or parsed.port not in (None, 443)):
        raise ValueError('资源源站地址无效。')
    _origin = value


def lookup(files, cancel):
    """Reuse verified cached files or exact public hash mappings in one request."""
    if not _origin or cancel.is_set():
        return {}
    requested = {}
    for item in files:
        digest = item.get('hashes', {}).get('sha1', '')
        if re.fullmatch('[0-9a-f]{40}', digest):
            requested.setdefault(digest, []).append(item)
    if len(requested) > 3000:
        # Bound each manifest; duplicate paths with identical bytes share a
        # lookup, but must all receive the returned route.
        entries = [item for group in requested.values() for item in group]
        return {path:url for start in range(0,len(entries),3000)
                for path,url in lookup(entries[start:start+3000],cancel).items()}
    if not requested:
        return {}
    result = {}
    try:
        with requests.post(_origin + '/room-cache/resolve', json={'wanted': list(requested)},
                timeout=(2, 4), stream=True, allow_redirects=False,
                headers={'User-Agent': 'Buggcraft-PackRepair/1 (+https://bugg.icu)'}) as response:
            response.raise_for_status()
            raw = bytearray()
            for chunk in response.iter_content(65536):
                if cancel.is_set():
                    return {}
                raw.extend(chunk)
                if len(raw) > 2 * 1024 ** 2:
                    return {}
            data = json.loads(raw)
        if data.get('protocol') != 'room-content-cache-v1':
            return {}
        for file in data.get('files', []):
            originals = requested.get(file.get('sha1'), [])
            for original in originals:
                digest = file.get('sha256', '')
                if (original and file.get('action') == 'cached' and original.get('size') == file.get('size')
                        and re.fullmatch('[0-9a-f]{64}', digest)):
                    result[original['path']] = _origin + '/room-cache/files/' + digest
                elif original and file.get('action') == 'redirect' and original.get('size') == file.get('size'):
                    urls = file.get('downloads', [])
                    if isinstance(urls,list) and urls and mapped_url(urls[0]):
                        result[original['path']] = urls[0]
    except (requests.RequestException, ValueError, TypeError, AttributeError):
        return {}
    return result
