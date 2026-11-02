"""Resolve publisher alternatives only when their file hashes and sizes match."""
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from urllib.parse import unquote, urlsplit

import requests

from core.downloads import DownloadCancelled
from utils.http_identity import USER_AGENT

logger = logging.getLogger(__name__)
_CACHE = {}
_CURSEFORGE_CACHE = {}
_UNAVAILABLE_HOSTS = {}
_LOCK = threading.Lock()
_CURSEFORGE_SLOTS = threading.BoundedSemaphore(3)
_DEADLINE = ContextVar('content_lookup_deadline', default=None)
_LOOKUP_ERRORS = ContextVar('content_lookup_errors', default=None)


def _lookup_error(reason):
    errors = _LOOKUP_ERRORS.get()
    if errors is not None and reason not in errors:
        errors.append(reason)


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
        from core.bugg_mirror import BASE_URL
        if parsed.hostname == urlsplit(BASE_URL).hostname:
            return 'Buggcraft'
    except ValueError:
        pass
    return ''


def _check(cancel):
    if cancel.is_set():
        raise DownloadCancelled('内容查询已取消')


def _get(url, cancel, params=None, headers=None):
    _check(cancel)
    host = urlsplit(url).hostname
    with _LOCK:
        if _UNAVAILABLE_HOSTS.get(host, 0) > time.monotonic():
            _lookup_error('查询服务暂时不可用')
            return {}
    deadline = _DEADLINE.get()
    remaining = deadline - time.monotonic() if deadline is not None else 8
    if remaining <= 0:
        _lookup_error('查询超时')
        return {}
    try:
        with requests.get(url, params=params,
                          headers={'User-Agent': USER_AGENT, 'Accept': 'application/json', **(headers or {})},
                          timeout=(min(3, remaining), min(8, remaining)), allow_redirects=False) as response:
            if response.status_code != 200:
                if response.status_code in (403, 408, 429, 500, 502, 503, 504):
                    _lookup_error('查询服务返回 HTTP ' + str(response.status_code))
                    if response.status_code in (403, 429):
                        with _LOCK:
                            _UNAVAILABLE_HOSTS[host] = time.monotonic() + 60
                return {}
            result = response.json()
        with _LOCK:
            _UNAVAILABLE_HOSTS.pop(host, None)
        _check(cancel)
        return result if isinstance(result, dict) else {}
    except (requests.RequestException, ValueError, OSError) as exc:
        _check(cancel)
        # A slow lookup is not evidence that every other file on this host is
        # unavailable. In particular, do not suppress a whole pack for a minute.
        _lookup_error('查询超时' if isinstance(exc, requests.Timeout) else '查询服务连接失败')
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


def prefetch_modrinth_hashes(jobs, cancel):
    """Resolve a pack's SHA-1 values in batches instead of one slow API call per file."""
    hashes = {str(sha1).lower(): size for sha1, size in jobs
              if re.fullmatch(r'[0-9a-fA-F]{40}', str(sha1)) and type(size) is int and size > 0}
    if not hashes:
        return
    now = time.monotonic()
    with _LOCK:
        pending = [digest for digest, size in hashes.items()
                   if (_CACHE.get((digest, '', size)) or (0,))[0] <= now]
    if not pending:
        return
    chunks = [pending[index:index + 100] for index in range(0, len(pending), 100)]

    def fetch(chunk):
        _check(cancel)
        versions = {}
        healthy = False
        try:
            with requests.post('https://api.modrinth.com/v2/version_files',
                               json={'hashes': chunk, 'algorithm': 'sha1'},
                               headers={'User-Agent': USER_AGENT, 'Accept': 'application/json'},
                               timeout=(3, 6)) as response:
                if response.status_code == 200:
                    versions = response.json()
                    healthy = isinstance(versions, dict)
        except (requests.RequestException, ValueError, OSError):
            pass
        _check(cancel)
        if not healthy:
            versions = {}
        ttl = 600 if healthy else 60
        with _LOCK:
            if not healthy:
                _UNAVAILABLE_HOSTS['api.modrinth.com'] = time.monotonic() + 60
            for digest in chunk:
                version = versions.get(digest) or {}
                file = next((item for item in version.get('files', [])
                             if isinstance(item, dict) and item.get('size') == hashes[digest]
                             and (item.get('hashes') or {}).get('sha1', '').lower() == digest
                             and provider(item.get('url', '')) == 'Modrinth'), {}) if isinstance(version, dict) else {}
                _CACHE[(digest, '', hashes[digest])] = (time.monotonic() + ttl, file, version, '')

    with ThreadPoolExecutor(max_workers=min(4, len(chunks))) as pool:
        list(pool.map(fetch, chunks))


