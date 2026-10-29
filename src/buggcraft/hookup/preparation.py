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

    def set(self):
        self.events[-1].set()

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
        raise ValueError('内容校验失败：' + item['name'])


async def _download_room_mod(endpoint, item, base, target, source, cancel, progress, host_ready=None):
    """Exhaust the configured source, then permit an established P2P fallback."""
    # Staging directories are disposable. Keep verified content and public
    # download checkpoints outside them, keyed by the authenticated manifest.
    cache = Path(base) / '.buggcraft-downloads' / 'room-content' / item['sha256']
    cache.mkdir(parents=True, exist_ok=True)
    cached = cache / 'content'
    if cached.is_file():
        try:
            await asyncio.to_thread(_verify_mod, cached, item, cancel)
        except ValueError:
            cached.unlink(missing_ok=True)
        else:
            await asyncio.to_thread(shutil.copy2, cached, target)
            progress('cached', item['size'], item['size'])
            return 'cached'
    paths = {'public': cached, 'p2p': cache / ('.p2p-' + secrets.token_hex(8))}
    try:
        winner = ''
        try:
            found = await fetch_public_mod(item, base, paths['public'], source, cancel,
                                           lambda done, total: progress('public', done, total))
            if found:
                await asyncio.to_thread(_verify_mod, paths['public'], item, cancel)
                winner = 'public'
        except InterruptedError:
            raise
        except Exception:
            # A corrupt public copy is treated as an unavailable source. The
            # independent direct download must pass the same verification.
            cached.unlink(missing_ok=True)
        if not winner:
            # Public files can overlap game installation; avoid asking the host
            # for a fallback before the requested loader has been validated.
            while host_ready is not None and not host_ready.is_set():
                if cancel.is_set():
                    raise InterruptedError('安装已取消。')
                try:
                    await asyncio.wait_for(host_ready.wait(), timeout=0.1)
                except asyncio.TimeoutError:
                    pass
            if cancel.is_set():
                raise InterruptedError('安装已取消。')
            if getattr(endpoint, 'transport_state', None) != 'p2p':
                raise ConnectionError('下载源未找到可用文件，当前未建立 P2P 直连，无法从房主下载。请更换下载源或在 P2P 连接成功后重试。')
            await fetch_mod(endpoint, item, paths['p2p'], cancel,
                            lambda done, total: progress('p2p', done, total))
            await asyncio.to_thread(_verify_mod, paths['p2p'], item, cancel)
            winner = 'p2p'
        if cancel.is_set():
            raise InterruptedError('安装已取消。')
        if winner == 'p2p':
            await asyncio.to_thread(os.replace, paths['p2p'], cached)
        await asyncio.to_thread(shutil.copy2, cached, target)
        return winner
    finally:
        # Public transfers use hash-bound checkpoints and survive failure or
        # cancellation. Native P2P has no Range contract; only reuse full files.
        paths['p2p'].unlink(missing_ok=True)


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


def install_game(game, directory, java, source, cancel, report, file_event=None):
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
            progress=lambda done, total: report('正在安装 Minecraft ' + version, done, total), file_event=file_event).install(version)
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
    callback = dict(fileEvent=file_event, setStatus=lambda text: report(text, 0, 0),
                    setMax=lambda total: progress.update(maximum=total),
                    setProgress=lambda done: report('正在安装 ' + loaders[loader], done, progress['maximum']))
    return install_loader(loaders[loader], version, loader_version, directory, java, callback, cancel, source)


async def fetch_public_mod(item, base, target, source, cancel, progress):
    """Try a byte-identical Modrinth file before asking the room host to send it."""
    if not item.get('sha1'):
        return False
    try:
        from core.content_mirrors import get_modrinth
        content_source = source if source in ('官方', 'MCIM', '自动测速') else '自动测速'
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
        downloader = MinecraftDownloader(base, source=source, cancel=cancel, workers=1)
        downloader.parallel_content = False  # Room files already share a bounded pool.
        downloader.content_source = content_source
        await asyncio.to_thread(downloader.fetch, url, relative, item['sha1'], item['size'],
                                file_progress=progress)
        item['downloads'] = [url]
        return True
    except Exception:
        if cancel.is_set():
            raise InterruptedError('安装已取消。')
        return False


async def prepare_configuration(endpoint, directory, java, source, cancel, report, event=None,
                                existing_instance=None, content_source=None):
    from core.downloads import use_download_budget
    with use_download_budget() as budget:
        return await _prepare_configuration(endpoint, directory, java, source, cancel, report, event,
                                            existing_instance, content_source, budget)


