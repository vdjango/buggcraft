"""MCIM metadata routing, cache freshness and upstream fallback."""
from datetime import datetime, timezone
import logging

import requests

from core.downloads import DownloadCancelled, CONTENT_MIRROR
from utils.http_identity import USER_AGENT

logger = logging.getLogger(__name__)


def configured_source(settings):
    source = settings.get_setting('settings.general.content_mirror', 'Modrinth')
    # Restore automatic routing for older publisher-first preferences.
    return source if source in ('自动测速', 'CurseForge', 'Modrinth', 'MCIM', '官方') else '自动测速'


def display_source(source, provider=None):
    """Name the actual publisher when the official route is selected."""
    return provider if source == '官方' and provider in ('Modrinth', 'CurseForge') else source


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
    official = 'https://api.modrinth.com/v2'
    mirror_endpoint = CONTENT_MIRROR + '/modrinth/v2'
    endpoints = [official] if source in ('官方', 'CurseForge', 'Modrinth') else [mirror_endpoint, official]
    cached = None
    last_error = None
    for index, endpoint in enumerate(endpoints):
        if cancel.is_set():
            raise DownloadCancelled('内容查询已取消')
        mirror = endpoint.startswith(CONTENT_MIRROR)
        try:
            with requests.get(endpoint + path, params=params, timeout=(5, 15),
                              headers={'User-Agent': USER_AGENT}, allow_redirects=False) as response:
                response.raise_for_status()
                if response.status_code != 200:
                    raise ValueError('Modrinth 返回状态无效')
                try:
                    data = response.json()
                except (ValueError, UnicodeDecodeError) as exc:
                    raise ValueError('资源下载信息不完整或格式错误，请重试或更换下载源。') from exc
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
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            if cancel.is_set():
                raise DownloadCancelled('内容查询已取消') from None
            if not mirror:
                if cached is not None:
                    logger.warning('Modrinth upstream unavailable; using cached MCIM metadata')
                    return cached
                if index + 1 < len(endpoints):
                    logger.warning('Modrinth upstream unavailable; trying MCIM metadata')
                    continue
                raise
            logger.warning('MCIM metadata unavailable; falling back to Modrinth', exc_info=True)
    if cached is not None:
        return cached
    if last_error is not None:
        raise last_error
    raise ValueError('Modrinth 下载信息暂不可用')
