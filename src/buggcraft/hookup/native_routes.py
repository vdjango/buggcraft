"""Lifecycle and bounded JSON-RPC transport for the native multiplayer bridge.

The bridge is the only launcher networking implementation. This module loads
the library or starts its process, sends control requests and forwards events.
"""
import asyncio
import hashlib
import json
import logging
import os
from pathlib import Path
import sys
import time
import weakref
from .native_library import library_path, load_library

LOG = logging.getLogger(__name__)
_managers = weakref.WeakKeyDictionary()


class BridgeError(ConnectionError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def startup_error(exc, component):
    """Report loader failures without guessing that Windows blocked the bridge."""
    code = getattr(exc, 'winerror', None) or getattr(exc, 'errno', None)
    LOG.warning('native_bridge_start_failed component=%s reason=%s code=%s',
                component, type(exc).__name__, code)
    if code in (577, 4551):
        message = 'Windows 应用控制阻止了原生联机组件，请查看 Windows 安全中心的拦截记录。'
    elif code == 193:
        message = '原生联机组件架构不匹配或文件损坏，请安装与系统匹配的完整运行包。'
    elif code == 5:
        message = '原生联机组件访问被拒绝，请检查文件权限和系统安全记录。'
    elif isinstance(exc, FileNotFoundError) or code == 126:
        message = '原生联机运行库不完整或依赖库缺失，请重新安装完整 native 目录。'
    else:
        message = '原生联机组件加载或初始化失败，请导出联机诊断日志。'
    return ConnectionError(message)


def executable():
    configured = os.environ.get('BUGGCRAFT_BRIDGE_EXECUTABLE')
    if configured:
        return str(Path(configured).resolve())
    name = 'buggcraft-bridge.exe' if os.name == 'nt' else 'buggcraft-bridge'
    for root in (Path(__file__).resolve().parent.parent, Path(sys.executable).resolve().parent):
        candidate = root / 'native' / 'bin' / name
        if candidate.is_file():
            return str(candidate)
    # A source checkout uses the adjacent native build. Packaged launchers must
    # ship a complete CMake install tree and never search arbitrary PATH entries.
    source = next((parent for parent in Path(__file__).resolve().parents
                   if (parent / 'build.py').is_file() and (parent / 'src/buggcraft').is_dir()), None)
    native = source.parent / 'minecraft-tunnel-native' if source else None
    if native and (native / 'CMakeLists.txt').is_file():
        for folder in ('runtime/bin', 'build/Release', 'build'):
            candidate = native / folder / name
            if candidate.is_file():
                return str(candidate)
    return None


class NativeRoutes:
    def __init__(self):
        self.process = None
        self.library = None
        self.stderr = None
        self.handles = {}
        self.callbacks = {}
        self.cached = {}
        self.serial = 0
        self.lock = asyncio.Lock()
        self.request_lock = asyncio.Lock()
        self.start_lock = asyncio.Lock()

    async def _drain_stderr(self, process):
        try:
            while await process.stderr.readline():
                # Player-scoped diagnostics are written by the native process.
                pass
        except (asyncio.CancelledError, OSError, ValueError):
            return

    async def close(self):
        library, self.library = self.library, None
        process, self.process = self.process, None
        self.handles.clear()
        self.cached.clear()
        self.callbacks.clear()
        if library is not None:
            await asyncio.to_thread(library.close)
        if process is not None and process.returncode is None:
            try:
                process.stdin.close()
            except (BrokenPipeError, OSError, ValueError):
                pass
            try:
                await asyncio.wait_for(process.wait(), 2)
            except (asyncio.TimeoutError, TimeoutError):
                process.kill()
                await process.wait()
        if self.stderr is not None:
            self.stderr.cancel()
            await asyncio.gather(self.stderr, return_exceptions=True)
            self.stderr = None

    async def _request(self, method, params):
        async with self.request_lock:
            process = self.process
            if self.library is None and (process is None or process.returncode is not None):
                raise ConnectionError('Native multiplayer bridge is not running')
            self.serial += 1
            serial = self.serial
            message = {'jsonrpc': '2.0', 'id': serial, 'method': method, 'params': params}
            payload = (json.dumps(message, separators=(',', ':')) + '\n').encode('utf-8')
            if len(payload) > 8192:
                raise ValueError('Native bridge request exceeds the 8192-byte limit')
            try:
                async with asyncio.timeout(45):
                    if self.library is not None:
                        raw = await asyncio.to_thread(self.library.exchange, payload)
                    else:
                        process.stdin.write(payload)
                        await process.stdin.drain()
                        raw = await process.stdout.readline()
            except BaseException:
                # A timed-out response cannot become the next request's reply.
                await self.close()
                raise
            if not raw or len(raw) > 65536:
                await self.close()
                raise ConnectionError('Native bridge returned an invalid response')
            try:
                response = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                await self.close()
                raise ConnectionError('Native bridge returned invalid JSON') from exc
            if not isinstance(response, dict) or response.get('id') != serial:
                await self.close()
                raise ConnectionError('Native bridge response id did not match the request')
            if 'error' in response:
                error = response.get('error') or {}
                raise BridgeError(error.get('code', -32000), error.get('message', 'Native request failed'))
            if 'result' not in response:
                await self.close()
                raise ConnectionError('Native bridge response has no result')
            return response['result']

    async def ensure(self):
        async with self.start_lock:
            if self.library is None and (self.process is None or self.process.returncode is not None):
                await self._start()

    async def _start(self):
        await self.close()
        mode = os.environ.get('BUGGCRAFT_BRIDGE_MODE', 'auto')
        if mode not in ('auto', 'library', 'process'):
            raise ValueError('BUGGCRAFT_BRIDGE_MODE must be auto, library or process')
        # An explicitly configured process remains useful for isolation and tests.
        path = library_path() if mode != 'process' and not (
            mode == 'auto' and os.environ.get('BUGGCRAFT_BRIDGE_EXECUTABLE')) else None
        if path is not None:
            loading = asyncio.create_task(asyncio.to_thread(load_library, path))
            try:
                self.library = await asyncio.shield(loading)
            except asyncio.CancelledError:
                try:
                    library = await loading
                    await asyncio.to_thread(library.close)
                except Exception:
                    pass
                raise
            except (OSError, RuntimeError) as exc:
                raise startup_error(exc, 'library') from exc
        else:
            if mode == 'library':
                raise FileNotFoundError('未找到 C++ 联机动态库，请安装完整 native 目录。')
            binary = executable()
            if binary is None:
                raise FileNotFoundError('未找到 C++ 联机桥，请安装包含 native 的完整启动器。')
            options = {'creationflags': 0x08000000} if os.name == 'nt' else {}
            try:
                self.process = await asyncio.create_subprocess_exec(
                    binary, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE, limit=65536, **options)
            except OSError as exc:
                raise startup_error(exc, 'process') from exc
            self.stderr = asyncio.create_task(self._drain_stderr(self.process))
        try:
            initialized = await self._request('bridge.initialize', {'protocol': 1})
            methods = set(initialized.get('methods', []))
            required = {'node.add', 'node.selected', 'node.request', 'room.host',
                        'room.join', 'room.close', 'room.configure', 'room.retarget',
                        'game.status', 'game.discover', 'session.events', 'session.list',
                        'mods.manifest', 'mods.fetch', 'mods.status', 'mods.cancel', 'social.operate'}
            if not required <= methods:
                raise ConnectionError('原生联机桥版本过旧，请更新完整启动器。')
        except BaseException:
            await self.close()
            raise

    async def handle(self, profile):
        from .nodes import candidates, encode_code, profile_data

        key = hashlib.sha256(json.dumps(profile_data(profile), sort_keys=True).encode()).digest()
        await self.ensure()
        async with self.lock:
            existing = self.handles.get(key)
            if existing is not None:
                self.callbacks[existing] = getattr(profile, '_route_notice', None)
            if key not in self.handles:
                if len(self.handles) >= 16:
                    raise ConnectionError('Native bridge node limit reached; close an unused node')
                params = {'code': encode_code(profile), 'alternatives': []}
                for item in candidates(profile)[1:6]:
                    alternatives = params['alternatives'] + [profile_data(item)]
                    proposal = {'code': params['code'], 'alternatives': alternatives}
                    if len(json.dumps(proposal, separators=(',', ':')).encode()) > 7800:
                        break
                    params = proposal
                result = await self._request('node.add', params)
                handle = result['node']
                self.handles[key] = handle
                self.callbacks[handle] = getattr(profile, '_route_notice', None)
            return self.handles[key]

    async def request(self, method, params):
        await self.ensure()
        return await self._request(method, params)

    async def operation(self, profile, request):
        return await self._request('node.request', {
            'node': await self.handle(profile), 'request': request})

    async def choose(self, profile):
        from .nodes import profile_data, remember
        from .profiles import RelayProfile

        key = hashlib.sha256(json.dumps(profile_data(profile), sort_keys=True).encode()).digest()
        try:
            handle = await self.handle(profile)
            cached = self.cached.get(key)
            if cached is not None and time.monotonic() - cached[0] < 25:
                return cached[1]
            selected = await self._request('node.selected', {'node': handle})
            ordered = [RelayProfile(**selected['profile'])]
            for value in selected.get('backups', []):
                candidate = RelayProfile(**value)
                if candidate not in ordered:
                    ordered.append(candidate)
            # Persist a successful native refresh for the next launcher run.
            # A local write failure must not tear down an otherwise valid route.
            try:
                remember(profile, [profile_data(item) for item in ordered])
            except OSError:
                LOG.warning('native_route_cache_write_failed')
            self.cached[key] = (time.monotonic(), ordered)
            events = await self._request('bridge.events', {})
            for event in events.get('events', []):
                callback = self.callbacks.get(event.get('node'))
                name = event.get('to')
                if event.get('type') == 'node_route_changed' and isinstance(name, str):
                    LOG.info('native_route_changed reason=%s', event.get('reason', ''))
                    if callback:
                        callback(''.join(char for char in name if char.isprintable())[:80])
            return ordered
        except asyncio.CancelledError:
            await self.close()
            raise
        except (OSError, ValueError, TypeError, KeyError, ConnectionError,
                TimeoutError, asyncio.LimitOverrunError) as exc:
            LOG.warning('native_bridge_error reason=%s', type(exc).__name__)
            await self.close()
            if isinstance(exc, ConnectionError) and not isinstance(exc, BridgeError):
                raise
            if isinstance(exc, FileNotFoundError):
                raise ConnectionError('未找到完整的 C++ 联机运行库，请重新安装启动器。') from exc
            raise ConnectionError('C++ 联机桥请求失败，请查看联机诊断日志。') from exc

    async def failed(self, original, target):
        from .nodes import profile_data

        key = hashlib.sha256(json.dumps(profile_data(original), sort_keys=True).encode()).digest()
        self.cached.pop(key, None)
        handle = self.handles.get(key)
        if handle is not None and (self.library is not None or self.process is not None and self.process.returncode is None):
            await self._request('node.failed', {
                'node': handle, 'profile': profile_data(target)})

    async def close_handle(self, profile):
        from .nodes import profile_data

        key = hashlib.sha256(json.dumps(profile_data(profile), sort_keys=True).encode()).digest()
        handle = self.handles.get(key)
        if handle is not None and (self.library is not None or self.process is not None and self.process.returncode is None):
            await self._request('node.remove', {'node': handle})
            self.handles.pop(key, None)
            self.cached.pop(key, None)
            self.callbacks.pop(handle, None)


def manager():
    loop = asyncio.get_running_loop()
    instance = _managers.get(loop)
    if instance is None:
        instance = NativeRoutes()
        _managers[loop] = instance
    return instance


async def ordered(profile):
    return await manager().choose(profile)


async def failed(original, target):
    await manager().failed(original, target)


async def close():
    instance = _managers.pop(asyncio.get_running_loop(), None)
    if instance is not None:
        await instance.close()