async def _prepare_configuration(endpoint, directory, java, source, cancel, report, event=None,
                                 existing_instance=None, content_source=None, budget=None):
    from core.downloads import DownloadCancelled
    event = event or (lambda value: None)
    game = dict((endpoint.room_info or {}).get('game') or {})
    count = game.get('mods_count', len(game.get('mods', [])))
    # Fetch and validate before creating a new configuration. No arbitrary URLs
    # or executable paths from a peer are used by the installer.
    items = await fetch_manifest(endpoint) if count else []
    resource_items = []
    resource_count = game.get('resources_count', len(game.get('resources', [])))
    if resource_count:
        # Resource packs and shaders are optional presentation assets. A
        # missing mirror or host file is reported, but does not block joining.
        try:
            resource_items = await fetch_manifest(endpoint, 'resources')
        except Exception as exc:
            event(dict(kind='resources', state='skipped', reason=str(exc)))
    game['mods_count'] = len(items)
    game['resources_count'] = len(resource_items)
    event(dict(kind='manifest', files=items, resources=resource_items))
    if cancel.is_set():
        raise InterruptedError('安装已取消。')
    base = Path(directory).resolve()
    expected_loader = game.get('loader', 'vanilla').lower()
    host_ready = asyncio.Event()
    if existing_instance:
        installed = existing_instance['version']
        metadata = await asyncio.to_thread(resolved_metadata, base, installed)
        installed_loader, _ = metadata_loader(metadata)
        if installed_loader != expected_loader or (items and installed_loader == 'vanilla'):
            raise ValueError('加载器安装校验失败：房间需要 ' + expected_loader + '，实际安装为 ' + installed_loader + '。不会启动原版游戏。')
        from .rooms import instance_metadata
        local_game = await asyncio.to_thread(instance_metadata, base, installed,
                                             existing_instance.get('game_directory'))
        if local_game.get('version') != game.get('version') or local_game.get('loader') != expected_loader:
            raise ValueError('所选配置的 Minecraft 或加载器与房间不符。')
        loader = installed_loader
        host_ready.set()
    aborted = threading.Event()
    signal = _AnyCancel(cancel, aborted)
    game_task = None
    identity = 'room-' + re.sub('[^A-Za-z0-9_-]', '-', game['version']) + '-' + secrets.token_hex(4)
    published = base / 'versions' / identity
    target = base / '.buggcraft-downloads' / 'room-preparation' / identity
    target.mkdir(parents=True, exist_ok=False)
    marker = target / '.buggcraft-preparing'
    marker.write_text('Room preparation in progress', encoding='utf8')
    try:
        if not existing_instance:
            from core.transfer_metrics import TransferMeter
            game_meter = TransferMeter()

            async def prepare_game():
                installed = await asyncio.to_thread(
                    install_game, game, str(directory), java, source, signal, report,
                    lambda value: event(dict(game_meter.feed(value), kind='download', content='game')))
                metadata = await asyncio.to_thread(resolved_metadata, base, installed)
                loader, _ = metadata_loader(metadata)
                if loader != expected_loader or (items and loader == 'vanilla'):
                    raise ValueError('加载器安装校验失败：房间需要 ' + expected_loader + '，实际安装为 ' + loader + '。不会启动原版游戏。')
                host_ready.set()
                return installed, metadata, loader

            game_task = asyncio.create_task(prepare_game())
            game_task.add_done_callback(lambda task: aborted.set() if task.cancelled() or task.exception() else None)
            # Start the game worker before scanning local content caches.
            await asyncio.sleep(0)
        mods = target / 'mods'
        mods.mkdir()
        for folder in ('resourcepacks', 'shaderpacks'):
            (target / folder).mkdir()
        contents = [('mods', item) for item in items] + [('resources', item) for item in resource_items]
        completed_bytes = 0
        total_bytes = sum(item['size'] for _, item in contents)
        progress_lock = threading.Lock()
        active_progress = [0] * len(contents)
        last_progress = [0.0] * len(contents)
        existing_root = (Path(existing_instance.get('game_directory') or base)
                         if existing_instance else None)
        existing_by_hash = {}
        if existing_root:
            for folder in ('mods', 'resourcepacks', 'shaderpacks'):
                existing_folder = existing_root / folder
                if not existing_folder.is_dir():
                    continue
                for candidate in existing_folder.iterdir():
                    if not candidate.is_file() or candidate.is_symlink():
                        continue
                    digest = hashlib.sha256()
                    with candidate.open('rb') as stream:
                        for block in iter(lambda: stream.read(1024 * 1024), b''):
                            digest.update(block)
                    existing_by_hash.setdefault(digest.hexdigest(), candidate)
        semaphore = asyncio.Semaphore(budget.workers)
        resource_failures = []
        from core.transfer_metrics import TransferMeter
        content_meter = TransferMeter()

        async def prepare_content(index, kind, item):
            nonlocal completed_bytes
            async with semaphore:
                if signal.is_set():
                    raise InterruptedError('安装已取消。')
                optional = kind == 'resources'
                label = '资源' if optional else '模组'
                status = f'下载{label} {index + 1}/{len(contents)} · ' + item['name']
                event(dict(kind='file', name=item['name'], state='downloading', size=item['size'],
                           content=kind, index=index + 1, count=len(contents)))

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
                    event(content_meter.feed(dict(kind='progress', name=item['name'], key=item.get('path', 'mods/' + item['name']),
                               state='cached' if source_name == 'cached' else 'downloading', done=done, total=item['size'],
                               content=kind, index=index + 1, count=len(contents))))

                final_path = (mods / item['name'] if kind == 'mods' else target / item['path'])
                final_path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    cached = existing_by_hash.get(item['sha256'])
                    if cached:
                        await asyncio.to_thread(shutil.copy2, cached, final_path)
                        source_progress_update('cached', item['size'], item['size'])
                    else:
                        await _download_room_mod(endpoint, item, base, final_path, content_source or source,
                                                 signal, source_progress_update, host_ready)
                    await asyncio.to_thread(_verify_mod, final_path, item, signal)
                except BaseException as exc:
                    event(dict(kind='file', name=item['name'],
                               state='skipped' if optional else 'failed', content=kind,
                               size=item['size'], error=str(exc)))
                    if optional and isinstance(exc, Exception) and not signal.is_set() and not isinstance(exc, InterruptedError):
                        final_path.unlink(missing_ok=True)
                        with progress_lock:
                            active_progress[index] = 0
                            completed_bytes += item['size']
                        resource_failures.append(item['name'])
                        return
                    aborted.set()
                    raise
                with progress_lock:
                    completed_bytes += item['size']
                    active_progress[index] = 0
                    completed = completed_bytes
                report(('资源已下载并校验：' if optional else '模组已下载并校验：') + item['name'],
                       completed, total_bytes)
                event(dict(kind='file', name=item['name'], state='verified', content=kind,
                           size=item['size'], sha256=item['sha256'], path=str(final_path)))
                content_meter.feed(dict(name=item['name'], key=item.get('path', 'mods/' + item['name']), state='verified', done=item['size']))
                if item.get('downloads'):
                    from core.content_records import record_content
                    await asyncio.to_thread(record_content, target, final_path, item['downloads'])

        tasks = [asyncio.create_task(prepare_content(index, kind, item))
                 for index, (kind, item) in enumerate(contents)]
        outcomes = await asyncio.gather(*tasks, return_exceptions=True)
        failures = [result for result in outcomes if isinstance(result, BaseException)]
        if failures:
            aborted.set()
        if game_task:
            try:
                installed, metadata, loader = await game_task
            except BaseException as game_error:
                content_error = next((failure for failure in failures if not isinstance(failure, InterruptedError)), None)
                if content_error and isinstance(game_error, (InterruptedError, DownloadCancelled)):
                    raise content_error
                raise
        if failures:
            raise next((failure for failure in failures if not isinstance(failure, InterruptedError)), failures[0])
        if signal.is_set():
            raise InterruptedError('安装已取消。')
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
                        'parent': installed, 'mods_hash': actual,
                        'resources_hash': (manifest_hash(resource_items)
                                           if resource_items and not resource_failures else '')})
        (target / (identity + '.json')).write_text(json.dumps(isolated, ensure_ascii=False, indent=2), encoding='utf8')
        receipt_path = base / 'versions' / game['version'] / '.buggcraft-complete.json'
        if receipt_path.is_file():
            receipt = json.loads(receipt_path.read_text(encoding='utf8'))
            receipt['version'] = identity
            receipt['files'].append({'path': str((published / (identity + '.json')).relative_to(base)),
                                    'sha1': hashlib.sha1((target / (identity + '.json')).read_bytes()).hexdigest()})
            (target / '.buggcraft-complete.json').write_text(json.dumps(receipt), encoding='utf8')
        published.parent.mkdir(parents=True, exist_ok=True)
        target.rename(published)
        (published / marker.name).unlink()
        event(dict(kind='complete', version=identity, loader=loader))
        report('游戏配置已准备完成', 1, 1)
        return identity
    except BaseException:
        aborted.set()
        if game_task:
            await asyncio.gather(game_task, return_exceptions=True)
        # Incomplete directory has no usable version JSON and is never selected.
        if target.exists():
            await asyncio.to_thread(shutil.rmtree, target)
        if (published / marker.name).exists():
            await asyncio.to_thread(shutil.rmtree, published)
        raise