_SEARCH_NOISE = {'forge', 'fabric', 'neoforge', 'quilt', 'minecraft', 'release',
                 'beta', 'alpha', 'client', 'jar', 'zip', 'mrpack', 'mc'}


def _search_words(value):
    value = re.sub(r'(?i)\.(?:jar|zip|mrpack)$', '', str(value))
    value = re.sub(r'([a-z])([A-Z])', r'\1 \2', value)
    return [word for word in re.findall(r'[A-Za-z]+', value)
            if word.lower() not in _SEARCH_NOISE and word.lower() != 'v']


def _singular(word):
    # Publisher names often omit the plural used in a local filename. Avoid
    # blindly truncating words such as Cataclysm, Glass or Nexus.
    if len(word) > 4 and word.lower().endswith('s') and not word.lower().endswith(('ss', 'us', 'is')):
        return word[:-1]
    return word


def _curseforge_search_terms(filename, title='', slug=''):
    words = _search_words(filename)
    significant = [word for word in words if len(word) >= 4]
    singular = [_singular(word) for word in significant]
    terms = [title, ' '.join(words), ' '.join(significant), ' '.join(singular)]
    # Keep meaningful combinations for long filenames, followed by distinctive
    # words. A lone initial such as L produces too many unrelated results.
    if len(significant) > 2:
        terms.extend(' '.join(singular[index:index + 2]) for index in range(len(singular) - 1))
    for word in sorted(dict.fromkeys(significant), key=lambda item: -len(item)):
        terms.extend((_singular(word), word))
    terms.append(slug)
    return list(dict.fromkeys(term.strip() for term in terms if term and len(term.strip()) >= 4))[:12]


