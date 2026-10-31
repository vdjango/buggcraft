"""Reserved routes for the Buggcraft mirror. No requests until rollout enables it."""
from urllib.parse import urlsplit, unquote, quote

BASE_URL = 'https://mirror.bugg.icu'
ENABLED = False


def mirror_url(url):
    if not ENABLED:
        return None
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.port not in (None, 443)
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        return None
    path = unquote(parsed.path)
    if any(part in ('.', '..') for part in path.split('/')) or any(c in path for c in ('%', '\\', '\x00', ':')):
        return None
    host = parsed.hostname
    import re
    if host in ('piston-meta.mojang.com', 'launchermeta.mojang.com') and (
            re.fullmatch(r'/mc/game/version_manifest(?:_v2)?\.json', path)
            or re.fullmatch(r'/v1/packages/[a-f0-9]{40}/[A-Za-z0-9._ @-]+', path)
            or path.startswith('/v1/products/java-runtime/')):
        route = path
    elif host in ('piston-data.mojang.com', 'launcher.mojang.com') and re.fullmatch(
            r'/v1/objects/[a-f0-9]{40}/[A-Za-z0-9._ @-]+', path):
        route = path
    elif host == 'resources.download.minecraft.net' and re.fullmatch(r'/[a-f0-9]{2}/[a-f0-9]{40}', path):
        if path[1:3] != path[4:6]:
            return None
        route = '/assets' + path
    elif host == 'libraries.minecraft.net':
        route = '/maven' + path
    elif host in ('meta.fabricmc.net', 'meta.quiltmc.org'):
        route = ('/fabric-meta' if host == 'meta.fabricmc.net' else '/quilt-meta') + path
    elif host == 'maven.fabricmc.net' and path.startswith(('/net/fabricmc/fabric-loader/',
            '/net/fabricmc/intermediary/', '/net/fabricmc/tiny-', '/net/fabricmc/sponge-mixin/')):
        route = '/fabric-maven' + path
    elif host == 'maven.quiltmc.org' and path.startswith(('/repository/release/org/quiltmc/quilt-loader/',
            '/repository/release/org/quiltmc/hashed/')):
        route = '/quilt-maven' + path
    elif host == 'maven.neoforged.net' and path.startswith(('/releases/net/neoforged/',
            '/releases/cpw/mods/', '/releases/net/minecraftforge/')):
        route = '/neoforge-maven' + path
    elif host in ('edge.forgecdn.net', 'mediafilez.forgecdn.net') and re.fullmatch(
            r'/files/[0-9]+/[0-9]+/[A-Za-z0-9._ +@-]+\.jar', path):
        route = '/mods/curseforge' + path
    elif host == 'cdn.modrinth.com' and re.fullmatch(
            r'/data/[A-Za-z0-9_-]+/versions/[A-Za-z0-9_-]+/[A-Za-z0-9._ +@-]+\.jar', path):
        route = '/mods/modrinth' + path
    else:
        return None
    return BASE_URL + quote(route, safe='/@+')
