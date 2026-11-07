"""Prepare a separate game configuration without changing existing mod folders."""
import asyncio
import json
import logging
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


def _room_loader(metadata, game, installed):
    loader, build = metadata_loader(metadata)
    expected = game.get('loader', 'vanilla').lower()
    if loader != expected or game.get('mods_count') and loader == 'vanilla':
        logging.getLogger(__name__).warning('room_loader_validation_failed expected=%s expected_build=%s game=%s installed=%s actual=%s actual_build=%s',
            expected, game.get('loader_version',''), game.get('version',''), installed, loader, build)
        raise ValueError(f'加载器安装校验失败：房间需要 {expected}，实际配置 {installed} 为 {loader}。请重新准备房间客户端，或选择与房主一致的配置；不会使用其他加载器启动。')
    return loader


async def _wait_for_retry(attempt, signal):
    deadline = time.monotonic() + min(2 ** (attempt + 1), 15)
    while time.monotonic() < deadline and not signal.is_set():
        await asyncio.sleep(.1)


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


def _game_directory_path(directory):
    try:
        value = os.fspath(directory)
    except (TypeError, ValueError):
        value = None
    if not isinstance(value, str) or not value.strip():
        raise ValueError('游戏目录无效，请重新选择游戏目录。')
    return Path(value)


def _version_identity(identity):
    if (not isinstance(identity, str) or not identity or identity in ('.', '..') or
            '\x00' in identity or '/' in identity or '\\' in identity):
        raise ValueError('已安装游戏版本信息缺失或无效，请重新选择游戏实例。')
    return identity


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
    from utils.storage_paths import game_cache
    from utils.path_helper import filesystem_path
    from utils.payload_cache import FileLock
    import errno
    cache = filesystem_path(game_cache(base) / 'room-content' / item['sha256'])
    cache.mkdir(parents=True, exist_ok=True)
    # Different files and preparations may share the same verified bytes.
    # Serialize their cache writes without blocking the event loop or replacing
    # content that another worker is currently verifying/copying on Windows.
    while True:
        if cancel.is_set():
            raise InterruptedError('安装已取消。')
        try:
            lease = FileLock(cache / '.transfer.lock')
            break
        except OSError as exc:
            if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise
            await asyncio.sleep(.05)
    try:
        return await _download_room_mod_locked(endpoint, item, base, target, source,
                                                cancel, progress, host_ready, cache)
    finally:
        lease.close()


