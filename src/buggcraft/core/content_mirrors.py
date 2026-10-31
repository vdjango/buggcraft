"""Publisher preferences and direct Modrinth metadata queries."""
from core.downloads import DownloadCancelled
from utils.http_identity import USER_AGENT
import requests


def configured_source(settings):
    source = settings.get_setting('settings.general.content_mirror', 'CurseForge')
    if source in ('自动', '自动测速'):
        return '自动（CurseForge 优先）'
    return source if source in ('自动（CurseForge 优先）', 'CurseForge', 'Modrinth', 'MCIM', 'Buggcraft', '官方') else 'CurseForge'


def display_source(source, provider=None):
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
