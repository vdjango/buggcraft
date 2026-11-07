"""Publisher preferences and direct Modrinth metadata queries."""
from core.downloads import DownloadCancelled
from utils.http_identity import USER_AGENT
import requests


CONTENT_SOURCES = ('CurseForge', 'Modrinth', 'Buggcraft')
AUTO_SOURCES = ('自动', '自动测速', '自动（CurseForge 优先）')
AUTO_ORDER = ('Buggcraft', 'CurseForge', 'Modrinth')


def source_order(source):
    """Return a complete priority list; MCIM requires an explicit entry."""
    if isinstance(source, str) and source in AUTO_SOURCES:
        return list(AUTO_ORDER)
    if isinstance(source, (list, tuple)):
        selected = [name for name in source if isinstance(name, str)
                    and name in (*CONTENT_SOURCES, 'MCIM')]
    elif source in (*CONTENT_SOURCES, 'MCIM'):
        selected = [source]
    else:
        selected = []
    return list(dict.fromkeys([*selected, *CONTENT_SOURCES]))


def configured_order(settings):
    mode = settings.get_setting('settings.general.content_mirror', '自动')
    if mode == '优先级':
        return source_order(settings.get_setting('settings.general.content_order', list(CONTENT_SOURCES)))
    return source_order(mode)


def configured_source(settings):
    source = settings.get_setting('settings.general.content_mirror', '自动')
    if source == '优先级':
        return configured_order(settings)
    if source == 'MCIM' or isinstance(source, (list, tuple)):
        return source_order(source)
    if source in AUTO_SOURCES:
        return '自动测速'
    return source if source in ('CurseForge', 'Modrinth', 'MCIM', 'Buggcraft', '官方') else '自动测速'


def display_source(source, provider=None):
    if isinstance(source, (list, tuple)):
        return ' → '.join(source_order(source))
    return provider if source == '官方' and provider in ('Modrinth', 'CurseForge') else source


def get_modrinth(path, params, cancel, source):
    if cancel.is_set():
        raise DownloadCancelled('内容查询已取消')
    endpoint = 'https://mod.mcimirror.top/modrinth/v2' if source == 'MCIM' else 'https://api.modrinth.com/v2'
    with requests.get(endpoint + path, params=params, timeout=(5, 15),
                      headers={'User-Agent': USER_AGENT}, allow_redirects=False) as response:
        response.raise_for_status()
        if response.status_code != 200:
            raise ValueError('Modrinth 返回状态无效')
        try:
            data = response.json()
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError('资源下载信息不完整或格式错误，请重试或更换下载源。') from exc
    if cancel.is_set():
        raise DownloadCancelled('内容查询已取消')
    if not isinstance(data, (dict, list)):
        raise ValueError('Modrinth 返回格式无效')
    return data
