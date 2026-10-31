"""Collect unavailable mod downloads without relaxing integrity checks."""
from pathlib import PurePosixPath
from pathlib import Path
import hashlib
import os
import re
import tempfile
import threading
from urllib.parse import urlsplit

import requests

from core.downloads import MinecraftDownloader, DownloadSourcesExhausted, download_error_message
from utils.download_locks import download_lock


def unavailable_mod(path, error):
    """Only a missing remote JAR qualifies; network/disk/hash errors still fail."""
    relative = PurePosixPath(path)
    if not relative.parts or relative.parts[0].casefold() != 'mods' or relative.suffix.casefold() != '.jar':
        return False
    if isinstance(error, DownloadSourcesExhausted):
        return bool(error.source_errors) and all(unavailable_mod(path, item) for item in error.source_errors)
    current, seen = error, set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, requests.HTTPError) and current.response is not None:
            if current.response.status_code in (404, 410):
                return True
        current = current.__cause__ or current.__context__
    # The downloader includes the final source error in its terminal exception.
    return bool(re.search(r'\b(?:404|410)\s+(?:Client Error|Gone|Not Found)\b', str(error), re.IGNORECASE))


def recoverable_mod_download(path, error):
    """Only remote mod transfers can wait for repair; local/integrity errors fail."""
    relative = PurePosixPath(path)
    if not relative.parts or relative.parts[0].casefold() != 'mods' or relative.suffix.casefold() != '.jar':
        return False
    if isinstance(error, DownloadSourcesExhausted):
        return bool(error.source_errors) and all(recoverable_mod_download(path, item) for item in error.source_errors)
    return isinstance(error, requests.RequestException) or unavailable_mod(path, error)


def missing_mods_text(mods, instance=''):
    lines = ['缺失模组清单' + (' · ' + instance if instance else ''),
             '请下载清单指定版本，并放入此实例的 mods 文件夹。',
             '缺少必需模组可能无法启动；联机时请按房主实际使用情况补齐。', '']
    for item in mods:
        lines.extend([item.get('name', ''), '位置：' + item.get('path', 'mods/'),
                      '原因：' + item.get('reason', '暂时无法下载')])
        if item.get('pageUrl'):
            lines.append('下载页：' + item['pageUrl'])
        for url in item.get('downloads', []):
            lines.append('下载地址：' + url)
        for algorithm, digest in (item.get('hashes') or {}).items():
            if digest:
                lines.append(algorithm.upper() + '：' + digest)
        lines.append('')
    return '\n'.join(lines)


class PackResourceDownloader(MinecraftDownloader):
    def __init__(self, *args, allow_missing_mods=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.allow_missing_mods = allow_missing_mods
        self._missing_mods = {}
        self._missing_jobs = {}
        self._missing_lock = threading.Lock()
        self.required_hashes = {}

    @property
    def missing_mods(self):
        with self._missing_lock:
            return [dict(self._missing_mods[path]) for path in sorted(self._missing_mods)]

    def fetch(self, url, relative, *args, **kwargs):
        try:
            result = super().fetch(url, relative, *args, **kwargs)
        except Exception as exc:
            if not self.allow_missing_mods or self.cancel.is_set() or not recoverable_mod_download(relative, exc):
                raise
            sha1 = kwargs.get('sha1', args[0] if args else None)
            size = kwargs.get('size', args[1] if len(args) > 1 else None)
            hashes = dict(self.required_hashes.get(relative, {}))
            if sha1:
                hashes['sha1'] = sha1
            if kwargs.get('sha512'):
                hashes['sha512'] = kwargs['sha512']
            urls = [url, *getattr(self, 'file_mirrors', {}).get(url, [])]
            parsed = urlsplit(url)
            parts = parsed.path.split('/')
            page = (f'https://modrinth.com/mod/{parts[2]}/version/{parts[4]}'
                    if parsed.hostname == 'cdn.modrinth.com' and len(parts) >= 6
                    and parts[1] == 'data' and parts[3] == 'versions' else '')
            with self._missing_lock:
                self._missing_mods[relative] = dict(path=relative, name=PurePosixPath(relative).name,
                    reason=('下载源暂未提供这个文件，请手动下载或向整合包作者索要。'
                            if unavailable_mod(relative, exc) else download_error_message(exc)),
                    downloads=urls, pageUrl=page, hashes=hashes, size=size, canSupply=bool(hashes))
                self._missing_jobs[relative] = (url, relative, args, kwargs)
            self._file_event(relative, 'waiting', error='等待重试或手动补齐')
            return None
        with self._missing_lock:
            self._missing_mods.pop(relative, None)
            self._missing_jobs.pop(relative, None)
        return result

    def retry_missing(self):
        with self._missing_lock:
            jobs = list(self._missing_jobs.values())
        # Only retry failed files. fetch() retains the regular checkpoint and
        # transport retry behavior and removes successful entries from the list.
        for url, relative, args, kwargs in jobs:
            self.check_cancelled()
            self.fetch(url, relative, *args, **kwargs)

    def repair_from_origin(self):
        from core.client_file_source import lookup
        urls = lookup(self.missing_mods, self.cancel)
        for relative, url in urls.items():
            with self._missing_lock:
                job = self._missing_jobs.get(relative)
            if job:
                self.check_cancelled()
                self.status('正在从源站补齐：' + PurePosixPath(relative).name)
                _, relative, args, kwargs = job
                self.fetch(url, relative, *args, **kwargs)

    def supply_mod(self, relative, filename):
        with self._missing_lock:
            item = dict(self._missing_mods.get(relative) or {})
        if not item or not item.get('hashes'):
            return False
        temporary = None
        try:
            source = Path(filename)
            target = self.inside(relative)
            if not source.is_file() or source.stat().st_size != item['size']:
                raise ValueError('所选文件与整合包要求的版本不同，请重新选择。')
            self.status('正在校验手动补齐的模组：' + item['name'])
            digests = {name: hashlib.new(name) for name, value in item['hashes'].items() if value}
            with download_lock(target, self.cancel):
                target.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.manual-mod-', delete=False) as output:
                    temporary = Path(output.name)
                    with source.open('rb') as stream:
                        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                            self.check_cancelled()
                            for digest in digests.values():
                                digest.update(chunk)
                            output.write(chunk)
                if temporary.stat().st_size != item['size'] or any(
                        digest.hexdigest().lower() != item['hashes'][name].lower()
                        for name, digest in digests.items()):
                    raise ValueError('所选文件校验不匹配，请下载清单指定的版本后重新选择。')
                self.check_cancelled()
                os.replace(temporary, target)
                partial = target.with_name(target.name + '.buggcraft-part')
                partial.unlink(missing_ok=True)
                partial.with_name(partial.name + '.json').unlink(missing_ok=True)
                with self._missing_lock:
                    self._missing_mods.pop(relative, None)
                    self._missing_jobs.pop(relative, None)
                self._file_event(relative, 'verified', done=item['size'], total=item['size'], error='')
                self.status('手动补齐完成：' + item['name'])
                return True
        except (ValueError, FileNotFoundError) as exc:
            with self._missing_lock:
                if relative in self._missing_mods:
                    self._missing_mods[relative]['reason'] = str(exc)
            return False
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