def _curseforge(version, file, cancel):
    sha1 = str((file.get('hashes') or {}).get('sha1') or '')
    if not re.fullmatch('[0-9a-fA-F]{40}', sha1):
        return ''
    from core.curseforge import CLASSES, LOADERS, OFFICIAL_API, PUBLIC_API, download_url
    key = os.environ.get('BUGGCRAFT_CURSEFORGE_API_KEY', '')
    endpoint, headers = (OFFICIAL_API, {'x-api-key': key}) if key else (PUBLIC_API, {})
    filename = unquote(str(file.get('filename') or urlsplit(file.get('url', '')).path.rsplit('/', 1)[-1]))
    kind = file.get('kind', 'mod')
    project_id = version.get('project_id', '')
    # A descriptive filename is enough to search the chosen publisher. Do not
    # spend its lookup budget waiting for the other publisher's project API.
    project = (_get('https://api.modrinth.com/v2/project/' + project_id, cancel)
               if len([word for word in _search_words(filename) if len(word) >= 4]) < 2
               and re.fullmatch('[A-Za-z0-9]{8}', str(project_id)) else {})
    kind = project.get('project_type', kind)
    if kind == 'resourcepack' and 'shader' in (project.get('categories') or []):
        kind = 'shader'
    title = str(project.get('title') or '').split(':', 1)[0].strip()
    slug = project.get('slug')
    terms = _curseforge_search_terms(filename, title, slug if isinstance(slug, str) else '')
    normalize = lambda text: re.sub('[^a-z0-9]', '', str(text).lower())
    identities = {normalize(term) for term in terms}
    keywords = {_singular(word).lower() for text in (filename, title, slug or '')
                for word in _search_words(text) if len(word) >= 4}
    # Use compatibility metadata to find older files before paging the entire
    # project's latest releases. Still fall back to an unfiltered hash search.
    game_versions = re.findall(r'(?<!\d)1\.\d{1,2}(?:\.\d{1,2})?(?!\d)', filename)[:1]
    game_versions += sorted(version.get('game_versions') or [], key=len, reverse=True)
    filters = [{'gameVersion': value} for value in list(dict.fromkeys(game_versions))[:3]]
    loaders = version.get('loaders') or [value.lower() for value in
                re.findall(r'(?i)(neoforge|forge|fabric|quilt)', filename)]
    if len(loaders) == 1 and loaders[0] in LOADERS and filters:
        filters.insert(0, dict(filters[0], modLoaderType=LOADERS[loaders[0]]))
    filters.append({})
    seen = set()

    def matching_url(item, identifier):
        if (not isinstance(item, dict) or item.get('fileLength') != file.get('size')
                or item.get('modId', identifier) != identifier or item.get('isEarlyAccessContent')):
            return ''
        hashes = item.get('hashes') or []
        if not isinstance(hashes, list) or not any(isinstance(value, dict) and value.get('algo') == 1
                and str(value.get('value', '')).lower() == sha1.lower() for value in hashes):
            return ''
        try:
            url = download_url(item)
        except ValueError:
            return ''
        return url if provider(url) == 'CurseForge' else ''

    def search(term, compatibility=True):
        _check(cancel)
        if _DEADLINE.get() is not None and time.monotonic() >= _DEADLINE.get():
            _lookup_error('查询超时')
            return ''
        params = {'gameId': 432, 'classId': CLASSES.get(kind, 6), 'searchFilter': term,
                  'pageSize': 50, 'sortField': 6, 'sortOrder': 'desc'}
        if compatibility and filters[0]:
            params.update(filters[0])
        rows = _get(endpoint + '/mods/search', cancel,
                    params, headers).get('data') or []
        # Broad searches can put popular, unrelated projects ahead of the exact
        # title. Rank all returned metadata before spending requests on files.
        rows = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
        def relevance(row):
            labels = [row.get(field, '') for field in ('name', 'slug')]
            if any(normalize(label) in identities for label in labels):
                return 100
            words = {_singular(word).lower() for label in labels for word in _search_words(label)}
            return len(words & keywords)

        rows.sort(key=relevance, reverse=True)
        # Check cheap hashes already returned by search before fetching any
        # project history, even when the result is below the first three rows.
        for record in rows:
            identifier = record.get('id')
            if type(identifier) is int and identifier > 0 and record.get('gameId') == 432:
                for item in record.get('latestFiles', []) or []:
                    if url := matching_url(item, identifier):
                        return url
        candidates = [row for row in rows if relevance(row) or not (row.get('name') or row.get('slug'))]
        for record in candidates[:3]:
            identifier = record.get('id') if isinstance(record, dict) else None
            if (type(identifier) is not int or identifier <= 0 or record.get('gameId') != 432
                    or identifier in seen):
                continue
            seen.add(identifier)
            for query in filters:
                for offset in range(0, 200, 50):
                    _check(cancel)
                    if _DEADLINE.get() is not None and time.monotonic() >= _DEADLINE.get():
                        _lookup_error('查询超时')
                        return ''
                    rows = _get(endpoint + f'/mods/{identifier}/files', cancel,
                                {'pageSize': 50, 'index': offset, **query}, headers).get('data') or []
                    if not isinstance(rows, list):
                        break
                    for item in rows:
                        if url := matching_url(item, identifier):
                            return url
                    if len(rows) < 50:
                        break
        return ''

    # Searching CurseForge must work even when Modrinth metadata is unavailable.
    for term in terms:
        if url := search(term):
            return url
    # Compatibility tags can differ between publishers; they narrow the first
    # search, never replace the final byte hash as the authority.
    if filters[0]:
        for term in terms:
            if url := search(term, compatibility=False):
                return url
    return ''


