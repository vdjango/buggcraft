"""Find public, byte-identical mod downloads for compact pack export."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
import os
from pathlib import Path
import time
from urllib.parse import urljoin, urlsplit

import requests

from core.downloads import DownloadCancelled
from core.curseforge import OFFICIAL_API, PUBLIC_API
from utils.http_identity import USER_AGENT

logger = logging.getLogger(__name__)
_WHITE_SPACE = b'\x09\x0a\x0d\x20'
_CDN_HOSTS = {'cdn.modrinth.com', 'edge.forgecdn.net', 'mediafilez.forgecdn.net'}


def _check(cancel):
    if cancel is not None and cancel.is_set():
        raise DownloadCancelled('导出已取消')


def _fingerprint(path, cancel=None):
    """CurseForge MurmurHash2 (seed 1), omitting its four whitespace bytes."""
    path = Path(path)
    length = 0
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            _check(cancel)
            length += len(chunk.translate(None, _WHITE_SPACE))
    mask, multiplier = 0xffffffff, 0x5bd1e995
    value = (1 ^ length) & mask
    tail = b''
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            _check(cancel)
            data = tail + chunk.translate(None, _WHITE_SPACE)
            end = len(data) & ~3
            for offset in range(0, end, 4):
                part = int.from_bytes(data[offset:offset + 4], 'little')
                part = (part * multiplier) & mask
                part ^= part >> 24
                part = (part * multiplier) & mask
                value = ((value * multiplier) & mask) ^ part
            tail = data[end:]
    for index, byte in enumerate(tail):
        value ^= byte << (index * 8)
    if tail:
        value = (value * multiplier) & mask
    value ^= value >> 13
    value = (value * multiplier) & mask
    return (value ^ (value >> 15)) & mask


def _public_url(url):
    if (not isinstance(url, str) or len(url) > 8192
            or any(char.isspace() or ord(char) < 32 for char in url)):
        return False
    try:
        parsed = urlsplit(url)
        return (parsed.scheme == 'https' and parsed.hostname in _CDN_HOSTS
                and parsed.port in (None, 443) and not parsed.username and not parsed.password)
    except ValueError:
        return False


def _reachable(url, size, cancel=None):
    """Check that the publisher currently serves a byte range of the exact size."""
    for _ in range(4):
        _check(cancel)
        if not _public_url(url):
            return False
        with requests.get(url, headers={'User-Agent': USER_AGENT, 'Range': 'bytes=0-0',
                                        'Accept-Encoding': 'identity'}, stream=True,
                          allow_redirects=False, timeout=(4, 8)) as response:
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get('Location')
                if not location:
                    return False
                url = urljoin(url, location)
                continue
            if response.status_code == 206:
                valid = response.headers.get('Content-Range') == f'bytes 0-0/{size}'
            elif response.status_code == 200:
                valid = response.headers.get('Content-Length') == str(size)
            else:
                return False
            return valid and bool(next(response.iter_content(chunk_size=1), b''))
    return False


def _candidate(file, sha1, size):
    if not isinstance(file, dict) or file.get('size') != size:
        return ''
    hashes = file.get('hashes') or {}
    file_sha1 = hashes.get('sha1') if isinstance(hashes, dict) else None
    if not isinstance(file_sha1, str) or file_sha1.lower() != sha1:
        return ''
    url = file.get('url', '')
    return url if _public_url(url) else ''


def _modrinth_matches(mods, cancel, advance):
    matches = {}
    by_hash = {item['sha1']: item for item in mods}
    for start in range(0, len(by_hash), 100):
        _check(cancel)
        batch = list(by_hash)[start:start + 100]
        try:
            with requests.post('https://api.modrinth.com/v2/version_files',
                               json={'hashes': batch, 'algorithm': 'sha1'},
                               headers={'User-Agent': USER_AGENT}, timeout=(4, 12)) as response:
                response.raise_for_status()
                payload = response.json()
            if not isinstance(payload, dict):
                continue
            for sha1 in batch:
                version = payload.get(sha1)
                files = version.get('files', []) if isinstance(version, dict) else []
                for file in files if isinstance(files, list) else []:
                    url = _candidate(file, sha1, by_hash[sha1]['size'])
                    if url:
                        matches[sha1] = url
                        break
        except (requests.RequestException, ValueError) as exc:
            logger.info('Modrinth export lookup unavailable: %s', exc)
        finally:
            advance('正在查询 Modrinth', len(batch))
    return matches


def _curseforge_matches(mods, cancel, advance):
    matches = {}
    if not mods:
        return matches
    fingerprints = {}
    for item in mods:
        _check(cancel)
        fingerprints.setdefault(_fingerprint(item['source'], cancel), []).append(item)
        advance('正在计算 CurseForge 文件指纹')
    api_key = os.environ.get('BUGGCRAFT_CURSEFORGE_API_KEY', '')
    endpoint = (OFFICIAL_API if api_key else PUBLIC_API) + '/fingerprints/432'
    headers = {'User-Agent': USER_AGENT, 'Accept': 'application/json'}
    if api_key:
        headers['x-api-key'] = api_key
    for start in range(0, len(fingerprints), 100):
        _check(cancel)
        batch = list(fingerprints)[start:start + 100]
        try:
            with requests.post(endpoint, json={'fingerprints': batch}, headers=headers,
                               timeout=(4, 12)) as response:
                response.raise_for_status()
                payload = response.json()
            data = payload.get('data', {}) if isinstance(payload, dict) else {}
            rows = data.get('exactMatches', []) if isinstance(data, dict) else []
            for row in rows if isinstance(rows, list) else []:
                if not isinstance(row, dict):
                    continue
                file = row.get('file') or {}
                if (not isinstance(file, dict) or file.get('fileFingerprint') not in fingerprints
                        or file.get('isAvailable') is False or file.get('isEarlyAccessContent')
                        or file.get('isServerPack')):
                    continue
                hashes = file.get('hashes') or []
                if not isinstance(hashes, list):
                    continue
                url = file.get('downloadUrl', '')
                if not _public_url(url):
                    continue
                for item in fingerprints[file['fileFingerprint']]:
                    if file.get('fileLength') == item['size'] and any(
                            isinstance(value, dict) and value.get('algo') == 1
                            and str(value.get('value', '')).lower() == item['sha1'] for value in hashes):
                        matches[item['sha1']] = url
        except (requests.RequestException, ValueError) as exc:
            logger.info('CurseForge export lookup unavailable: %s', exc)
        finally:
            advance('正在查询 CurseForge', sum(len(fingerprints[value]) for value in batch))
    return matches


def find_public_mod_downloads(mods, cancel=None, progress=None):
    """Return downloadable URLs keyed by path; uncertain files stay embedded."""
    mods = list(mods)
    if not mods:
        return {}
    completed, total = 0, len(mods) * 4

    def advance(label, count=1):
        nonlocal completed
        _check(cancel)
        completed += count
        if progress:
            progress(f'{label}（{completed}/{total}）', completed, total)

    modrinth = _modrinth_matches(mods, cancel, advance)
    # Duplicate files share a Modrinth hash query.
    advance('Modrinth 查询完成', len(mods) - len({item['sha1'] for item in mods}))
    curseforge = _curseforge_matches(mods, cancel, advance)
    candidates = {}
    for item in mods:
        urls = [url for url in (modrinth.get(item['sha1']), curseforge.get(item['sha1'])) if url]
        if urls:
            candidates[item['path']] = (item, urls)
    found = {}
    advance('未匹配的模组将随包保留', len(mods) - len(candidates))
    if not candidates:
        return found

    def probe(item, urls):
        for url in urls:
            for attempt in range(3):
                _check(cancel)
                try:
                    if _reachable(url, item['size'], cancel):
                        return url
                    break
                except requests.RequestException as exc:
                    logger.info('Mod download probe unavailable (%s/3): %s', attempt + 1, exc)
                    if attempt < 2:
                        if cancel is not None:
                            if cancel.wait(.4 * (attempt + 1)):
                                _check(cancel)
                        else:
                            time.sleep(.4 * (attempt + 1))
        return ''

    with ThreadPoolExecutor(max_workers=min(8, len(candidates)), thread_name_prefix='pack-mod-probe') as pool:
        futures = {pool.submit(probe, item, urls): path for path, (item, urls) in candidates.items()}
        for future in as_completed(futures):
            _check(cancel)
            url = future.result()
            if url:
                item = candidates[futures[future]][0]
                found[item['path']] = {'sha1': item['sha1'], 'size': item['size'], 'downloads': [url]}
            advance('正在检查模组下载地址')
    return found
