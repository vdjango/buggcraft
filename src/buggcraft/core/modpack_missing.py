"""Collect unavailable mod downloads without relaxing integrity checks."""
from pathlib import PurePosixPath
import re
import threading

import requests

from core.downloads import MinecraftDownloader, DownloadSourcesExhausted


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


class PackResourceDownloader(MinecraftDownloader):
    def __init__(self, *args, allow_missing_mods=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.allow_missing_mods = allow_missing_mods
        self._missing_mods = {}
        self._missing_lock = threading.Lock()

    @property
    def missing_mods(self):
        with self._missing_lock:
            return [dict(self._missing_mods[path]) for path in sorted(self._missing_mods)]

    def fetch(self, url, relative, *args, **kwargs):
        try:
            return super().fetch(url, relative, *args, **kwargs)
        except Exception as exc:
            if not self.allow_missing_mods or self.cancel.is_set() or not unavailable_mod(relative, exc):
                raise
            with self._missing_lock:
                self._missing_mods[relative] = dict(path=relative, name=PurePosixPath(relative).name,
                    reason='模组可能未发布或已下架，下载源未提供这个文件。')
