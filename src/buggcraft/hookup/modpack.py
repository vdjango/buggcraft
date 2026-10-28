"""Room-scoped mod manifests and transfers delegated to the C++ bridge."""
import hashlib
from pathlib import Path
import re

MAX_MODS = 1000
MAX_RESOURCES = 2000
MAX_MANIFEST = 512 * 1024
MAX_MOD_SIZE = 2 * 1024 * 1024 * 1024


def validate_manifest(value, kind='mods'):
    if kind not in ('mods', 'resources'):
        raise ValueError('Invalid room content kind')
    limit = MAX_MODS if kind == 'mods' else MAX_RESOURCES
    if not isinstance(value, list) or len(value) > limit:
        raise ValueError('房间内容列表无效或过大。')
    names = set()
    for item in value:
        if not isinstance(item, dict):
            raise ValueError('房间模组信息无效。')
        name, digest, size = item.get('name'), item.get('sha256'), item.get('size')
        if (not isinstance(name, str) or not 1 <= len(name) <= 240 or
                any(ch in name for ch in '/\\:') or name in ('.', '..') or
                (kind == 'mods' and not name.lower().endswith('.jar')) or any(not ch.isprintable() for ch in name) or
                (('mods/' + name).casefold() if kind == 'mods' else
                 str(item.get('path', '')).casefold()) in names or not isinstance(digest, str) or
                not re.fullmatch('[0-9a-f]{64}', digest) or type(size) is not int or
                not 0 <= size <= MAX_MOD_SIZE):
            raise ValueError('房间内容文件名、校验值或大小无效。')
        if kind == 'resources':
            path = item.get('path')
            if (not isinstance(path, str) or not path.startswith(('resourcepacks/', 'shaderpacks/')) or
                    Path(path).name != name or '\\' in path or path.count('/') != 1):
                raise ValueError('房间资源路径无效。')
        sha1 = item.get('sha1')
        if sha1 is not None and (not isinstance(sha1, str) or not re.fullmatch('[0-9a-f]{40}', sha1)):
            raise ValueError('房间模组 SHA-1 信息无效。')
        names.add((('mods/' + name) if kind == 'mods' else item['path']).casefold())
    return value


def manifest(directory, kind='mods'):
    if kind not in ('mods', 'resources'):
        raise ValueError('Invalid room content kind')
    base = Path(directory).resolve()
    root = base / 'mods' if kind == 'mods' else base
    result = []
    candidates = ([('mods/' + path.name, path) for path in root.glob('*.jar')]
                  if kind == 'mods' else
                  [(folder + '/' + path.name, path)
                   for folder in ('resourcepacks', 'shaderpacks')
                   for path in (base / folder).glob('*') if path.is_file()])
    for relative, path in sorted(candidates, key=lambda value: value[0].casefold()):
        parent = root if kind == 'mods' else base / relative.split('/', 1)[0]
        if not path.resolve().is_relative_to(parent.resolve()):
            raise ValueError('模组链接指向游戏目录之外。')
        digest = hashlib.sha256()
        with path.open('rb') as source:
            for block in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(block)
        item = dict(name=path.name, sha256=digest.hexdigest(), size=path.stat().st_size)
        if kind == 'resources':
            item['path'] = relative
        result.append(item)
    return validate_manifest(result, kind)


def manifest_hash(items):
    return hashlib.sha256('\n'.join(sorted(item['sha256'] for item in items)).encode()).hexdigest()


async def fetch_manifest(endpoint, kind='mods'):
    try:
        raw = await endpoint.mod_manifest(kind)
    except TypeError:
        # Older in-process fixtures and third-party endpoints only accepted
        # the original mod manifest call. Keep that boundary compatible while
        # the native bridge rolls out the optional resource kind.
        if kind != 'mods':
            raise
        raw = await endpoint.mod_manifest()
    items = validate_manifest(raw, kind)
    expected = (endpoint.room_info or {}).get('game', {})
    count_key, hash_key = ('mods_count', 'mods_hash') if kind == 'mods' else ('resources_count', 'resources_hash')
    if (expected.get(count_key, len(items)) != len(items) or
            expected.get(hash_key) and manifest_hash(items) != expected[hash_key]):
        raise ValueError('Room content changed; refresh the room before retrying')
    return items


async def fetch_mod(endpoint, item, target, cancel, progress):
    return await endpoint.download_mod(item, target, cancel, progress)
