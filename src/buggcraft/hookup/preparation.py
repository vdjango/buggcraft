"""Prepare a separate game configuration without changing existing mod folders."""
import asyncio
import json
import copy
import hashlib
import os
from pathlib import Path
import re
import secrets
import shutil
import threading
import time

from .modpack import fetch_manifest, fetch_mod, manifest_hash
from .rooms import metadata_loader


class _AnyCancel:
    def __init__(self, *events):
        self.events = events

    def is_set(self):
        return any(event.is_set() for event in self.events)

    def wait(self, timeout=None):
        deadline = None if timeout is None else time.monotonic() + timeout
        while not self.is_set():
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                return False
            self.events[0].wait(min(.05, remaining) if remaining is not None else .05)
        return True


def _verify_mod(path, item, cancel):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            if cancel.is_set():
                raise InterruptedError('安装已取消。')
            digest.update(block)
    if path.stat().st_size != item['size'] or digest.hexdigest() != item['sha256']:
        raise ValueError('模组校验失败：' + item['name'])


async def _download_room_mod(endpoint, item, base, target, source, cancel, progress):
    """Race independent public/P2P files; publish only a verified winner."""
    paths = {name: target.with_name('.' + name + '-' + target.name)
             for name in ('public', 'p2p')}
    stops = {name: threading.Event() for name in paths}
    signals = {name: _AnyCancel(cancel, stops[name]) for name in paths}

    async def download(name):
        path, signal = paths[name], signals[name]
        callback = lambda done, total: progress(name, done, total)
        if name == 'public':
            if not await fetch_public_mod(item, base, path, source, signal, callback):
                return ''
        else:
            # Public mirrors get the first chance. Start the direct file
            # channel shortly after so a slow or missing mirror can be
            # assisted without making P2P the visible primary path.
            for _ in range(5):
                if signal.is_set():
                    return ''
                await asyncio.sleep(.1)
            await fetch_mod(endpoint, item, path, signal, callback)
        await asyncio.to_thread(_verify_mod, path, item, signal)
        return name

    tasks = {name: asyncio.create_task(download(name)) for name in paths}
    errors = {}
    winner = ''
    try:
        pending = set(tasks.values())
        while pending and not winner:
            if cancel.is_set():
                raise InterruptedError('安装已取消。')
            done, pending = await asyncio.wait(pending, timeout=.1,
                                               return_when=asyncio.FIRST_COMPLETED)
            for name, task in tasks.items():
                if task not in done:
                    continue
                try:
                    winner = task.result() or winner
                except Exception as exc:
                    errors[name] = exc
        if not winner:
            error = errors.get('p2p') or errors.get('public')
            if error is not None and 'P2P file channel' not in str(error):
                raise error
            raise ConnectionError('下载失败，正在重试。')
        if cancel.is_set():
            raise InterruptedError('安装已取消。')
        await asyncio.to_thread(os.replace, paths[winner], target)
        return winner
    finally:
        for stop in stops.values():
            stop.set()
        # to_thread cannot be forcibly cancelled: wait for writers to stop
        # before removing their temporary files or the instance directory.
        await asyncio.shield(asyncio.gather(*tasks.values(), return_exceptions=True))
        for path in paths.values():
            path.unlink(missing_ok=True)
            path.with_name(path.name + '.buggcraft-part').unlink(missing_ok=True)


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
        progress_lock = threading.Lock()
        active_progress = [0] * len(items)
        last_progress = [0.0] * len(items)
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
        semaphore = asyncio.Semaphore(4)
        aborted = threading.Event()
        signal = _AnyCancel(cancel, aborted)

        async def prepare_mod(index, item):
            nonlocal completed_bytes
            async with semaphore:
                if signal.is_set():
                    raise InterruptedError('??????')
                status = f'下载模组 {index + 1}/{len(items)} · ' + item['name']
                event(dict(kind='file', name=item['name'], state='downloading', size=item['size'],
                           index=index + 1, count=len(items)))

                source_progress = {}

                def source_progress_update(source_name, done, total):
                    if signal.is_set():
                        raise InterruptedError('安装已取消。')
                    now = time.monotonic()
                    with progress_lock:
                        source_progress[source_name] = max(0, min(done, item['size']))
                        done = max(source_progress.values())
                        active_progress[index] = done
                        current = completed_bytes + sum(active_progress)
                        should_report = now - last_progress[index] >= .1 or done >= total
                        if should_report:
                            last_progress[index] = now
                    if not should_report:
                        return
                    report(status, current, total_bytes)
                    event(dict(kind='progress', name=item['name'], done=done, total=item['size'],
                               index=index + 1, count=len(items)))

                final_path = mods / item['name']
                try:
                    cached = existing_by_hash.get(item['sha256'])
                    if cached:
                        await asyncio.to_thread(shutil.copy2, cached, final_path)
                        source_progress_update('cached', item['size'], item['size'])
                    else:
                        await _download_room_mod(endpoint, item, base, final_path, source,
                                                 signal, source_progress_update)
                    await asyncio.to_thread(_verify_mod, final_path, item, signal)
                except BaseException as exc:
                    aborted.set()
                    event(dict(kind='file', name=item['name'], state='failed', size=item['size'], error=str(exc)))
                    raise
                with progress_lock:
                    completed_bytes += item['size']
                    active_progress[index] = 0
                    completed = completed_bytes
                report('模组已下载并校验：' + item['name'], completed, total_bytes)
                event(dict(kind='file', name=item['name'], state='verified', size=item['size'],
                           sha256=item['sha256'], path=str(final_path)))

        tasks = [asyncio.create_task(prepare_mod(index, item)) for index, item in enumerate(items)]
        outcomes = await asyncio.gather(*tasks, return_exceptions=True)
        failures = [result for result in outcomes if isinstance(result, BaseException)]
        if failures:
            raise next((failure for failure in failures if not isinstance(failure, InterruptedError)), failures[0])
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
