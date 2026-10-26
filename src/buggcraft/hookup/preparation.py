"""Prepare a separate game configuration without changing existing mod folders."""
import asyncio
import json
import copy
import hashlib
from pathlib import Path
import re
import secrets
import shutil
import time

from .modpack import fetch_manifest, fetch_mod, manifest_hash
from .rooms import metadata_loader


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
    from core.loaders import available_versions, install_loader
    version = game.get('version', '')
    if not re.fullmatch(r'[A-Za-z0-9_.+-]{1,64}', version) or version in ('.', '..'):
        raise ValueError('房间游戏版本无效。')
    loader = game.get('loader', 'vanilla').lower()
    if loader == 'vanilla':
        if game.get('mods_count') or game.get('mods'):
            raise ValueError('房间包含模组，但未识别到加载器。请房主选择实际运行的 Forge、NeoForge、Fabric 或 Quilt 实例并更新房间配置。')
        MinecraftDownloader(directory, source=source, cancel=cancel,
            status=lambda text: report(text, 0, 0),
            progress=lambda done, total: report('正在安装 Minecraft ' + version, done, total)).install(version)
        return version
    loaders = {'forge': 'Forge', 'neoforge': 'NeoForge', 'fabric': 'Fabric', 'quilt': 'Quilt'}
    loader_version = game.get('loader_version', '')
    if loader not in loaders or (loader_version and not re.fullmatch(r'[A-Za-z0-9_.+-]{1,64}', loader_version)):
        raise ValueError('房间加载器信息无效。')
    if loader == 'forge' and loader_version.startswith(version + '-'):
        loader_version = loader_version[len(version) + 1:]
    if not java:
        raise ValueError('请先在设置中选择 Java，才能安装游戏加载器。')
    if cancel.is_set():
        raise InterruptedError('安装已取消。')
    report('正在核对 ' + loaders[loader] + ' 加载器版本…', 0, 0)
    try:
        versions = available_versions(loaders[loader], version, source)
    except Exception:
        # A catalogue outage must not prevent installing the host's known build.
        if not loader_version or cancel.is_set():
            raise
        versions = [loader_version]
    if loader_version not in versions:
        if not versions:
            raise ValueError(f'没有适用于 Minecraft {version} 的 {loaders[loader]} 版本，请确认房主的游戏和加载器信息。')
        previous = loader_version or '未提供'
        loader_version = versions[0]
        report(f'房主 {loaders[loader]} {previous} 暂不可用，使用适用于 Minecraft {version} 的 {loader_version}；加载器类型保持一致。', 0, 0)
    else:
        report(f'使用与房主一致的 {loaders[loader]} {loader_version}', 0, 0)
    progress = {'maximum': 0}
    callback = dict(setStatus=lambda text: report(text, 0, 0),
                    setMax=lambda total: progress.update(maximum=total),
                    setProgress=lambda done: report('正在安装 ' + loaders[loader], done, progress['maximum']))
    return install_loader(loaders[loader], version, loader_version, directory, java, callback, cancel, source)


async def fetch_public_mod(item, base, target, source, cancel, progress):
    """Try a byte-identical Modrinth file before asking the room host to send it."""
    if not item.get('sha1'):
        return False
    try:
        from core.content_mirrors import get_modrinth
        content_source = '官方' if source == '官方' else 'MCIM'
        metadata = await asyncio.to_thread(get_modrinth, '/version_file/' + item['sha1'],
                                           {}, cancel, content_source)
        candidates = []
        for file in (metadata or {}).get('files', []):
            hashes = file.get('hashes', {})
            if (hashes.get('sha1') == item['sha1'] and file.get('size') == item['size'] and
                    (not item.get('sha512') or hashes.get('sha512') == item['sha512'])):
                candidates.append(file)
        if not candidates:
            return False
        file = next((value for value in candidates if value.get('primary') is True), candidates[0])
        from urllib.parse import urlsplit
        url = file.get('url', '')
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or parsed.hostname != 'cdn.modrinth.com' or
                parsed.username or parsed.password or parsed.port not in (None, 443)):
            return False
        from core.downloads import MinecraftDownloader
        relative = target.relative_to(base).as_posix()
        downloader = MinecraftDownloader(base, source=source, cancel=cancel)
        downloader.content_source = content_source
        await asyncio.to_thread(downloader.fetch, url, relative, item['sha1'], item['size'],
                                file_progress=progress)
        return True
    except Exception:
        if cancel.is_set():
            raise InterruptedError('安装已取消。')
        return False


