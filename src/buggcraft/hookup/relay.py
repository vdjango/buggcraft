"""Python room SDK. AsyncSSH owns encryption, channel framing and flow control."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import hashlib
import json
import logging
from pathlib import Path
import secrets
import threading

import asyncssh
from .rooms import request, compatibility, LanAnnouncer, validate_room, game_status, connect_directory

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class RelayProfile:
    server_host: str
    server_port: int
    token: str = field(repr=False)
    server_public_key: str
    _source: str = field(default='', init=False, repr=False, compare=False)
    _nodes: tuple = field(default=(), init=False, repr=False, compare=False)

    def __post_init__(self):
        if (not isinstance(self.server_host, str) or not self.server_host.strip() or len(self.server_host) > 253
                or any(c.isspace() or c in '/\\@?#' for c in self.server_host)):
            raise ValueError('Invalid relay address')
        if type(self.server_port) is not int or not 1 <= self.server_port <= 65535:
            raise ValueError('Invalid relay port')
        if not isinstance(self.token, str) or not 32 <= len(self.token) <= 2048:
            raise ValueError('Invalid relay service token')
        asyncssh.import_public_key(self.server_public_key)

    @classmethod
    def load(cls, path):
        path = Path(path).resolve()
        if path.stat().st_size > 8192:
            raise ValueError('节点配置超过大小限制')
        profile = cls(**json.loads(path.read_text(encoding="utf-8")))
        object.__setattr__(profile, '_source', str(path))
        return profile

    def known_hosts(self):
        # A pinned host key is mandatory; never use known_hosts=None.
        key = asyncssh.import_public_key(self.server_public_key)
        return ([key], [], [])


@dataclass(frozen=True)
class RoomInvite:
    secret: str = field(repr=False)

    def __post_init__(self):
        if not isinstance(self.secret, str) or not 32 <= len(self.secret) <= 128:
            raise ValueError("Invalid room invitation")
        if any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for ch in self.secret):
            raise ValueError("Invalid room invitation")

    @property
    def room_id(self):
        return hashlib.sha256(self.secret.encode("ascii")).hexdigest()[:32]

    @classmethod
    def create(cls):
        return cls(secrets.token_urlsafe(32))

    def encode(self):
        return "bugg1-" + self.secret

    @classmethod
    def decode(cls, value):
        value = value.strip()
        if not value.startswith("bugg1-"):
            raise ValueError("Invalid room invitation")
        return cls(value[6:])


class TunnelEndpoint:
    def __init__(self, profile: RelayProfile, invite: RoomInvite, *, role,
                 game_host="127.0.0.1", game_port=25565, listen_port=25566, on_status=None,
                 room_settings=None, local_game=None, announce=True, game_directory=None,
                 game_chat_enabled=False, game_chat_name=None, transport_policy='auto', peer_timeout=4):
        if role not in ("host", "client"):
            raise ValueError("Invalid role")
        if not (0 if role == 'host' else 1) <= int(game_port) <= 65535 or not 0 <= int(listen_port) <= 65535:
            raise ValueError("Invalid port")
        self.profile, self.invite, self.role = profile, invite, role
        self._active_profile = profile
        self.game_host, self.game_port = game_host, int(game_port)
        self.listen_port = int(listen_port)
        self.on_status = on_status or (lambda state, detail: None)
        self.connection = self.listener = self.task = None
        self.cleaning_up = False
        self._stopped = False
        self._stop_task = None
        self._has_connected = False
        self.room_settings, self.local_game = room_settings, local_game
        self.announce = announce
        self.room_info = None
        self.announcement = None
        self.chat_process = None
        self.chat_task = None
        self.chat_pending = {}
        self.chat_name = "玩家"
        if type(game_chat_enabled) is not bool:
            raise ValueError('游戏聊天同步开关必须为布尔值。')
        self.game_chat_enabled = game_chat_enabled
        self.game_chat_name = None
        if game_chat_enabled:
            from .chat_validation import bridge_player_name
            self.game_chat_name = bridge_player_name(
                game_chat_name if game_chat_name is not None else 'BuggChat' + secrets.token_hex(4))
        self.on_chat = lambda event: None
        self.bridge = self.bridge_task = None
        self.bridge_queue = asyncio.Queue(maxsize=100)
        self.bridge_sender = None
        self.bridge_status = ('等待房主连接游戏聊天' if game_chat_enabled else
                              '游戏聊天同步未开启，仅在大厅内聊天。')
        self.room_task = None
        self.room_state = 'ready'
        self.stop_reason = '联机已停止'
        self.recovery_started = None
        self.game_directory = game_directory
        self.pack_server = self.pack_listener = None
        self.pack_port = 0
        self.world_lock = asyncio.Lock()
        if transport_policy not in ('auto', 'relay') or not 0 < peer_timeout <= 10:
            raise ValueError('Invalid transport policy or timeout')
        self.transport_policy, self.peer_timeout = transport_policy, peer_timeout
        self.peer_transport = None
        self.diagnostic_trace = secrets.token_hex(8)

    @property
    def transport_state(self):
        peer = self.peer_transport
        if self.role == 'host':
            return 'auto' if peer and not peer.closed else 'relay'
        return 'p2p' if peer and peer.connected.is_set() else 'relay'

    async def _start_peer(self, connection):
        if self.transport_policy == 'relay':
            LOG.info('transport_policy role=%s policy=relay peer_negotiation=skipped', self.role)
            return
        LOG.info('transport_policy role=%s policy=auto peer_timeout=%s', self.role, self.peer_timeout)
        try:
            from . import _rtc  # Fall back to encrypted SSH if a dependency is unavailable.
            from .peer import PeerTransport
            self.peer_transport = PeerTransport(self)
            await asyncio.wait_for(self.peer_transport.start(connection), self.peer_timeout)
        except (ImportError, OSError, ValueError, asyncssh.Error, asyncio.TimeoutError):
            LOG.warning('peer_fallback role=%s path=ssh-relay', self.role, exc_info=True)
            if self.peer_transport:
                await self.peer_transport.close()
                self.peer_transport = None
            LOG.info('peer_fallback_complete role=%s path=ssh-relay', self.role)

    def room_event(self, event):
        state = event.get('state')
        if state not in ('ready', 'waiting', 'closed'):
            return
        self.room_state = state
        self.on_chat(event)
        if state == 'closed':
            self.stop_reason = str(event.get('reason') or '房主已结束联机，房间已关闭。')
            self._stopped = True
            self.on_status('closed', self.stop_reason)
            if self.connection:
                if self.room_task and self.room_task is not asyncio.current_task():
                    self.room_task.cancel()
                self.connection.close()

    async def _room_loop(self, connection):
        """World availability is independent of chat protocol support."""
        while not self._stopped and not connection.is_closed():
            try:
                if self.role == 'host':
                    async with self.world_lock:
                        try:
                            if not self.game_port:
                                raise ConnectionError('World not open')
                            _, writer = await asyncio.wait_for(asyncio.open_connection(
                                self.game_host, self.game_port), 1.5)
                            writer.close()
                            await writer.wait_closed()
                            available = True
                        except (OSError, asyncio.TimeoutError):
                            available = False
                        control_started = asyncio.get_running_loop().time()
                        info = await request(connection, 'availability', available=available)
                else:
                    control_started = asyncio.get_running_loop().time()
                    info = await request(connection, 'describe')
                    self.room_info = info
                control_rtt_ms = (asyncio.get_running_loop().time() - control_started) * 1000
                diagnostics_enabled = info.get('diagnostics', False)
                latency = None
                status = None
                if info.get('availability', 'ready') == 'ready':
                    try:
                        status = await game_status(self.game_port if self.role == 'host' else self.listen_port, timeout=2)
                        latency = status.get('latency_ms') if self.role != 'host' else None
                    except (OSError, ValueError, asyncio.TimeoutError, asyncio.IncompleteReadError):
                        pass
                if self.role == 'host':
                    players = status.get('players', {}) if status else {}
                    count, maximum = players.get('online'), players.get('max')
                    if type(count) is int and count >= 0:
                        count = max(0, count - int(bool(self.bridge and self.bridge.ready)))
                    else:
                        count = None
                    try:
                        info = await request(connection, 'presence', players=count,
                                             maximum=maximum if type(maximum) is int and maximum >= 0 else None)
                    except (OSError, asyncssh.Error, ValueError):
                        pass  # Compatible with older nodes lacking presence reports.
                if diagnostics_enabled:
                    try:
                        await request(connection, 'diagnostics', report={
                            'control_rtt_ms': control_rtt_ms, 'game_rtt_ms': latency,
                            'path': self.transport_state})
                    except (OSError, asyncssh.Error, ValueError):
                        pass  # Diagnostics must never interrupt a game session.
                state = info.get('availability', 'ready')
                game = info.get('game')
                self.room_event({'type':'room', 'state':state, 'reason':info.get('reason') or
                    ('游戏世界已恢复，请重新进入游戏。' if state == 'ready' else
                     '房主不在游戏内，请等待房主重新开放世界。'),
                     'game': game, 'title': info.get('title'),
                     'members':info.get('members'), 'capacity':info.get('capacity'),
                     'game_players':info.get('game_players'), 'latency_ms':latency,
                     'transport':self.transport_state})
            except (OSError, asyncssh.Error, ValueError):
                pass
            await asyncio.sleep(2)

    async def retarget_world(self, port):
        if self.role != 'host' or not self.connection or self.connection.is_closed():
            raise ValueError('房主连接尚未恢复，请稍后重试。')
        info = await game_status(int(port))
        expected_game = (self.room_settings or {}).get('game', {})
        expected = expected_game.get('protocol')
        if expected is not None and info.get('protocol') != expected:
            raise ValueError('这个世界与房间的游戏版本不一致，请重新选择。')
        async with self.world_lock:
            self.game_port = int(port)
            if self.room_settings is not None:
                expected_game['protocol'] = info.get('protocol')
                self.room_info = await request(self.connection, 'configure', **self.room_settings)
            if self.bridge_task:
                self.bridge_task.cancel()
                await asyncio.gather(self.bridge_task, return_exceptions=True)
            self.bridge_task = (asyncio.create_task(self._bridge_loop())
                                if self.room_settings and self.game_chat_enabled else None)
            await request(self.connection, 'availability', available=True)
            self.room_state = 'ready'
        return info

    async def update_game(self, game, game_directory=None):
        if self.role != 'host' or self.room_settings is None:
            raise ValueError('只有房主可以更新房间版本。')
        if self.room_state != 'waiting' and self.game_port:
            raise ValueError('游戏世界已开放，请先结束当前房间再更换版本。')
        self.game_port = 0
        self.room_settings['game'] = dict(game)
        if self.bridge_task:
            self.bridge_task.cancel()
            await asyncio.gather(self.bridge_task, return_exceptions=True)
            self.bridge_task = asyncio.create_task(self._bridge_loop())
        if game_directory:
            self.game_directory = game_directory
            if self.pack_server:
                await self.pack_server.close()
            if self.connection and not self.connection.is_closed():
                from .modpack import ModPackServer
                self.pack_server = ModPackServer(game_directory)
                self.pack_port = await self.pack_server.start()
        if self.connection and not self.connection.is_closed():
            self.room_info = await request(self.connection, 'configure', **self.room_settings)
        return dict(game)

    async def chat_write(self, message):
        process = self.chat_process
        if not process or process.exit_status is not None:
            raise ConnectionError("房间聊天暂不可用，请稍后重试。")
        process.stdin.write(json.dumps(message, ensure_ascii=True).encode() + b'\n')
        await process.stdin.drain()

    async def send_chat(self, text):
        from .chat_validation import chat_text
        text = chat_text(text)
        if len(self.chat_pending) >= 10:
            raise ValueError('待发送消息过多，请稍后重试。')
        request_id = secrets.token_hex(12)
        future = asyncio.get_running_loop().create_future()
        self.chat_pending[request_id] = future
        try:
            await self.chat_write({'op':'send', 'text':text, 'request':request_id})
            await asyncio.wait_for(future, 10)
        finally:
            self.chat_pending.pop(request_id, None)

    async def _read_chat(self, process):
        buffer = bytearray()
        while True:
            chunk = await process.stdout.read(4096)
            if not chunk:
                return
            buffer.extend(chunk)
            while b'\n' in buffer:
                line, _, buffer = buffer.partition(b'\n')
                if len(line) > 32768:
                    raise ValueError('房间消息超过限制')
                event = json.loads(line)
                if not isinstance(event, dict):
                    raise ValueError('节点聊天消息无效')
                if event.get('type') == 'message':
                    from .chat_validation import chat_text
                    chat_text(event.get('text'))
                    if not isinstance(event.get('id'), str) or len(event['id']) > 64:
                        raise ValueError('节点消息标识无效')
                    if not isinstance(event.get('sender'), str) or len(event['sender']) > 32:
                        raise ValueError('节点消息昵称无效')
                    account = event.get('account')
                    if account is not None:
                        import re
                        if not isinstance(account, str) or not re.fullmatch('[0-9a-f]{32}\\.[0-9a-f]{32}', account):
                            raise ValueError('节点账号身份无效')
                request_id = event.get('request')
                if request_id is not None and not isinstance(request_id, str):
                    raise ValueError('节点消息确认标识无效')
                pending = self.chat_pending.get(request_id)
                if pending and not pending.done():
                    if event.get('type') == 'message' and not event.get('replay'):
                        pending.set_result(event)
                    elif event.get('type') == 'error':
                        pending.set_exception(ValueError(str(event.get('error', '消息发送失败。'))))
                event.pop('request', None)
                if event.get('type') == 'ready' and isinstance(event.get('bridge'), str):
                    self.on_chat({'type':'bridge', 'status':event['bridge']})
                if event.get('type') == 'room':
                    self.room_event(event)
                    continue
                self.on_chat(event)
                if (event.get('type') == 'message' and event.get('source') == 'lobby'
                        and not event.get('replay') and self.role == 'host' and self.game_chat_enabled):
                    try:
                        self.bridge_queue.put_nowait(event)
                    except asyncio.QueueFull:
                        self.on_chat({'type':'bridge', 'status':'游戏消息队列已满，消息仍保留在大厅。'})
            if len(buffer) > 8192:
                raise ValueError('房间消息超过限制')

    async def _game_to_chat(self, name, text):
        from .chat_validation import chat_text
        await self.chat_write({'op':'game', 'name':name, 'text':chat_text(text)})

    async def _bridge_send(self):
        last_status = None
        last_process = None
        while True:
            if self.chat_process is not last_process:
                last_status, last_process = None, self.chat_process
            if self.chat_process and self.bridge_status != last_status:
                try:
                    await self.chat_write({'op':'bridge', 'status':self.bridge_status})
                    last_status = self.bridge_status
                except (OSError, asyncssh.Error):
                    pass
            try:
                event = await asyncio.wait_for(self.bridge_queue.get(), .5)
            except asyncio.TimeoutError:
                continue
            try:
                if self.bridge and self.bridge.ready:
                    await self.bridge.send_message(event['sender'], event['text'])
                    await asyncio.sleep(.6)
                else:
                    raise ConnectionError('游戏聊天未同步，消息仅送达大厅。')
            except (OSError, ValueError) as exc:
                self.bridge_status = str(exc)[:160] or '游戏聊天暂不可用，消息仅送达大厅。'
                self.on_chat({'type':'bridge', 'status':self.bridge_status})
            finally:
                self.bridge_queue.task_done()

    async def _chat_loop(self, connection):
        delay = 1
        while not self._stopped and not connection.is_closed():
            try:
                async with await connection.create_process(subsystem='buggcraft-chat-v1', encoding=None) as process:
                    self.chat_process = process
                    await self.chat_write({'op':'hello', 'name':self.chat_name})
                    delay = 1
                    await self._read_chat(process)
            except asyncio.CancelledError:
                raise
            except (OSError, asyncssh.Error, ValueError):
                pass
            finally:
                self.chat_process = None
                for future in self.chat_pending.values():
                    if not future.done():
                        future.set_exception(ConnectionError('聊天连接已断开，消息未确认；请检查记录后重试。'))
            if not connection.is_closed() and not self._stopped:
                self.on_chat({'type':'offline', 'error':'聊天通道断开，正在重连；游戏连接不受影响。'})
                await asyncio.sleep(delay)
                delay = min(30, delay * 2)

    async def _bridge_loop(self):
        if not self.game_chat_enabled:
            return
        from .game_chat import GameChatBridge
        game = (self.room_settings or {}).get('game', {})
        def status(state, detail):
            self.bridge_status = detail[:160]
            self.on_chat({'type':'bridge', 'status':detail, 'state':state})
        while not self._stopped:
            if not self.game_port:
                await asyncio.sleep(1)
                continue
            game = (self.room_settings or {}).get('game', {})
            try:
                self.bridge = GameChatBridge(self.game_port, game.get('protocol'), self._game_to_chat, status,
                                             name=self.game_chat_name)
            except ValueError as exc:
                status('unavailable', str(exc))
                return
            await self.bridge.run()
            permanent = self.bridge.permanent_error
            self.bridge = None
            if permanent:
                return
            await asyncio.sleep(10)

    async def _connect(self):
        from .nodes import candidates
        options = [self._active_profile] + [p for p in candidates(self.profile) if p != self._active_profile]
        if self.role == 'host':
            error = None
            for profile in options:
                try:
                    connection = await self._connect_to(profile)
                    self._active_profile = profile
                    return connection
                except asyncssh.HostKeyNotVerifiable:
                    raise
                except (OSError, asyncssh.Error) as exc:
                    if isinstance(exc, asyncssh.PermissionDenied):
                        raise
                    error = exc
            raise error or ConnectionError('没有可用的联机节点')
        if self.role == 'client':
            from .rooms import locate_room
            try:
                connection = await self._connect_to(self._active_profile)
                return connection
            except asyncssh.HostKeyNotVerifiable:
                raise
            except (OSError, asyncssh.Error) as original:
                # Entry nodes discover the owner; game traffic connects directly
                # to that owner's pinned SSH key and never traverses entry nodes.
                target = await locate_room(self.profile, self.invite.room_id)
                if target is not None:
                    connection = await self._connect_to(target)
                    self._active_profile = target
                    return connection
                raise original

    async def _connect_to(self, profile):
        return await asyncssh.connect(
            profile.server_host, profile.server_port,
            username=f"{self.role}:{self.invite.room_id}",
            password=json.dumps({"token": profile.token.split('~', 1)[0], "secret": self.invite.secret}),
            known_hosts=profile.known_hosts(), client_keys=[], agent_path=None,
            preferred_auth=["password"], connect_timeout=2, login_timeout=4,
            config=None, x509_trusted_certs=None, x509_trusted_cert_paths=[],
            keepalive_interval=2, keepalive_count_max=2, encoding=None, window=256 * 1024,
        )

    async def run(self):
        from utils.diagnostics import connection_session_directory
        directory = connection_session_directory()
        if directory:
            from utils.network_diagnostics import capture_network
            snapshot = asyncio.create_task(asyncio.to_thread(capture_network, directory, self.diagnostic_trace))
            def snapshot_finished(done):
                if not done.cancelled() and (error := done.exception()):
                    LOG.warning('network_snapshot_failed trace=%s error=%s', self.diagnostic_trace,
                                type(error).__name__)
            snapshot.add_done_callback(snapshot_finished)
        LOG.info('endpoint_start trace=%s role=%s policy=%s node=%s:%s', self.diagnostic_trace,
                 self.role, self.transport_policy, self.profile.server_host, self.profile.server_port)
        self.task = asyncio.current_task()
        delay = 1
        try:
            while not self._stopped:
                try:
                    self.on_status("connecting", "正在连接联机服务")
                    async with await self._connect() as connection:
                        self.connection = connection
                        if self.role == "host":
                            # Resolve the current game port when each stream opens.
                            # Reopening a LAN world can assign a new ephemeral port.
                            self.listener = await connection.create_server(
                                lambda _host, _port: connection.forward_connection(
                                    self.game_host, self.game_port), '127.0.0.1', 0)
                            if self.room_settings is not None:
                                if (self.room_settings.get('public') and
                                        self.room_settings.get('require_invite')):
                                    capabilities = await request(connection, 'ping')
                                    if 'room-invite-policy-v1' not in capabilities.get('capabilities', []):
                                        raise ValueError('当前节点不支持公开房间的邀请码保护，请更新节点或改为不公开房间。')
                                self.room_info = await request(connection, 'configure', **self.room_settings)
                                if not self.game_port:
                                    self.room_info = await request(connection, 'availability', available=False)
                            if self.game_directory:
                                from .modpack import ModPackServer
                                self.pack_server = ModPackServer(self.game_directory)
                                self.pack_port = await self.pack_server.start()
                                try:
                                    self.pack_listener = await connection.create_server(
                                        lambda _host, _port: connection.forward_connection('127.0.0.1', self.pack_port),
                                        'buggcraft-mods', 0)
                                except asyncssh.ChannelListenError:
                                    await self.pack_server.close()
                                    self.pack_server = None
                                    self.on_status('warning', '当前节点需要升级才能分享模组；游戏联机和聊天仍可用。')
                        else:
                            self.room_info = await request(connection, 'describe')
                            if self.room_info.get('availability') == 'closed':
                                self.room_event({'type':'room', 'state':'closed', 'reason':self.room_info.get('reason')})
                                break
                            if self.local_game is not None:
                                validate_room(self.room_info)
                                errors, warnings = compatibility(self.local_game, self.room_info.get('game', {}))
                                if errors:
                                    raise ValueError('无法加入：' + '、'.join(errors))
                                if warnings:
                                    self.on_status('warning', '；'.join(warnings))
                            await self._start_peer(connection)
                            if self.peer_transport and self.peer_transport.connected.is_set():
                                from .peer import GameListener
                                self.listener = await GameListener.start(self.peer_transport, self.listen_port)
                            else:
                                self.listener = await connection.forward_local_port(
                                    "127.0.0.1", self.listen_port, self.invite.room_id, 25565)
                            self.listen_port = self.listener.get_port()
                            if self.announce:
                                title = (self.room_info or {}).get('title', 'Buggcraft 好友联机')
                                self.announcement = asyncio.create_task(LanAnnouncer(self.listen_port, title).run())
                        if self.role == 'host':
                            await self._start_peer(connection)
                        self.chat_task = asyncio.create_task(self._chat_loop(connection))
                        self.room_task = asyncio.create_task(self._room_loop(connection))
                        if self.role == 'host' and self.room_settings:
                            if self.game_chat_enabled:
                                self.bridge_task = asyncio.create_task(self._bridge_loop())
                            self.bridge_sender = asyncio.create_task(self._bridge_send())
                        delay = 1
                        self._has_connected = True
                        LOG.info('endpoint_online trace=%s role=%s policy=%s path=%s listen_port=%s',
                                 self.diagnostic_trace, self.role, self.transport_policy,
                                 self.transport_state, self.listen_port)
                        self.recovery_started = None
                        self.on_status("online", self.invite.room_id if self.role == "host"
                                       else f"127.0.0.1:{self.listen_port}")
                        await connection.wait_closed()
                        if not self._stopped:
                            raise ConnectionError("联机服务连接断开")
                except asyncssh.PermissionDenied:
                    # A restarted node can accept clients before the host has
                    # recreated its room. Check terminal state before retrying.
                    if self._has_connected and not self._stopped:
                        if self.role == 'client':
                            try:
                                async with await connect_directory(self.profile) as directory:
                                    state = await request(directory, 'state', id=self.invite.room_id)
                                if state.get('availability') == 'closed':
                                    self.room_event({'type':'room', 'state':'closed',
                                        'reason':'房主已结束联机，房间已关闭。'})
                                    break
                            except (OSError, asyncssh.Error, ValueError):
                                pass
                        now = asyncio.get_running_loop().time()
                        self.recovery_started = self.recovery_started or now
                        if now - self.recovery_started >= 120:
                            self.room_event({'type':'room', 'state':'closed',
                                'reason':'房主长时间未恢复连接，请重新加入房间。'})
                            break
                        self.on_status("reconnecting", "等待节点或房主恢复连接，正在重试")
                        await asyncio.sleep(delay + secrets.randbelow(250) / 1000)
                        from .nodes import candidates
                        delay = min(delay * 2, 3 if len(candidates(self.profile)) > 1 else 30)
                        continue
                    self.on_status("error", "房间已关闭、邀请码失效或节点认证失败，请重新加入。")
                    raise
                except asyncssh.HostKeyNotVerifiable:
                    self.on_status("error", "认证或服务器身份校验失败")
                    raise
                except ValueError as exc:
                    self.on_status('error', str(exc))
                    raise
                except (OSError, asyncssh.Error) as exc:
                    if self._stopped:
                        break
                    self.on_status("reconnecting", "连接中断，正在重连；游戏中请重新加入")
                    LOG.warning("%s endpoint reconnecting: %s", self.role, type(exc).__name__)
                    await asyncio.sleep(delay + secrets.randbelow(250) / 1000)
                    from .nodes import candidates
                    delay = min(delay * 2, 3 if len(candidates(self.profile)) > 1 else 30)
                finally:
                    self.cleaning_up = True
                    # Detach the public connection before transport cleanup,
                    # which may wait for DTLS/SCTP shutdown after room closure.
                    self.connection = None
                    if self.peer_transport:
                        await self.peer_transport.close()
                        self.peer_transport = None
                    if self.pack_listener:
                        self.pack_listener.close()
                        await self.pack_listener.wait_closed()
                        self.pack_listener = None
                    if self.pack_server:
                        await self.pack_server.close()
                        self.pack_server = None
                    if self.room_task:
                        self.room_task.cancel()
                        await asyncio.gather(self.room_task, return_exceptions=True)
                        self.room_task = None
                    for task in (self.bridge_task, self.bridge_sender):
                        if task:
                            task.cancel()
                    await asyncio.gather(*(task for task in (self.bridge_task, self.bridge_sender) if task), return_exceptions=True)
                    self.bridge_task = self.bridge_sender = self.bridge = None
                    while not self.bridge_queue.empty():
                        self.bridge_queue.get_nowait()
                        self.bridge_queue.task_done()
                    if self.chat_task:
                        self.chat_task.cancel()
                        await asyncio.gather(self.chat_task, return_exceptions=True)
                        self.chat_task = None
                    if self.chat_process:
                        self.chat_process.close()
                        await asyncio.gather(self.chat_process.wait_closed(), return_exceptions=True)
                        self.chat_process = None
                    if self.announcement:
                        self.announcement.cancel()
                        await asyncio.gather(self.announcement, return_exceptions=True)
                        self.announcement = None
                    if self.listener:
                        self.listener.close()
                        await self.listener.wait_closed()
                    self.connection = self.listener = None
                    self.cleaning_up = False
        finally:
            self.on_status("stopped", self.stop_reason)

    async def stop(self):
        # Leaving a room and quitting can overlap. Send one owner-close RPC;
        # a second stop must not close SSH before the first RPC reaches the node.
        if self._stop_task is None:
            self._stop_task = asyncio.create_task(self._stop())
        await asyncio.shield(self._stop_task)

    async def _stop(self):
        self._stopped = True
        if self.room_task and self.room_task is not asyncio.current_task():
            self.room_task.cancel()
        if self.role == 'host' and self.connection and not self.connection.is_closed():
            try:
                await asyncio.wait_for(request(self.connection, 'close'), 3)
            except (OSError, asyncssh.Error, ValueError, asyncio.TimeoutError):
                pass
        if self.connection:
            connection = self.connection
            connection.close()
            try:
                await asyncio.wait_for(connection.wait_closed(), 2)
            except asyncio.TimeoutError:
                LOG.warning('endpoint_shutdown_timeout trace=%s role=%s; aborting SSH',
                            self.diagnostic_trace, self.role)
                connection.abort()
        if self.task and self.task is not asyncio.current_task():
            if not self.cleaning_up:
                self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        if self.peer_transport:
            await self.peer_transport.close()
            self.peer_transport = None


class TunnelHost(TunnelEndpoint):
    def __init__(self, profile, invite=None, **kwargs):
        super().__init__(profile, invite or RoomInvite.create(), role="host", **kwargs)


class TunnelClient(TunnelEndpoint):
    def __init__(self, profile, invite, **kwargs):
        super().__init__(profile, invite, role="client", **kwargs)


class TunnelService:
    """Own endpoints in one background event loop, independent of Qt's UI."""
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.endpoints = {}
        self._retiring = set()
        self.closed = False
        self._close_lock = threading.Lock()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True, name="multiplayer")
        self.thread.start()

    def add(self, name, endpoint):
        if self.closed:
            raise RuntimeError('联机服务已经关闭')
        if name in self.endpoints:
            raise ValueError("联机连接名称已存在")
        self.endpoints[name] = endpoint
        future = asyncio.run_coroutine_threadsafe(endpoint.run(), self.loop)
        # Retrieve exceptions so a failed login is surfaced rather than hidden.
        def completed(result):
            if not result.cancelled():
                try:
                    result.result()
                except Exception as exc:
                    endpoint.on_status("error", str(exc))
        future.add_done_callback(completed)
        return future

    def submit(self, coroutine):
        if self.closed:
            coroutine.close()
            raise RuntimeError('联机服务已经关闭')
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop)

    def remove(self, name):
        endpoint = self.endpoints.pop(name)
        self._retiring.add(endpoint)
        future = asyncio.run_coroutine_threadsafe(endpoint.stop(), self.loop)
        future.add_done_callback(lambda done: self._retiring.discard(endpoint))
        return future

    def close(self):
        async def shutdown():
            endpoints = tuple(dict.fromkeys((*self.endpoints.values(), *self._retiring)))
            stops = [asyncio.create_task(endpoint.stop()) for endpoint in endpoints]
            if stops:
                _, pending_stops = await asyncio.wait(stops, timeout=7)
                for endpoint in endpoints:
                    endpoint._stopped = True
                    if endpoint.connection:
                        endpoint.connection.abort()
                for task in pending_stops:
                    task.cancel()
                await asyncio.gather(*stops, return_exceptions=True)
            self.endpoints.clear()
            self._retiring.clear()
            pending = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        with self._close_lock:
            if self.closed:
                return
            self.closed = True
            if not self.loop.is_closed():
                future = asyncio.run_coroutine_threadsafe(shutdown(), self.loop)
                try:
                    future.result(timeout=10)
                except TimeoutError:
                    LOG.error('multiplayer_shutdown_timeout; forcing control connections closed')
                    def abort_remaining():
                        for endpoint in tuple(self.endpoints.values()) + tuple(self._retiring):
                            endpoint._stopped = True
                            if endpoint.connection:
                                endpoint.connection.abort()
                    self.loop.call_soon_threadsafe(abort_remaining)
                    future.cancel()
                finally:
                    self.loop.call_soon_threadsafe(self.loop.stop)
                    self.thread.join(timeout=3)
                    if not self.thread.is_alive():
                        self.loop.close()
        LOG.info('multiplayer_service_closed thread_alive=%s', self.thread.is_alive())
