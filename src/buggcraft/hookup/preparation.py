"""Prepare a separate game configuration without changing existing mod folders."""
import asyncio
import json
import copy
import hashlib
from pathlib import Path
import re
import secrets

from .modpack import fetch_manifest, fetch_mod, manifest_hash


def resolved_metadata(directory, identity, seen=None):
    """Resolve nested loader inheritance before cloning a room configuration."""
    root = Path(directory)
    seen = set() if seen is None else seen
    if identity in seen or Path(identity).name != identity or identity in ('.', '..'):
        raise ValueError('游戏版本继承无效。')
    seen.add(identity)
    child = json.loads((root / 'versions' / identity / (identity + '.json')).read_text(encoding='utf8'))
    if not child.get('inheritsFrom'):
        child.setdefault('jar', identity)
        return child
    parent = resolved_metadata(root, child['inheritsFrom'], seen)
    result = copy.deepcopy(parent)
    def library_key(item):
        coordinate = item['name'].split(':')
        # Classifiers distinguish the ordinary library from its native binaries.
        return tuple(coordinate[:2] + coordinate[3:])
    libraries = {library_key(item): item for item in parent.get('libraries', [])}
    for item in child.get('libraries', []):
        libraries[library_key(item)] = item
    for key, value in child.items():
        if key == 'arguments':
            result['arguments'] = {kind: parent.get('arguments', {}).get(kind, []) + value.get(kind, [])
                                   for kind in set(parent.get('arguments', {})) | set(value)}
        elif key not in ('inheritsFrom', 'libraries'):
            result[key] = value
    result['libraries'] = list(libraries.values())
    result.pop('inheritsFrom', None)
    return result


def install_game(game, directory, java, source, cancel, report):
    from core.downloads import MinecraftDownloader
    from core.loaders import install_loader
    version = game.get('version', '')
    if not re.fullmatch(r'[A-Za-z0-9_.+-]{1,64}', version) or version in ('.', '..'):
        raise ValueError('房间游戏版本无效。')
    loader = game.get('loader', 'vanilla').lower()
    if loader == 'vanilla':
        MinecraftDownloader(directory, source=source, cancel=cancel,
            status=lambda text: report(text, 0, 0),
            progress=lambda done, total: report('正在安装 Minecraft ' + version, done, total)).install(version)
        return version
    loaders = {'forge': 'Forge', 'neoforge': 'NeoForge', 'fabric': 'Fabric', 'quilt': 'Quilt'}
    loader_version = game.get('loader_version', '')
    if loader not in loaders or not re.fullmatch(r'[A-Za-z0-9_.+-]{1,64}', loader_version):
        raise ValueError('房间加载器信息无效。')
    if loader == 'forge' and loader_version.startswith(version + '-'):
        loader_version = loader_version[len(version) + 1:]
    if not java:
        raise ValueError('请先在设置中选择 Java，才能安装游戏加载器。')
    progress = {'maximum': 0}
    callback = dict(setStatus=lambda text: report(text, 0, 0),
                    setMax=lambda total: progress.update(maximum=total),
                    setProgress=lambda done: report('正在安装 ' + loaders[loader], done, progress['maximum']))
    return install_loader(loaders[loader], version, loader_version, directory, java, callback, cancel, source)


async def prepare_configuration(endpoint, directory, java, source, cancel, report):
    game = dict((endpoint.room_info or {}).get('game') or {})
    count = game.get('mods_count', len(game.get('mods', [])))
    # Fetch and validate before creating a new configuration. No arbitrary URLs
    # or executable paths from a peer are used by the installer.
    items = await fetch_manifest(endpoint) if count else []
    if cancel.is_set():
        raise InterruptedError('安装已取消。')
    installed = await asyncio.to_thread(install_game, game, str(directory), java, source, cancel, report)
    if cancel.is_set():
        raise InterruptedError('安装已取消。')
    base = Path(directory).resolve()
    metadata = resolved_metadata(base, installed)
    identity = 'room-' + re.sub('[^A-Za-z0-9_-]', '-', game['version']) + '-' + secrets.token_hex(4)
    target = base / 'versions' / identity
    target.mkdir(parents=True, exist_ok=False)
    marker = target / '.buggcraft-preparing'
    marker.write_text('Room preparation in progress', encoding='utf8')
    try:
        mods = target / 'mods'
        mods.mkdir()
        for index, item in enumerate(items):
            report('下载模组 ' + item['name'], index, len(items))
            await fetch_mod(endpoint, item, mods / item['name'], cancel,
                            lambda done, total: report('下载模组 ' + item['name'], done, total))
        actual = manifest_hash(items)
        if game.get('mods_hash') and actual != game['mods_hash']:
            raise ValueError('房间模组已改变，请重新准备。')
        current_game = (endpoint.room_info or {}).get('game', {})
        if any(current_game.get(key) != game.get(key) for key in
               ('version', 'loader', 'loader_version', 'mods_hash')):
            raise ValueError('安装期间房间配置发生变化，请按最新配置重试。')
        # Inherit installed libraries and vanilla assets; game data and mods use
        # this new directory, including when global version isolation is disabled.
        isolated = dict(metadata, id=identity, buggcraftRoom={'version': game['version'],
                        'parent': installed, 'mods_hash': actual})
        (target / (identity + '.json')).write_text(json.dumps(isolated, ensure_ascii=False, indent=2), encoding='utf8')
        receipt_path = base / 'versions' / game['version'] / '.buggcraft-complete.json'
        if receipt_path.is_file():
            receipt = json.loads(receipt_path.read_text(encoding='utf8'))
            receipt['version'] = identity
            receipt['files'].append({'path': str((target / (identity + '.json')).relative_to(base)),
                                    'sha1': hashlib.sha1((target / (identity + '.json')).read_bytes()).hexdigest()})
            (target / '.buggcraft-complete.json').write_text(json.dumps(receipt), encoding='utf8')
        marker.unlink()
        report('游戏配置已准备完成', 1, 1)
        return identity
    except BaseException:
        # Incomplete directory has no usable version JSON and is never selected.
        (target / (identity + '.json')).unlink(missing_ok=True)
        raise
