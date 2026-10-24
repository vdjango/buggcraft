"""MCIM metadata routing, cache freshness and upstream fallback."""
from datetime import datetime, timezone
import logging

import requests

from core.downloads import DownloadCancelled, CONTENT_MIRROR
from utils.http_identity import USER_AGENT

logger = logging.getLogger(__name__)


def configured_source(settings):
    return settings.get_setting('settings.general.content_mirror', 'MCIM')


def cached_dates(payload):
    """Use the most recent upstream check, inspecting nested cache records."""
    if isinstance(payload, list):
        for item in payload:
            yield from cached_dates(item)
    elif isinstance(payload, dict):
        value = payload.get('checked_at') or payload.get('sync_at')
        if isinstance(value, str):
            try:
                date = datetime.fromisoformat(value.replace('Z', '+00:00'))
                if date.tzinfo:
                    yield date
            except ValueError:
                pass
        for key, value in payload.items():
            if isinstance(value, (list, dict)):
                yield from cached_dates(value)


def get_modrinth(path, params, cancel, source):
    endpoints = ([CONTENT_MIRROR + '/modrinth/v2'] if source == 'MCIM' else []) + ['https://api.modrinth.com/v2']
    cached = None
    for endpoint in endpoints:
        if cancel.is_set():
            raise DownloadCancelled('内容查询已取消')
        mirror = endpoint.startswith(CONTENT_MIRROR)
        try:
            with requests.get(endpoint + path, params=params, timeout=(5, 15),
                              headers={'User-Agent': USER_AGENT}, allow_redirects=False) as response:
                response.raise_for_status()
                if response.status_code != 200:
                    raise ValueError('Modrinth 返回状态无效')
                data = response.json()
            if not isinstance(data, (dict, list)):
                raise ValueError('Modrinth 返回格式无效')
            dates = list(cached_dates(data)) if mirror else []
            logger.info('content_metadata provider=Modrinth mirror=%s cache_dates=%s', mirror,
                        [date.isoformat() for date in dates[:5]])
            if mirror and (not dates or (datetime.now(timezone.utc) - min(dates)).total_seconds() > 86400):
                cached = data
                continue
            if cancel.is_set():
                raise DownloadCancelled('内容查询已取消')
            return data
        except (requests.RequestException, ValueError):
            if cancel.is_set():
                raise DownloadCancelled('内容查询已取消') from None
            if not mirror:
                if cached is not None:
                    logger.warning('Modrinth upstream unavailable; using cached MCIM metadata')
                    return cached
                raise
            logger.warning('MCIM metadata unavailable; falling back to Modrinth', exc_info=True)
    return cached