async def _download_room_mod_locked(endpoint, item, base, target, source, cancel,
                                    progress, host_ready, cache):
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
        origin = getattr(endpoint, '_content_cache', None)
        # The batch plan marks only verified copies as cached. Use those
        # immediately; a missing/expired copy returns False to ordinary sources.
        if origin and await origin.download(item, cached, cancel,
                lambda done, total: progress('origin', done, total)):
            await asyncio.to_thread(shutil.copy2, cached, target)
            return 'origin'
        try:
            public_key = (source, tuple(item.get('downloads', [])))
            found = False
            if item.get('_exhausted_public') != public_key:
                found = await fetch_public_mod(item, base, paths['public'], source, cancel,
                                               lambda done, total: progress('public', done, total))
                if not found:
                    item['_exhausted_public'] = public_key
            if found:
                await asyncio.to_thread(_verify_mod, paths['public'], item, cancel)
                winner = 'public'
        except InterruptedError:
            raise
        except ValueError:
            # A corrupt public copy is treated as an unavailable source. The
            # independent direct download must pass the same verification.
            cached.unlink(missing_ok=True)
        if not winner:
            origin = getattr(endpoint, '_content_cache', None)
            if origin and await origin.download(item, cached, cancel,
                    lambda done, total: progress('origin', done, total)):
                winner = 'origin'
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
            last_error = None
            if getattr(endpoint, 'transport_state', None) == 'p2p':
                try:
                    transfer_item = {key: value for key, value in item.items() if not key.startswith('_')}
                    await fetch_mod(endpoint, transfer_item, paths['p2p'], cancel,
                                    lambda done, total: progress('p2p', done, total))
                    await asyncio.to_thread(_verify_mod, paths['p2p'], item, cancel)
                    winner = 'p2p'
                except InterruptedError:
                    raise
                except (ConnectionError, OSError, ValueError) as exc:
                    last_error = exc
            if not winner:
                detail = str(last_error) if last_error else '未建立 P2P 房主传输，且源站尚无所需文件'
                raise ConnectionError('所选下载源、Buggcraft 源站和房主文件暂不可用（' + detail + '），等待补齐；房间连接和已完成文件会保留。') from last_error
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
    root = _game_directory_path(directory)
    identity = _version_identity(identity)
    seen = set() if seen is None else seen
    if identity in seen:
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
    """Use the host's hash-checked public metadata; never auto-probe Modrinth."""
    from requests import RequestException
    from core.downloads import DownloadSourcesExhausted
    if not item.get('sha1'):
        return False
    try:
        from .room_cache import public_url
        from core.client_file_source import mapped_url
        content_source = source if isinstance(source, (list, tuple)) or source in ('自动测速', '自动（CurseForge 优先）', 'CurseForge', 'Modrinth', 'MCIM', 'Buggcraft', '官方') else 'CurseForge'
        urls = list(dict.fromkeys([*(url for url in item.get('_accelerated_downloads', []) if mapped_url(url)),
            *(url for url in item.get('downloads', []) if public_url(url))]))
        if not urls:
            return False
        url = urls[0]
        from core.downloads import MinecraftDownloader
        relative = target.name
        downloader = MinecraftDownloader(target.parent, source=source if isinstance(source, str) else '自动', cancel=cancel, workers=1, retries=6)
        downloader.parallel_content = False  # Room files already share a bounded pool.
        downloader.resolve_content_sources = True
        downloader.content_source = content_source
        downloader.file_mirrors = {url: urls[1:]}
        await asyncio.to_thread(downloader.fetch, url, relative, item['sha1'], item['size'],
                                file_progress=progress)
        return True
    except (RequestException, DownloadSourcesExhausted, ValueError):
        if cancel.is_set():
            raise InterruptedError('安装已取消。')
        return False


async def prepare_configuration(endpoint, directory, java, source, cancel, report, event=None,
                                existing_instance=None, content_source=None, resume=None):
    from core.downloads import use_download_budget
    with use_download_budget() as budget:
        return await _prepare_configuration(endpoint, directory, java, source, cancel, report, event,
                                            existing_instance, content_source, budget, resume)