async def prepare_configuration(endpoint, directory, java, source, cancel, report, event=None,
                                existing_instance=None):
    event = event or (lambda value: None)
    game = dict((endpoint.room_info or {}).get('game') or {})
    count = game.get('mods_count', len(game.get('mods', [])))
    # Fetch and validate before creating a new configuration. No arbitrary URLs
    # or executable paths from a peer are used by the installer.
    items = await fetch_manifest(endpoint) if count else []
    game['mods_count'] = len(items)
    event(dict(kind='manifest', files=items))
    if cancel.is_set():
        raise InterruptedError('安装已取消。')
    base = Path(directory).resolve()
    if existing_instance:
        installed = existing_instance['version']
        metadata = await asyncio.to_thread(resolved_metadata, base, installed)
        installed_loader, _ = metadata_loader(metadata)
        expected_loader = game.get('loader', 'vanilla').lower()
        if installed_loader != expected_loader:
            raise ValueError(f'所选配置的加载器为 {installed_loader}，房间需要 {expected_loader}；请选择匹配的配置。')
        from .rooms import instance_metadata
        local_game = await asyncio.to_thread(instance_metadata, base, installed,
                                             existing_instance.get('game_directory'))
        if local_game.get('version') != game.get('version') or local_game.get('loader') != expected_loader:
            raise ValueError('所选配置的 Minecraft 或加载器与房间不符。')
    else:
        installed = await asyncio.to_thread(install_game, game, str(directory), java, source, cancel, report)
        metadata = await asyncio.to_thread(resolved_metadata, base, installed)
    if cancel.is_set():
        raise InterruptedError('安装已取消。')
    loader, _ = metadata_loader(metadata)
    expected_loader = game.get('loader', 'vanilla').lower()
    if loader != expected_loader or (items and loader == 'vanilla'):
        raise ValueError('加载器安装校验失败：房间需要 ' + expected_loader + '，实际安装为 ' + loader + '。不会启动原版游戏。')
    identity = 'room-' + re.sub('[^A-Za-z0-9_-]', '-', game['version']) + '-' + secrets.token_hex(4)
    target = base / 'versions' / identity
    target.mkdir(parents=True, exist_ok=False)
    marker = target / '.buggcraft-preparing'
    marker.write_text('Room preparation in progress', encoding='utf8')
    try:
        mods = target / 'mods'
        mods.mkdir()
        completed_bytes = 0
        total_bytes = sum(item['size'] for item in items)
        existing_mods = (Path(existing_instance.get('game_directory') or base) / 'mods'
                         if existing_instance else None)
        existing_by_hash = {}
        if existing_mods and existing_mods.is_dir():
            for candidate in existing_mods.glob('*.jar'):
                digest = hashlib.sha256()
                with candidate.open('rb') as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b''):
                        digest.update(block)
                existing_by_hash.setdefault(digest.hexdigest(), candidate)
        for index, item in enumerate(items):
            status = f'下载模组 {index + 1}/{len(items)} · ' + item['name']
            event(dict(kind='file', name=item['name'], state='downloading', size=item['size'],
                       index=index + 1, count=len(items)))
            last = [0.0]
            def progress(done, total):
                if cancel.is_set():
                    raise InterruptedError('安装已取消。')
                now = time.monotonic()
                if now - last[0] < .1 and done < total:
                    return
                last[0] = now
                done = max(0, min(done, item['size']))
                report(status, completed_bytes + done, total_bytes)
                event(dict(kind='progress', name=item['name'], done=done, total=item['size'],
                           index=index + 1, count=len(items)))
            report(status, completed_bytes, total_bytes)
            try:
                cached = existing_by_hash.get(item['sha256'])
                if cached:
                    await asyncio.to_thread(shutil.copy2, cached, mods / item['name'])
                    progress(item['size'], item['size'])
                else:
                    downloaded = await fetch_public_mod(item, base, mods / item['name'], source, cancel, progress)
                    if not downloaded:
                        (mods / item['name']).unlink(missing_ok=True)
                        try:
                            await fetch_mod(endpoint, item, mods / item['name'], cancel, progress)
                        except Exception as exc:
                            if not cancel.is_set() and 'transfer' in str(exc).lower():
                                raise ConnectionError('模组资源不可用，且房主尚未授权从本机传输；请房主在房间设置中允许模组共享。') from exc
                            raise
                if cancel.is_set():
                    raise InterruptedError('安装已取消。')
                digest = hashlib.sha256()
                with (mods / item['name']).open('rb') as downloaded:
                    for block in iter(lambda: downloaded.read(1024 * 1024), b''):
                        digest.update(block)
                if (mods / item['name']).stat().st_size != item['size'] or digest.hexdigest() != item['sha256']:
                    raise ValueError('模组校验失败：' + item['name'])
            except BaseException as exc:
                event(dict(kind='file', name=item['name'], state='failed', size=item['size'], error=str(exc)))
                raise
            completed_bytes += item['size']
            report('模组已下载并校验：' + item['name'], completed_bytes, total_bytes)
            event(dict(kind='file', name=item['name'], state='verified', size=item['size'],
                       sha256=item['sha256'], path=str(mods / item['name'])))
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
        event(dict(kind='complete', version=identity, loader=loader))
        report('游戏配置已准备完成', 1, 1)
        return identity
    except BaseException:
        # Incomplete directory has no usable version JSON and is never selected.
        (target / (identity + '.json')).unlink(missing_ok=True)
        raise
