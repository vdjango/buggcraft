"""Room-scoped, hash-verified mod transfer over authenticated SSH channels."""
import hashlib
from pathlib import Path
import re

MAX_MODS = 1000
MAX_MANIFEST = 512 * 1024
MAX_MOD_SIZE = 2 * 1024 * 1024 * 1024


def validate_manifest(value):
    if not isinstance(value, list) or len(value) > MAX_MODS:
        raise ValueError('房间模组列表无效或过大。')
    names = set()
    for item in value:
        if not isinstance(item, dict):
            raise ValueError('房间模组信息无效。')
        name, digest, size = item.get('name'), item.get('sha256'), item.get('size')
        if (not isinstance(name, str) or not 1 <= len(name) <= 240 or
                any(ch in name for ch in '/\\:') or name in ('.', '..') or
                not name.lower().endswith('.jar') or any(not ch.isprintable() for ch in name) or
                name.casefold() in names or not isinstance(digest, str) or
                not re.fullmatch('[0-9a-f]{64}', digest) or type(size) is not int or
                not 0 <= size <= MAX_MOD_SIZE):
            raise ValueError('房间模组文件名、校验值或大小无效。')
        sha1 = item.get('sha1')
        if sha1 is not None and (not isinstance(sha1, str) or not re.fullmatch('[0-9a-f]{40}', sha1)):
            raise ValueError('房间模组 SHA-1 信息无效。')
        names.add(name.casefold())
    return value


def manifest(directory):
    root = (Path(directory) / 'mods').resolve()
    result = []
    for path in sorted(root.glob('*.jar'), key=lambda p: p.name.casefold()):
        if not path.resolve().is_relative_to(root):
            raise ValueError('模组链接指向游戏目录之外。')
        digest = hashlib.sha256()
        with path.open('rb') as source:
            for block in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(block)
        result.append(dict(name=path.name, sha256=digest.hexdigest(), size=path.stat().st_size))
    return validate_manifest(result)


def manifest_hash(items):
    return hashlib.sha256('\n'.join(sorted(item['sha256'] for item in items)).encode()).hexdigest()


async def fetch_manifest(endpoint):
    items = validate_manifest(await endpoint.mod_manifest())
    expected = (endpoint.room_info or {}).get('game', {})
    if (expected.get('mods_count', len(items)) != len(items) or
            expected.get('mods_hash') and manifest_hash(items) != expected['mods_hash']):
        raise ValueError('Room mods changed; refresh the room before retrying')
    return items


async def fetch_mod(endpoint, item, target, cancel, progress):
    return await endpoint.download_mod(item, target, cancel, progress)
