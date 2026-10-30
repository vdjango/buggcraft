"""Download addresses for progress views, without embedded credentials."""
from urllib.parse import urlsplit, urlunsplit


def source_name(url):
    try:
        host = urlsplit(url).hostname or ''
    except (ValueError, TypeError):
        return ''
    if host == 'mod.mcimirror.top':
        return 'MCIM'
    if host == 'mirror.minguncle.cn':
        return 'MCMirror'
    if host == 'cdn.modrinth.com':
        return 'Modrinth'
    if host in ('maven.minecraftforge.net', 'files.minecraftforge.net'):
        return 'Forge'
    if host == 'maven.neoforged.net':
        return 'NeoForge'
    if host in ('maven.fabricmc.net', 'meta.fabricmc.net'):
        return 'Fabric'
    if host in ('maven.quiltmc.org', 'meta.quiltmc.org'):
        return 'Quilt'
    if host.endswith('.forgecdn.net'):
        return 'CurseForge'
    if host == 'bmclapi2.bangbang93.com' or host.endswith('.bmclapi.com'):
        return 'BMCLAPI'
    if host == 'mojang.com' or host.endswith(('.mojang.com', '.minecraft.net')):
        return 'Mojang'
    return host


def display_address(url):
    if not isinstance(url, str):
        return ''
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname:
            return ''
        # Signed query strings and URL user information are not needed to
        # identify the CDN and file, and must not enter download history.
        return urlunsplit((parsed.scheme, parsed.netloc.rsplit('@', 1)[-1], parsed.path, '', ''))
    except ValueError:
        return ''