async def _prepare_configuration(endpoint, directory, java, source, cancel, report, event=None,
                                 existing_instance=None, content_source=None, budget=None, resume=None):
    from core.downloads import DownloadCancelled
    event = event or (lambda value: None)
    base = _game_directory_path(directory).resolve()
    installed = None
    if existing_instance is not None:
        if not isinstance(existing_instance, dict):
            raise ValueError('所选游戏实例信息无效，请重新选择游戏实例。')
        installed = _version_identity(existing_instance.get('version'))
    game = dict((endpoint.room_info or {}).get('game') or {})
    if not isinstance(game.get('version'), str) or not game['version'].strip():
        raise ValueError('房间游戏版本信息缺失，请房主重新创建房间。')
    count = game.get('mods_count', len(game.get('mods', [])))
    # Fetch and validate before creating a new configuration. No arbitrary URLs
    # or executable paths from a peer are used by the installer.
    try:
        items = [dict(item) for item in await fetch_manifest(endpoint)] if count else []
    except ConnectionError as exc:
        raise ConnectionError('房主文件清单获取失败：' + str(exc)) from exc
    resource_items = []
    resource_count = game.get('resources_count', len(game.get('resources', [])))
    if resource_count:
        # Resource packs and shaders are optional presentation assets. A
        # missing mirror or host file is reported, but does not block joining.
        try:
            resource_items = [dict(item) for item in await fetch_manifest(endpoint, 'resources')]
        except Exception as exc:
            event(dict(kind='resources', state='skipped', reason=str(exc)))
    game['mods_count'] = len(items)
    game['resources_count'] = len(resource_items)
    from .room_cache import client as room_cache_client, PendingRoomFiles
    origin = await room_cache_client(endpoint)
    event(dict(kind='manifest', files=items, resources=resource_items))
    if cancel.is_set():
        raise InterruptedError('安装已取消。')
    expected_loader = game.get('loader', 'vanilla').lower()
    host_ready = asyncio.Event()
    if existing_instance:
        metadata = await asyncio.to_thread(resolved_metadata, base, installed)
        installed_loader = _room_loader(metadata, game, installed)
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
    from utils.storage_paths import game_cache
    target = game_cache(base) / 'room-preparation' / identity
    target.mkdir(parents=True, exist_ok=False)
    marker = target / '.buggcraft-preparing'
    marker.write_text('Room preparation in progress', encoding='utf8')
    async def refresh_origin(**fields):
        from requests import RequestException
        try:
            await asyncio.wait_for(origin.plan(**fields, timeout=(1, 2)), timeout=3)
            origin.enrich([*items, *resource_items])
        except (ConnectionError, OSError, ValueError, RequestException, asyncio.TimeoutError):
            pass  # Optional acceleration never holds up ordinary downloads.
    origin_task = None
    try:
        if origin:
            origin_task = asyncio.create_task(refresh_origin(
                wanted=[item['sha256'] for item in [*items, *resource_items]]))
        if not existing_instance:
            from core.transfer_metrics import TransferMeter
            game_meter = TransferMeter()

            async def prepare_game():
                try:
                    installed = await asyncio.to_thread(
                        install_game, game, str(directory), java, source, signal, report,
                        lambda value: event(dict(game_meter.feed(value), kind='download', content='game')))
                except (InterruptedError, DownloadCancelled):
                    raise
                except Exception as exc:
                    prefix = '加载器安装失败：' if expected_loader != 'vanilla' else '游戏下载失败：'
                    if isinstance(exc, ValueError):
                        raise ValueError(prefix + str(exc)) from exc
                    raise RuntimeError(prefix + str(exc)) from exc
                metadata = await asyncio.to_thread(resolved_metadata, base, installed)
                loader = _room_loader(metadata, game, installed)
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
                        selected_source = content_source() if callable(content_source) else content_source or source
                        await _download_room_mod(endpoint, item, base, final_path, selected_source,
                                                 signal, source_progress_update, host_ready)
                    await asyncio.to_thread(_verify_mod, final_path, item, signal)
                except BaseException as exc:
                    item['_download_error'] = str(exc)
                    from requests import RequestException
                    from core.downloads import DownloadSourcesExhausted
                    retryable = isinstance(exc, (ConnectionError, RequestException, DownloadSourcesExhausted))
                    event(dict(kind='file', name=item['name'],
                               state='skipped' if optional else 'waiting' if retryable else 'failed', content=kind,
                               size=item['size'], error=str(exc)))
                    if optional and isinstance(exc, Exception) and not signal.is_set() and not isinstance(exc, InterruptedError):
                        final_path.unlink(missing_ok=True)
                        with progress_lock:
                            active_progress[index] = 0
                            completed_bytes += item['size']
                        resource_failures.append(item['name'])
                        return
                    if isinstance(exc, InterruptedError):
                        raise
                    if retryable and not optional:
                        with progress_lock:
                            active_progress[index] = 0
                        raise ConnectionError('文件暂未就绪（' + item['name'] + '）：' + str(exc)) from exc
                    aborted.set()
                    if not optional:
                        message = '模组下载失败（' + item['name'] + '）：' + str(exc)
                        if isinstance(exc, ValueError):
                            raise ValueError(message) from exc
                        if isinstance(exc, (ConnectionError, OSError)):
                            raise ConnectionError(message) from exc
                        raise RuntimeError(message) from exc
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

        # Complete independent files first. A missing required file must not
        # cancel successful transfers or the parallel game installation.
        pending = list(enumerate(contents))
        failures = []
        attempt = 0
        while pending:
            tasks = [asyncio.create_task(prepare_content(index, kind, item))
                     for index, (kind, item) in pending]
            outcomes = await asyncio.gather(*tasks, return_exceptions=True)
            failures = [result for result in outcomes if isinstance(result, BaseException)]
            if not failures or signal.is_set():
                break
            from requests import RequestException
            from core.downloads import DownloadSourcesExhausted
            recoverable = (ConnectionError, RequestException, DownloadSourcesExhausted)
            fatal = next((error for error in failures if not isinstance(error, recoverable)), None)
            if fatal:
                aborted.set()
                raise fatal
            pending = [entry for entry, outcome in zip(pending, outcomes) if isinstance(outcome, BaseException)]
            waiting = [item for _, (_, item) in pending]
            event(dict(kind='pending', files=waiting, attempt=attempt, state='waiting',
                       completed=len(contents) - len(waiting), total=len(contents), manual=attempt == 6))
            if attempt == 6:
                if resume is None:
                    raise PendingRoomFiles(waiting)
                report(f'已完成 {len(contents) - len(waiting)}/{len(contents)}，正在补齐 {len(waiting)} 个；请点击“继续补齐”', completed_bytes, total_bytes)
                while not resume.is_set() and not signal.is_set():
                    await asyncio.sleep(.1)
                if signal.is_set():
                    if game_task and game_task.done():
                        await game_task
                    raise InterruptedError('安装已取消。')
                resume.clear()
                # A deliberate resume starts a fresh budget only for these files.
                for item in waiting:
                    item.pop('_exhausted_public', None)
                event(dict(kind='resumed', completed=len(contents) - len(waiting), total=len(contents)))
                attempt = -1
            report(f'等待补齐 {len(waiting)} 个必需文件 · 自动重试 {attempt + 1}/6；已完成文件已保留', completed_bytes, total_bytes)
            if origin:
                await refresh_origin(failed=[item['sha256'] for item in waiting])
            # Cancellation stays responsive while the provider fills the plan.
            if attempt >= 0:
                await _wait_for_retry(attempt, signal)
            if origin:
                await refresh_origin()
            attempt += 1
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
        # A room is a standalone version for this launcher and for PCL/HMCL.
        # Give it its own client JAR and natives instead of leaving an alias
        # whose version JSON points at another version folder.
        from core.launch_preparation import exclude_version_jar_from_bootstrap_scan, version_chain
        chain = version_chain(base, installed)
        jar_owner = next((layer.get('jar') for _, layer in chain if layer.get('jar')), None)
        if jar_owner is None:
            jar_owner = next((name for name, _ in chain if
                              (base / 'versions' / name / (name + '.jar')).is_file()), None)
        if (not isinstance(jar_owner, str) or jar_owner in ('.', '..') or
                any(char in jar_owner for char in ('/', chr(92), ':'))):
            raise ValueError('加载器安装失败：找不到可用的游戏核心文件。')
        core = base / 'versions' / jar_owner / (jar_owner + '.jar')
        if not core.is_file():
            raise FileNotFoundError('加载器安装失败：缺少游戏核心文件 ' + str(core))
        shutil.copy2(core, target / (identity + '.jar'))
        for name, _ in reversed(chain):
            natives = base / 'versions' / name / 'natives'
            if natives.is_dir():
                shutil.copytree(natives, target / 'natives', dirs_exist_ok=True)
        # Libraries and assets remain shared beneath .minecraft, as in a
        # conventional standalone Minecraft version.
        isolated = dict(metadata, id=identity, buggcraftRoom={'version': game['version'],
                        'parent': installed, 'mods_hash': actual,
                        'resources_hash': (manifest_hash(resource_items)
                                           if resource_items and not resource_failures else '')})
        isolated.pop('inheritsFrom', None)
        isolated.pop('jar', None)
        exclude_version_jar_from_bootstrap_scan(isolated, identity)
        (target / (identity + '.json')).write_text(json.dumps(isolated, ensure_ascii=False, indent=2), encoding='utf8')
        receipt_path = base / 'versions' / game['version'] / '.buggcraft-complete.json'
        if receipt_path.is_file():
            receipt = json.loads(receipt_path.read_text(encoding='utf8'))
            receipt['version'] = identity
            receipt['files'].append({'path': str((published / (identity + '.json')).relative_to(base)),
                                    'sha1': hashlib.sha1((target / (identity + '.json')).read_bytes()).hexdigest()})
            receipt['files'].append({'path': str((published / (identity + '.jar')).relative_to(base)),
                                    'sha1': hashlib.sha1((target / (identity + '.jar')).read_bytes()).hexdigest()})
            (target / '.buggcraft-complete.json').write_text(json.dumps(receipt), encoding='utf8')
        published.parent.mkdir(parents=True, exist_ok=True)
        from utils.storage_paths import publish_directory
        publish_directory(target, published)
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
    finally:
        if origin_task:
            origin_task.cancel()
            await asyncio.gather(origin_task, return_exceptions=True)
