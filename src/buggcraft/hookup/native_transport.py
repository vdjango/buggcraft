"""Launcher-facing room API implemented by the native C++ bridge.

This module adapts Qt's existing endpoint lifecycle to bridge RPC. It contains
no socket, SSH, ICE, relay, compression, or game-packet forwarding code.
"""
import asyncio
import logging
import threading

from .native_routes import manager
from .profiles import RoomInvite

LOG = logging.getLogger(__name__)


class NativeEndpoint:
    def __init__(self, profile, invite=None, *, role, game_port=25565,
                 listen_port=0, room_settings=None, game_directory=None,
                 game_chat_enabled=False, game_chat_name=None,
                 transport_policy='auto', announce=True, on_status=None):
        if role not in ('host', 'client'):
            raise ValueError('Invalid native endpoint role')
        if transport_policy not in ('auto', 'relay'):
            raise ValueError('Invalid transport policy')
        self.profile = profile
        self.invite = invite or RoomInvite.create()
        self.role = role
        self.game_port = int(game_port)
        self.listen_port = int(listen_port or 0)
        self.room_settings = dict(room_settings or {})
        self.local_game = None
        self.game_directory = game_directory
        self.game_chat_enabled = bool(game_chat_enabled)
        self.game_chat_name = game_chat_name
        self.chat_name = 'Player'
        self.transport_policy = transport_policy
        self.announce = bool(announce)
        self.on_status = on_status
        self.on_chat = None
        self.bridge_status = 'Waiting for native bridge'
        self.room_info = {}
        self.room_state = 'connecting'
        # Kept as an endpoint lifecycle flag for existing Qt state code. It is
        # not a Python SSH connection and exposes no network stream methods.
        self.connection = None
        self.listener = False
        self.task = None
        self.session = None
        self._stopped = False
        self._routes = None
        self._transport = 'auto'

    @property
    def transport_state(self):
        return self._transport

    async def _emit(self, state, detail=''):
        self.room_state = state
        callback = self.on_status
        if callback:
            callback(state, detail)

    async def run(self):
        self._stopped = False
        self.task = asyncio.current_task()
        try:
            self._routes = manager()
            node = await self._routes.handle(self.profile)
            params = {'node': node, 'transport': self.transport_policy,
                      'compression': 'auto', 'announce': self.announce,
                      'chat_name': self.chat_name}
            if self.role == 'host':
                params.update(game_port=self.game_port, settings=self.room_settings,
                              game_directory=str(self.game_directory or ''),
                              game_chat_enabled=self.game_chat_enabled,
                              game_chat_name=self.game_chat_name or '')
                method = 'room.host'
            else:
                params.update(invite=self.invite.encode(), listen_port=self.listen_port)
                method = 'room.join'
            result = await self._routes.request(method, params)
            self.session = result['session']
            # Capture at connection time as well as export time; ICE and game
            # forwarding never wait for route, DNS or STUN diagnostics.
            from utils.diagnostics import connection_session_directory
            directory = connection_session_directory()
            if directory:
                from utils.network_diagnostics import capture_session_network
                probe = asyncio.create_task(asyncio.to_thread(
                    capture_session_network, directory, self.session))
                probe.add_done_callback(lambda task: task.exception() if not task.cancelled() else None)
            if self.role == 'host' and result.get('invite'):
                self.invite = RoomInvite.decode(result['invite'])
            address = result.get('address') or ''
            if ':' in address:
                self.listen_port = int(address.rsplit(':', 1)[1])
            self.room_info = dict(result.get('info') or {})
            self._set_transport(result.get('transport', 'relay'), force=True)
            self.bridge_status = 'Native bridge controls this room'
            self.connection = self
            self.listener = self.role == 'client'
            await self._emit('online', self.bridge_status)

            while not self._stopped and self.session:
                await asyncio.sleep(.5)
                try:
                    events = await self._routes.request(
                        'session.events', {'session': self.session})
                    for event in events.get('events', []):
                        self._apply_event(event)
                        if self.on_chat:
                            self.on_chat(event)
                    sessions = (await self._routes.request('session.list', {})).get('sessions', [])
                    current = next((item for item in sessions
                                    if item.get('session') == self.session), None)
                    if current is None or current.get('state') in ('stopped', 'error'):
                        detail = current.get('reason', 'Room disconnected') if current else 'Room disconnected'
                        await self._emit('closed', detail)
                        break
                    self._set_transport(current.get('transport', self._transport))
                    self.room_info.update(current.get('info') or {})
                    state = current.get('state', 'online')
                    if state != self.room_state:
                        await self._emit(state, current.get('reason', ''))
                except (OSError, ConnectionError, asyncio.TimeoutError, ValueError) as exc:
                    if not self._stopped:
                        await self._emit('error', '原生联机桥连接已中断，请重新加入房间。')
                        LOG.info('native_session_poll_failed reason=%s', type(exc).__name__)
                    break
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._emit('error', str(exc) or type(exc).__name__)
        finally:
            self.connection = None
            self.listener = False

    def _apply_event(self, event):
        if event.get('type') == 'members' and isinstance(event.get('snapshot'), dict):
            self.room_info['lobby'] = event['snapshot']
        elif event.get('type') == 'room':
            self.room_info.update(event)
            if event.get('state') in ('ready', 'waiting', 'closed'):
                self.room_info['availability'] = event['state']
            transport = event.get('transport')
            if transport:
                self._set_transport(transport, notify=False)
        elif event.get('type') == 'transport':
            self._set_transport(event.get('transport'), notify=False)
        elif event.get('type') == 'bridge':
            self.bridge_status = str(event.get('status', self.bridge_status))[:160]
        elif event.get('type') == 'latency':
            value = event.get('latency_ms')
            self.room_info['latency_ms'] = value if type(value) is int and 0 <= value <= 1000000 else None
            self.room_info['latency_state'] = event.get('state', 'unavailable')

    def _set_transport(self, transport, *, force=False, notify=True):
        if transport not in ('p2p', 'relay', 'auto'):
            return
        changed = transport != self._transport
        self._transport = transport
        if notify and self.on_chat and (changed or force):
            self.on_chat({'type': 'transport', 'transport': transport})

    async def stop(self):
        self._stopped = True
        session, self.session = self.session, None
        if self._routes and session:
            try:
                await self._routes.request('room.close', {'session': session})
            except (OSError, ConnectionError, asyncio.TimeoutError, ValueError):
                LOG.info('native_room_close_failed')
        self.connection = None
        self.listener = False

    async def send_chat(self, text):
        if not self.session or not self._routes:
            raise ConnectionError('Room is disconnected')
        return await self._routes.request('chat.send', {
            'session': self.session, 'text': text, 'name': self.chat_name})

    async def retarget_world(self, port):
        if not self.session or self.role != 'host':
            raise ValueError('Only an active host can change its world')
        current = dict(self.room_settings.get('game', {}))
        game = await self._routes.request('room.retarget', {
            'session': self.session, 'port': int(port), 'game': current})
        self.game_port = int(port)
        self.room_settings['game'] = game
        self.room_info['game'] = game
        return game

    async def update_game(self, game, game_directory=None):
        if self.role != 'host' or not self.session:
            raise ValueError('Only the active host can update the room version')
        if self.game_port:
            raise ValueError('游戏世界仍处于开放状态。请先关闭当前世界，再更改房间版本。')
        self.room_settings['game'] = dict(game)
        if game_directory:
            self.game_directory = game_directory
            await self._routes.request('mods.configure', {
                'session': self.session, 'directory': str(game_directory)})
        self.room_info = dict(await self._routes.request('room.configure', {
            'session': self.session, 'settings': self.room_settings}))
        return dict(game)

    async def update_settings(self, title, public, require_invite, allow_mod_transfer=False,
                              mod_transfer_limit_kib=512):
        lobby = self.room_info.get('lobby', {})
        if not self.session or (self.role != 'host' and lobby.get('self_id') != lobby.get('manager_id')):
            raise ValueError('只有在线房主可以修改房间设置。')
        if self.role != 'host':
            info = await self.lobby_request('configure', title=title, public=public,
                require_invite=not public or require_invite)
            self.room_info.update(info)
            return info
        settings = dict(self.room_settings, title=title, public=public,
                        require_invite=not public or require_invite,
                        allow_mod_transfer=bool(allow_mod_transfer),
                        mod_transfer_limit_kib=int(mod_transfer_limit_kib))
        info = dict(await self._routes.request('room.configure', {
            'session': self.session, 'settings': settings}))
        self.room_settings = settings
        self.room_info = info
        return info

    async def lobby_request(self, op, **fields):
        if not self.session or 'room-lobby-v1' not in self.room_info.get('capabilities', []):
            raise ValueError('当前节点需要升级，才能使用成员准备和管理功能。')
        return await self._routes.request('room.request', {
            'session': self.session, 'request': dict(op=op, **fields)})

    async def mod_manifest(self, kind='mods'):
        if kind not in ('mods', 'resources'):
            raise ValueError('Invalid room content kind')
        result = await self._routes.request('mods.manifest', {'session': self.session, 'kind': kind})
        return await self._wait_transfer(result)

    async def download_mod(self, item, target, cancel, progress):
        if self.transport_state != 'p2p':
            raise ConnectionError('当前未建立 P2P 直连，禁止从房主传输文件。请优先使用下载源。')
        deadline = asyncio.get_running_loop().time() + 45
        # The file PeerConnection is negotiated independently of the game
        # channel. A first RPC can therefore arrive while its ICE offer is
        # still gathering; retry that transient state so the public source
        # race can continue without exposing a P2P-specific failure.
        while True:
            if self.transport_state != 'p2p' or not self.session:
                raise ConnectionError('P2P 直连已断开，文件传输已停止。')
            if cancel is not None and cancel.is_set():
                raise InterruptedError('模组安装已取消。')
            try:
                result = await self._routes.request('mods.fetch', {
                    'session': self.session, 'item': dict(item), 'target': str(target),
                    'kind': 'resources' if item.get('path') else 'mods'})
                return await self._wait_transfer(result, cancel, progress)
            except ConnectionError as error:
                if 'P2P file channel is not connected' not in str(error):
                    raise
                if cancel is not None and cancel.is_set():
                    raise InterruptedError('模组安装已取消')
                if asyncio.get_running_loop().time() >= deadline:
                    raise ConnectionError('P2P 文件通道暂时不可用') from error
                await asyncio.sleep(.35)

    async def _wait_transfer(self, result, cancel=None, progress=None):
        transfer = result.get('transfer')
        try:
            while result.get('state') != 'complete':
                if progress is not None and self.transport_state != 'p2p':
                    raise ConnectionError('P2P 直连已断开，文件传输已停止。')
                if result.get('state') == 'error':
                    raise ConnectionError(result.get('error', 'Native transfer failed'))
                if cancel is not None and cancel.is_set():
                    raise InterruptedError('Mod installation cancelled')
                await asyncio.sleep(.1)
                result = await self._routes.request('mods.status', {
                    'session': self.session, 'transfer': transfer})
                if progress:
                    progress(result.get('received', 0), result.get('size', 0))
            if 'items' not in result:
                return result
            items = list(result['items'])
            total = result.get('total', len(items))
            if type(total) is not int or not 0 <= total <= 2000:
                raise ValueError('Native bridge returned an invalid manifest total')
            while len(items) < total:
                page = await self._routes.request('mods.status' if transfer else 'mods.manifest', {
                    'session': self.session, **({'transfer': transfer} if transfer else {}),
                    'offset': len(items)})
                if not page.get('items') or page.get('offset') != len(items) or page.get('total') != total:
                    raise ValueError('Native bridge returned an incomplete manifest page')
                items.extend(page['items'])
            if len(items) != total:
                raise ValueError('Native bridge returned an oversized manifest page')
            return items
        finally:
            if transfer:
                try:
                    await self._routes.request('mods.cancel', {
                        'session': self.session, 'transfer': transfer})
                except (OSError, ConnectionError, asyncio.TimeoutError, ValueError):
                    pass