def resolve_download_urls(addresses, sha1, size, *, sha512=None, preference='自动测速', cancel, report=None, kind='mod'):
    """Find identical public artifacts and order them by the selected source."""
    _check(cancel)
    addresses = list(dict.fromkeys(addresses))
    if preference == 'MCIM':
        return addresses  # An explicit MCIM choice keeps its existing URL policy.
    has_curseforge = any(provider(url) == 'CurseForge' for url in addresses)
    has_modrinth = any(provider(url) == 'Modrinth' for url in addresses)
    if (has_modrinth or has_curseforge or any(provider(url) == 'Buggcraft' for url in addresses)) \
            and (not has_modrinth or not has_curseforge) and type(size) is int and size > 0 and (
            re.fullmatch(r'[0-9a-fA-F]{40}', sha1 or '') or re.fullmatch(r'[0-9a-fA-F]{128}', sha512 or '')):
        key = (str(sha1 or '').lower(), str(sha512 or '').lower(), size)
        now = time.monotonic()
        with _LOCK:
            cached = _CACHE.get(key) or _CACHE.get((str(sha1 or '').lower(), '', size))
        if cached and sha512 and cached[1] and str((cached[1].get('hashes') or {}).get('sha512', '')).lower() != sha512.lower():
            cached = None
        if cached and cached[0] > now:
            _, file, version, curseforge_url = cached
        elif has_modrinth and not has_curseforge and re.fullmatch(r'[0-9a-fA-F]{40}', sha1 or ''):
            # The pack already contains a Modrinth URL. Resolve the preferred
            # CurseForge copy from its own search API instead of waiting for a
            # second lookup of the supplied URL's metadata first.
            file, version, curseforge_url = {}, {}, ''
        else:
            deadline = _DEADLINE.set(now + 8)
            try:
                file, version = _modrinth(sha1, sha512, size, cancel)
            finally:
                _DEADLINE.reset(deadline)
            curseforge_url = ''
        if not has_curseforge and not curseforge_url:
            # The pack already supplies the SHA-1 and size. Do not require a
            # successful Modrinth lookup just to search the chosen publisher.
            source_file = file or {'url': next((url for url in addresses if provider(url) == 'Modrinth'), addresses[0]),
                                   'hashes': {'sha1': sha1}, 'size': size}
            source_file = dict(source_file, kind=kind)
            cf_key = (str((source_file.get('hashes') or {}).get('sha1', '')).lower(), size, kind)
            with _LOCK:
                cf_cached = _CURSEFORGE_CACHE.get(cf_key)
            if cf_cached and cf_cached[0] > time.monotonic():
                _, curseforge_url, reason = cf_cached
            else:
                while not _CURSEFORGE_SLOTS.acquire(timeout=.1):
                    _check(cancel)
                errors = []
                deadline = _DEADLINE.set(time.monotonic() + 24)
                error_token = _LOOKUP_ERRORS.set(errors)
                try:
                    _check(cancel)
                    curseforge_url = _curseforge(version, source_file, cancel)
                finally:
                    _LOOKUP_ERRORS.reset(error_token)
                    _DEADLINE.reset(deadline)
                    _CURSEFORGE_SLOTS.release()
                reason = errors[0] if errors else '未找到与整合包哈希及大小一致的文件'
                with _LOCK:
                    _CURSEFORGE_CACHE[cf_key] = (time.monotonic() + (600 if curseforge_url else 15 if errors else 60),
                                                curseforge_url, reason)
            from core.content_mirrors import source_order
            if not curseforge_url and source_order(preference)[0] == 'CurseForge' and report:
                report('CurseForge ' + reason + '，按备用来源继续；仍会校验整合包哈希')
        if not cached or cached[0] <= now or curseforge_url != cached[3]:
            with _LOCK:
                _CACHE[key] = (time.monotonic() + 600, file, version, curseforge_url)
        discovered = ([file['url']] if file else []) + ([curseforge_url] if curseforge_url else [])
        addresses = list(dict.fromkeys([*addresses, *discovered]))
    from core.content_mirrors import source_order
    order = [*source_order(preference), '']
    return sorted(addresses, key=lambda url: order.index(provider(url)))
