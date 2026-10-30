"""Game/loader mirrors with reversible, documented upstream routes."""
from urllib.parse import urlsplit

BMCLAPI = 'https://bmclapi2.bangbang93.com'
MCMIRROR = 'https://mirror.minguncle.cn'

_GAME = {'piston-meta.mojang.com': '', 'launchermeta.mojang.com': '',
         'piston-data.mojang.com': '', 'launcher.mojang.com': '',
         'resources.download.minecraft.net': '/assets', 'libraries.minecraft.net': '/maven'}
_LOADER = {'maven.minecraftforge.net', 'files.minecraftforge.net', 'maven.fabricmc.net',
           'maven.neoforged.net', 'maven.quiltmc.org'}


def publisher_url(url):
    parsed = urlsplit(url)
    if parsed.hostname not in ('mirror.minguncle.cn', 'bmclapi2.bangbang93.com'):
        return url
    path = parsed.path
    if parsed.hostname == 'bmclapi2.bangbang93.com' and path.startswith('/maven/'):
        relative = path[len('/maven'):]
        for group, host, prefix in (('/net/minecraftforge/', 'maven.minecraftforge.net', ''),
                                     ('/net/neoforged/', 'maven.neoforged.net', '/releases'),
                                     ('/net/fabricmc/', 'maven.fabricmc.net', ''),
                                     ('/org/quiltmc/', 'maven.quiltmc.org', '/repository/release')):
            if relative.startswith(group):
                return parsed._replace(netloc=host, path=prefix + relative).geturl()
    for prefix, host in (('/assets/', 'resources.download.minecraft.net'),
                         ('/maven/', 'libraries.minecraft.net'),
                         ('/fabric-meta/', 'meta.fabricmc.net'),
                         ('/quilt-meta/', 'meta.quiltmc.org')):
        if path.startswith(prefix):
            return parsed._replace(netloc=host, path='/' + path[len(prefix):]).geturl()
    for alias, host in (('piston-meta', 'piston-meta.mojang.com'), ('launchermeta', 'launchermeta.mojang.com'),
                        ('piston-data', 'piston-data.mojang.com'), ('launcher', 'launcher.mojang.com'),
                        ('resources.download.minecraft.net', 'resources.download.minecraft.net')):
        prefix = '/' + alias + '/'
        if path.startswith(prefix):
            return parsed._replace(netloc=host, path='/' + path[len(prefix):]).geturl()
    for host in _LOADER | {'piston-meta.mojang.com', 'piston-data.mojang.com',
                           'launchermeta.mojang.com', 'launcher.mojang.com'}:
        prefix = '/' + host + '/'
        if path.startswith(prefix):
            return parsed._replace(netloc=host, path='/' + path[len(prefix):]).geturl()
    host = ('piston-data.mojang.com' if path.startswith('/v1/objects/') else
            'piston-meta.mojang.com' if path.startswith(('/v1/packages/', '/mc/game/')) else '')
    return parsed._replace(netloc=host).geturl() if host else url


def mirror_url(url, mirror):
    parsed = urlsplit(publisher_url(url))
    if parsed.scheme != 'https' or parsed.port not in (None, 443) or parsed.username or parsed.password:
        return None
    host, path = parsed.hostname, parsed.path
    if host in _GAME:
        path = _GAME[host] + path
        if mirror == MCMIRROR and host in ('piston-meta.mojang.com', 'launchermeta.mojang.com') and '/mc/game/version_manifest' in path:
            path = '/mc/game/version_manifest.json'
    elif host in ('meta.fabricmc.net', 'meta.quiltmc.org'):
        if mirror == MCMIRROR and host == 'meta.quiltmc.org':
            return None  # Not advertised by this mirror.
        path = ('/fabric-meta' if host == 'meta.fabricmc.net' else '/quilt-meta') + path
    elif host in _LOADER:
        if mirror == MCMIRROR:
            if host == 'maven.quiltmc.org':
                return None
            path = '/' + host + path
        else:
            path = '/maven' + (path[len('/releases'):] if path.startswith('/releases/') else path)
    else:
        return None
    return mirror + path + ('?' + parsed.query if parsed.query else '')


def source_urls(source, official, bmcl=None):
    official = publisher_url(official)
    bmcl = bmcl or mirror_url(official, BMCLAPI)
    ming = mirror_url(official, MCMIRROR)
    if source == 'MCMirror':
        urls = [ming, bmcl, official]
    elif source in ('官方', '自动（官方优先，失败切换镜像）'):
        urls = [official, bmcl, ming]
    else:
        urls = [bmcl, ming, official]
    return list(dict.fromkeys(url for url in urls if url))