class TunnelHost(NativeEndpoint):
    def __init__(self, profile, invite=None, **kwargs):
        super().__init__(profile, invite, role='host', **kwargs)


class TunnelClient(NativeEndpoint):
    def __init__(self, profile, invite, **kwargs):
        super().__init__(profile, invite, role='client', **kwargs)


class TunnelService:
    """Run bridge-control coroutines away from Qt's GUI event loop."""
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.endpoints = {}
        self._retiring = set()
        self.closed = False
        self._close_lock = threading.Lock()
        self.thread = threading.Thread(
            target=self.loop.run_forever, daemon=True, name='native-multiplayer')
        self.thread.start()

    def add(self, name, endpoint):
        if self.closed:
            raise RuntimeError('Multiplayer service is closed')
        if name in self.endpoints:
            raise ValueError('Room connection name already exists')
        self.endpoints[name] = endpoint
        future = asyncio.run_coroutine_threadsafe(endpoint.run(), self.loop)

        def completed(result):
            if not result.cancelled():
                try:
                    result.result()
                except Exception as exc:
                    if endpoint.on_status:
                        endpoint.on_status('error', str(exc) or type(exc).__name__)

        future.add_done_callback(completed)
        return future

    def submit(self, coroutine):
        if self.closed:
            coroutine.close()
            raise RuntimeError('Multiplayer service is closed')
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop)

    def remove(self, name):
        endpoint = self.endpoints.pop(name)
        self._retiring.add(endpoint)
        future = asyncio.run_coroutine_threadsafe(endpoint.stop(), self.loop)
        future.add_done_callback(lambda _: self._retiring.discard(endpoint))
        return future

    def close(self):
        async def shutdown():
            endpoints = tuple(dict.fromkeys((*self.endpoints.values(), *self._retiring)))
            await asyncio.gather(*(endpoint.stop() for endpoint in endpoints), return_exceptions=True)
            from .native_routes import close as close_native_routes
            await close_native_routes()
            pending = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            self.endpoints.clear()
            self._retiring.clear()

        with self._close_lock:
            if self.closed:
                return
            self.closed = True
            if not self.loop.is_closed():
                future = asyncio.run_coroutine_threadsafe(shutdown(), self.loop)
                try:
                    future.result(timeout=10)
                except TimeoutError:
                    LOG.error('native_multiplayer_shutdown_timeout')
                    future.cancel()
                finally:
                    self.loop.call_soon_threadsafe(self.loop.stop)
                    self.thread.join(timeout=3)
                    if not self.thread.is_alive():
                        self.loop.close()
