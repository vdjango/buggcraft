"""Qt presentation state; all multiplayer I/O belongs to the C++ bridge."""
import asyncio
import hashlib
import math
from pathlib import Path
import re
import threading
import time
import uuid

from PySide6.QtCore import QObject, Property, Signal, Slot, QStandardPaths, QTimer
from PySide6.QtWidgets import QApplication, QFileDialog

from hookup.profiles import RelayProfile, RoomInvite
from hookup.native_transport import TunnelHost, TunnelClient, TunnelService
from hookup.native_routes import manager as native_bridge
from hookup.rooms import instance_metadata, list_room_page, resolve_room, compatibility, lookup_account
from hookup.storage import LobbyStore
from hookup.nodes import decode_code, probe, save_json, profile_data, remember, node_identity
from hookup.social import check_expiry, credential_expiry, ExpiredNodeCredential, EXPIRED_CODE_MESSAGE
from utils.instances import installed_instance_ids, running_games


class MultiplayerController(QObject):
    changed = Signal()
    completed = Signal(str, object, object)
    status = Signal(str, str, str)
    chat_event = Signal(str, object)
    chat_sent = Signal(str, object)
    preparation_progress = Signal(str, str, object, object)
    copied = Signal(str)
    friend_finished = Signal(bool, str)
    friend_invited = Signal(object)
    route_changed = Signal(str, str)

    def __init__(self, window, storage_path=None):
        super().__init__(window)
        self.window = window
        self.launcher_page = getattr(window, "launcher_page", None) or window.parent()
        self.service = TunnelService()
        self.jobs = set()
        self.game = {}
        self.pending = None
        self.creation = None
        self.generation = uuid.uuid4().hex
        self.closed = False
        self.records = {}
        self.chat_state = '加入房间后连接'
        self.bridge_status = '游戏聊天同步由房主创建房间时设置。'
        self.node_path = ''
        self.friend_request = None
        self.social_path = ''
        self.social_identity = None
        self.social_generation = uuid.uuid4().hex
        self.pending_node_update = None
        self.pending_friend_invite = None
        self.seen_friend_invitations = set()
        self.ignored_friend_invitations = set()
        self.instance_job = None
        self.instance_source = None
        self.preparations = {}
        self.external_running = None
        self.runtime_job = False
        self.room_generation = uuid.uuid4().hex
        self.node_check_generation = uuid.uuid4().hex
        self.room_search_timer = QTimer(self)
        self.room_search_timer.setSingleShot(True)
        self.room_search_timer.setInterval(300)
        self.room_search_timer.timeout.connect(self.refresh)
        self._state = dict(page='hall', step=0, nodes=[], nodeIndex=-1, nodeAvailable=False, nodeLatencyMs=None,
                           rooms=[], contacts=[], friendRequests=[], friendInvitations=[], socialAccount='', socialName='', socialReady=False, socialError='',
                           connections=[], worlds=[], selected='', busy=False, friendBusy=False, socialLoading=False, loading=False,
                           pendingFriendInvite='', outgoingInvitations={},
                           nodeAccessExpired=False, nodeAccessMessage='',
                           error='', notice='', nodeDraft='', roomError='', needsVersion=False,
                           joinRoomId='', joinRoomTitle='', invitePrompt=False,
                           transportPolicy='auto',
                           nodeUpdatePrompt=False, nodeUpdateMessage='',
                           roomQuery='', roomNext=None, roomTotal=None, loadingMore=False,
                           version='', loader='vanilla', loaderVersion='', worldPort=0,
                           instances=[], instanceId='', instanceLoading=False, instanceError='',
                           instanceLocked=False, chatMessages=[], chatState=self.chat_state,
                           bridgeStatus=self.bridge_status, chatError='', chatDraft='', chatSending=False)
        start_page = self.launcher_page
        main_window = getattr(start_page, 'parent', None)
        cache = getattr(main_window, 'cache_path', None)
        root = Path(cache or QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation)) / 'multiplayer'
        try:
            self.store = LobbyStore(storage_path or root / 'lobby.json')
        except (OSError, ValueError) as exc:
            self.store = None
            self._state['notice'] = '本地配置未能读取，原文件已保留：' + str(exc)
        self.completed.connect(self.finish)
        self.status.connect(self.update_status)
        self.chat_event.connect(self.update_chat)
        self.chat_sent.connect(self.finish_chat)
        self.preparation_progress.connect(self.update_preparation)
        self.route_changed.connect(self.show_route_tip)
        QApplication.instance().aboutToQuit.connect(self.close)
        self.reload_store()
        self.friend_timer = QTimer(self)
        self.friend_timer.setInterval(5000)
        self.friend_timer.timeout.connect(self.refresh_friends)
        self.friend_timer.start()

    @Property('QVariantMap', notify=changed)
    def view(self):
        return self._state

    def patch(self, **values):
        self._state.update(values)
        self.changed.emit()

    @staticmethod
    def valid_latency(value):
        return (round(value, 1) if type(value) in (int, float) and
                math.isfinite(value) and value >= 0 else None)

    def reload_store(self, select=None, refresh_identity=False):
        nodes = []
        for path in self.store.data['nodes'] if self.store else []:
            personal_code = False
            expired = False
            try:
                profile = RelayProfile.load(path)
                title = self.store.data['node_names'].get(path, '社区节点')
                personal_code = profile.token.startswith('acct1.')
                expiry = credential_expiry(profile)
                expired = expiry is not None and expiry <= time.time()
            except Exception:
                title = '配置不可用 · ' + Path(path).name
            nodes.append({'title': title, 'path': path, 'personalCode': personal_code, 'codeExpired': expired})
        paths = [node['path'] for node in nodes]
        target = select or self.node_path
        index = paths.index(target) if target in paths else (0 if paths else -1)
        self.patch(nodes=nodes, nodeIndex=index)
        self.patch(nodeAccessExpired=bool(index >= 0 and nodes[index]['codeExpired']),
                   nodeAccessMessage=EXPIRED_CODE_MESSAGE if index >= 0 and nodes[index]['codeExpired'] else '')
        new_path = paths[index] if index >= 0 else ''
        if new_path != self.node_path or refresh_identity:
            self.node_path = new_path
            self.patch(rooms=[], roomError='', nodeAvailable=False)
            self.refresh()
        try:
            identity = (new_path, hashlib.sha256(RelayProfile.load(new_path).token.encode()).hexdigest()) if new_path else None
        except (OSError, ValueError):
            identity = (new_path, None)
        if identity != self.social_identity or refresh_identity:
            self.social_identity = identity
            self.social_generation = uuid.uuid4().hex
            self.pending_friend_invite = None
            self.seen_friend_invitations.clear()
            self.ignored_friend_invitations.clear()
            self.friend_request = None
            self.social_path = new_path
            self.patch(contacts=[], friendRequests=[], friendInvitations=[], socialAccount='', socialName='', socialReady=False,
                       socialError='', friendBusy=False, socialLoading=False, pendingFriendInvite='', outgoingInvitations={})
            self.refresh_friends()

    def job(self, key, coroutine):
        if self.closed or key in self.jobs:
            coroutine.close()
            return
        self.jobs.add(key)
        future = self.service.submit(coroutine)
        def done(result):
            try:
                value, error = result.result(), None
            except Exception as exc:
                value, error = None, str(exc) or type(exc).__name__
            if not self.closed:
                self.completed.emit(key, value, error)
        future.add_done_callback(done)

    @Slot(str, 'QVariantMap')
    def act(self, action, data):
        try:
            if action == 'exportDiagnostics':
                from datetime import datetime
                from utils.diagnostics import export_diagnostics
                path, _ = QFileDialog.getSaveFileName(self.window, '导出联机诊断日志',
                    'Buggcraft-diagnostics-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.zip',
                    'ZIP (*.zip)')
                if path:
                    if not path.lower().endswith('.zip'):
                        path += '.zip'
                    self.patch(notice='正在采集网络拓扑与游戏诊断日志…')
                    self.job('diagnostics', asyncio.to_thread(export_diagnostics, path))
            elif action == 'clearError':
                record = self.records.get(self._state['selected'])
                if record:
                    record['chatError'] = ''
                self.patch(error='', chatError='')
            elif action == 'openFriends':
                if not self._state['socialReady']:
                    raise ValueError('当前为匿名或未验证状态，请先添加个人接入码。')
                self.window.show_friends()
            elif action == 'navigate':
                self.navigate(data['page'])
            elif action == 'node':
                if self._state['connections']:
                    raise ValueError('房间运行期间不能切换节点，请先退出所有房间。')
                index = int(data['index'])
                self.node_path = self._state['nodes'][index]['path']
                self.patch(nodeIndex=index, rooms=[], roomError='', nodeAvailable=False)
                self.reload_store()
                self.refresh()
            elif action == 'refresh':
                self.refresh()
            elif action == 'loadMoreRooms':
                self.load_more_rooms()
            elif action == 'searchRooms':
                query = str(data.get('text', ''))[:100]
                if query != self._state['roomQuery']:
                    self.room_generation = uuid.uuid4().hex
                    self.patch(roomQuery=query, rooms=[], roomNext=None, roomTotal=None,
                               loading=bool(self.node_path), loadingMore=False, roomError='')
                    self.room_search_timer.start()
            elif action == 'discover':
                self.patch(busy=True, error='', worlds=[])
                excluded = [e.listen_port for e in self.service.endpoints.values() if e.role == 'client']
                async def discover():
                    result = await native_bridge().request('game.discover', {'exclude': excluded, 'duration_ms': 3000})
                    return result.get('worlds', [])
                self.job('lan:' + self.generation, discover())
            elif action == 'probe':
                self.probe(data)
            elif action == 'createWaiting':
                self.require_available_node()
                self.require_instance()
                self.creation = {'path': self.node_path, 'game': dict(self.game), 'port': 0}
                self.patch(step=1, error='')
            elif action == 'create':
                self.create(data)
            elif action == 'backCreate':
                if self._state['step'] == 1 and self.creation:
                    self.patch(step=0, error='', notice='', busy=False)
            elif action == 'join':
                policy = data.get('transport', self._state['transportPolicy'])
                if policy not in ('auto', 'relay'):
                    raise ValueError('请选择有效的连接方式。')
                self.patch(transportPolicy=policy)
                self.join(data.get('invite', ''), room_id=self._state['joinRoomId'] or None)
            elif action == 'transport':
                if self._state['connections']:
                    raise ValueError('房间运行期间不能切换连接方式。')
                policy = data.get('policy')
                if policy not in ('auto', 'relay'):
                    raise ValueError('请选择有效的连接方式。')
                self.patch(transportPolicy=policy)
            elif action == 'cancelInvite':
                self.generation = uuid.uuid4().hex
                self.patch(invitePrompt=False, joinRoomId='', joinRoomTitle='', error='', busy=False)
            elif action == 'joinPublic':
                self.require_available_node()
                path, profile = self.node_path, self.profile()
                self.patch(busy=True, error='')
                async def resolve():
                    return {'path': path, **await resolve_room(profile, data['id'])}
                self.job('resolve:' + self.generation, resolve())
            elif action == 'selectInstance':
                self.select_instance(data['id'])
            elif action == 'launchRoom':
                self.launch_room()
            elif action == 'syncRoomVersion':
                self.sync_room_version()
            elif action == 'prepareRoom':
                self.prepare_room()
            elif action == 'cancelPreparation':
                cancel = self.preparations.get(self._state['selected'])
                if cancel:
                    cancel.set()
            elif action == 'loadMods':
                name = self._state['selected']
                endpoint = self.service.endpoints.get(name)
                if endpoint:
                    from hookup.modpack import fetch_manifest
                    self.job('manifest:' + name, fetch_manifest(endpoint))
            elif action == 'copyInvite':
                endpoint = self.service.endpoints.get(data['id'])
                if endpoint and self.records[data['id']]['state'] == 'online':
                    QApplication.clipboard().setText(endpoint.invite.encode())
                    self.copied.emit('invite')
            elif action == 'copyAddress':
                endpoint = self.service.endpoints.get(data['id'])
                if endpoint and endpoint.role == 'client' and endpoint.listener:
                    QApplication.clipboard().setText(f'127.0.0.1:{endpoint.listen_port}')
                    self.copied.emit('address')
            elif action == 'stop':
                name = data['id']
                self.forget_room(name, '房间已关闭。' if self.records.get(name, {}).get('role') == 'host' else '已退出房间。')
            elif action == 'reopenWorld':
                self.patch(page='worldPicker', worlds=[], busy=False, error='', notice='')
                self.act('discover', {})
            elif action == 'applyWorld':
                name = self._state['selected']
                endpoint = self.service.endpoints.get(name)
                if not endpoint or endpoint.role != 'host':
                    raise ValueError('只有房主可以重新选择世界。')
                port = int(data.get('port') or 0)
                if not 1 <= port <= 65535:
                    raise ValueError('请选择世界，或填写游戏显示的端口。')
                self.patch(busy=True, error='')
                self.job('retarget:' + name, endpoint.retarget_world(port))
            elif action == 'selectConnection':
                self.patch(page='connected', selected=data['id'], error='', notice='')
                self.publish_connections()
            elif action == 'saveFriend':
                self.lookup_friend(data)
            elif action == 'joinFriend':
                self.require_available_node()
                if any(record.get('state') not in ('stopped', 'error') for record in self.records.values()):
                    raise ValueError('请先退出当前房间，再接受新的联机邀请。')
                if not any(item['id'] == data['id'] and item['account'] == data['account']
                           for item in self._state['friendInvitations']):
                    raise ValueError('邀请已过期或已处理，请好友重新邀请。')
                self.social_operation('join', data['account'], ref=data['id'])
            elif action == 'ignoreFriendInvite':
                self.ignored_friend_invitations.add(data['id'])
                self.patch(friendInvitations=[item for item in self._state['friendInvitations']
                                              if item['id'] != data['id']])
            elif action == 'cancelFriendInvite':
                self.pending_friend_invite = None
                self.patch(pendingFriendInvite='', notice='已取消待发送的邀请。')
            elif action == 'acceptFriend':
                self.social_operation('accept', data['account'], ref=data['id'])
            elif action in ('declineFriend', 'removeFriend'):
                self.social_operation('remove', data['account'])
            elif action == 'inviteFriend':
                self.invite_friend(data['account'])
            elif action == 'refreshFriends':
                self.refresh_friends()
            elif action == 'replaceNodeCode':
                self.navigate('nodes')
                self.patch(nodeDraft='', notice='在原节点网页登录账号，领取新的个人启动器接入码后粘贴。确认更新即可保留原节点。')
            elif action == 'editFriend':
                index = int(data['index'])
                contact = self.store.data['contacts'][index]
                self.patch(page='friendForm', error='', editIndex=index, friendName=contact['name'], friendAccount=contact.get('account', ''))
            elif action == 'importNode':
                path, _ = QFileDialog.getOpenFileName(self.window, '导入可信节点配置', '', 'JSON (*.json)')
                if path:
                    self.import_node(path)
            elif action == 'nodeDraft':
                self.patch(nodeDraft=str(data.get('text', ''))[:4096])
            elif action == 'addNodeCode':
                profile = decode_code(self._state['nodeDraft'])
                self.verify_node(profile)
            elif action == 'confirmNodeUpdate':
                pending = self.pending_node_update
                if pending:
                    self.pending_node_update = None
                    self.patch(nodeUpdatePrompt=False)
                    self.save_verified_node(pending)
            elif action == 'cancelNodeUpdate':
                self.pending_node_update = None
                self.patch(nodeUpdatePrompt=False, busy=False, notice='已取消更新，原接入码继续保留。')
            elif action == 'exportNode':
                self.profile()
                path, _ = QFileDialog.getSaveFileName(self.window, '导出节点配置', 'relay-profile.json', 'JSON (*.json)')
                if path:
                    Path(path).write_bytes(Path(self.node_path).read_bytes())
                    self.patch(notice='节点配置已导出，请只分享给可信的朋友。')
            elif action == 'removeNode':
                if self._state['connections']:
                    raise ValueError('请先退出所有房间再移除节点。')
                if self.store and self.node_path in self.store.data['nodes']:
                    self.store.data['nodes'].remove(self.node_path)
                    self.store.save()
                    self.reload_store()
            elif action == 'dismiss':
                self.patch(notice='')
            elif action == 'close':
                self.window.close()
            elif action == 'sendChat':
                record = self.records.get(self._state['selected'])
                if record and record.get('chatSending'):
                    return
                endpoint = self.service.endpoints.get(self._state['selected'])
                from hookup.chat_validation import chat_text
                message = chat_text(data.get('text', ''))
                if not endpoint:
                    raise ValueError('先加入一个房间，再发送聊天消息。')
                record.update(chatSending=True, chatError='', chatDraft=message)
                self.publish_connections()
                future = self.service.submit(endpoint.send_chat(message))
                future.add_done_callback(lambda result, key=self._state['selected']:
                                         self.chat_sent.emit(key, result))
            elif action == 'chatDraft':
                record = self.records.get(self._state['selected'])
                if record and not record.get('chatSending'):
                    record['chatDraft'] = str(data.get('text', ''))[:256]
                    record['chatError'] = ''
                    self.publish_connections()
            elif action == 'minimize':
                self.window.showMinimized()
            elif action == 'drag':
                if self.window.windowHandle():
                    self.window.windowHandle().startSystemMove()
        except Exception as exc:
            self.patch(error=str(exc) or '操作未完成，请重试。', busy=False)

    def navigate(self, page):
        if page not in ('hall', 'create', 'join', 'friends', 'friendForm', 'connections', 'connected', 'nodes'):
            return
        if page in ('friends', 'friendForm') and not self._state['socialReady']:
            raise ValueError('匿名接入没有好友功能，请先领取个人接入码。')
        if page in ('create', 'join'):
            self.require_available_node()
        if page == 'connected' and self._state['selected'] not in self.records:
            page = 'hall'
        if page == 'connections' and not self._state['connections']:
            page = 'hall'
        self.generation = uuid.uuid4().hex
        self.pending = self.creation = None
        self.patch(page=page, error='', notice='', busy=False, step=0, needsVersion=False,
                   joinRoomId='', joinRoomTitle='', invitePrompt=False,
                   worlds=[], worldPort=0, editIndex=-1, friendName='', friendAccount='')

    def profile(self):
        if not self.node_path:
            raise ValueError('请先通过大厅的节点菜单添加可信节点。')
        profile = RelayProfile.load(self.node_path)
        try:
            check_expiry(profile)
        except ExpiredNodeCredential:
            self.mark_node_expired()
            raise
        path = self.node_path
        object.__setattr__(profile, '_route_notice', lambda name: self.route_changed.emit(path, name))
        return profile

    def mark_node_expired(self):
        nodes = [dict(node, codeExpired=True) if node['path'] == self.node_path else node
                 for node in self._state['nodes']]
        self.patch(nodes=nodes, nodeAccessExpired=True, nodeAccessMessage=EXPIRED_CODE_MESSAGE,
                   nodeAvailable=False, socialReady=False, socialLoading=False,
                   contacts=[], friendRequests=[], friendInvitations=[],
                   socialAccount='', socialName='', socialError=EXPIRED_CODE_MESSAGE,
                   roomError='个人接入码已过期，请更换后重试。', loading=False, loadingMore=False)

    @Slot(str, str)
    def show_route_tip(self, path, name):
        if not self.closed and path == self.node_path and not self._state.get('error'):
            self.patch(notice='已选择节点「' + name + '」，后续连接使用新线路。')

    def require_available_node(self):
        """Require a node that has completed a successful directory check."""
        if not self.node_path:
            raise ValueError('请先添加一个可用的联机节点。')
        if self._state['nodeAccessExpired']:
            raise ExpiredNodeCredential(EXPIRED_CODE_MESSAGE)
        if not self._state.get('nodeAvailable', False):
            raise ValueError('当前联机节点不可用，请先刷新并等待连接检查完成。')
        try:
            return self.profile()
        except ExpiredNodeCredential:
            raise
        except (OSError, ValueError):
            self.patch(nodeAvailable=False)
            raise ValueError('节点配置不可用，请重新导入。') from None

    def import_node(self, path):
        self.verify_node(RelayProfile.load(path))

    def verify_node(self, profile):
        check_expiry(profile)
        if not self.store:
            raise ValueError('请先修复本地配置。')
        if self._state['busy']:
            return
        self.patch(busy=True, error='', notice='正在验证节点身份和连接…')
        self.job('nodecode:' + self.generation, probe(profile))

    def matching_nodes(self, profile):
        matches = []
        identity = node_identity(profile)
        for path in self.store.data['nodes']:
            try:
                existing = RelayProfile.load(path)
            except (OSError, ValueError):
                continue
            if node_identity(existing) == identity:
                matches.append(path)
            elif (existing.server_host.lower().rstrip('.'), existing.server_port) == (profile.server_host.lower().rstrip('.'), profile.server_port):
                raise ValueError('同一地址的节点公钥发生变化，请先核实节点身份；原配置未覆盖。')
        return matches

    def save_verified_node(self, profile):
        if not self.store:
            raise ValueError('请先修复本地配置。')
        matches = self.matching_nodes(profile)
        identifier = hashlib.sha256(node_identity(profile).encode()).hexdigest()
        path = Path(self.node_path if self.node_path in matches else matches[0]) if matches else self.store.path.parent / 'nodes' / (identifier + '.json')
        save_json(path, profile_data(profile))
        remember(RelayProfile.load(path), list(profile._nodes))
        chosen = str(path.resolve())
        # Keep old files, but retain a single list entry for this pinned node.
        self.store.data['nodes'] = [item for item in self.store.data['nodes'] if item not in matches or item == chosen]
        if chosen not in self.store.data['nodes']:
            self.store.data['nodes'].append(chosen)
        for previous in matches:
            if previous != chosen:
                self.store.data['node_names'].pop(previous, None)
        self.store.data['node_names'][chosen] = getattr(profile, '_name', '社区节点')
        self.store.save()
        self.reload_store(self.node_path if self._state['connections'] else chosen, refresh_identity=True)
        notice = ('个人接入码已更新，正在重新加载好友；现有房间保持连接，新身份用于后续联机。'
                  if profile.token.startswith('acct1.') else '匿名节点已保存；匿名接入不提供好友功能。')
        if self.node_path != chosen:
            notice = '节点已保存；当前房间结束后，切换到该节点即可使用新的接入身份。'
        self.patch(nodeDraft='', busy=False, error='', notice=notice)

    def refresh(self):
        self.room_search_timer.stop()
        self.room_generation = uuid.uuid4().hex
        self.node_check_generation = uuid.uuid4().hex
        self.patch(rooms=[], roomNext=None, roomTotal=None, loadingMore=False,
                   roomError='', nodeAvailable=False, nodeLatencyMs=None)
        if not self.node_path:
            self.patch(loading=False)
            return
        try:
            profile = self.profile()
        except ExpiredNodeCredential:
            return
        except Exception:
            self.patch(roomError='节点配置不可用，请重新导入。', loading=False)
            return
        self.patch(loading=True, roomError='')
        self.job('rooms:' + self.room_generation + ':0',
                 list_room_page(profile, query=self._state['roomQuery']))

    def load_more_rooms(self):
        offset = self._state['roomNext']
        if (offset is None or self._state['loading'] or self._state['loadingMore']
                or self.room_search_timer.isActive()):
            return
        try:
            profile = self.profile()
        except ExpiredNodeCredential:
            return
        except Exception:
            self.patch(roomError='节点配置不可用，请重新导入。', nodeAvailable=False)
            return
        self.node_check_generation = uuid.uuid4().hex
        self.patch(loadingMore=True, roomError='')
        self.job('rooms:' + self.room_generation + ':' + str(offset),
                 list_room_page(profile, offset=offset, query=self._state['roomQuery']))

    def check_node(self):
        """Check availability without clearing a paginated list or editing a form."""
        if self.closed or self._state['loading'] or self._state['loadingMore']:
            return
        if not self.node_path:
            self.patch(nodeAvailable=False, nodeLatencyMs=None)
            return
        try:
            profile = self.profile()
        except ExpiredNodeCredential:
            return
        except Exception:
            self.patch(nodeAvailable=False, nodeLatencyMs=None, roomError='节点配置不可用，请重新导入。')
            return
        key = 'nodehealth:' + self.node_check_generation
        if key in self.jobs:
            return
        from hookup.rooms import connect_directory, request
        async def check():
            async with await connect_directory(profile) as connection:
                started = time.perf_counter()
                await request(connection, 'ping')
                return (time.perf_counter() - started) * 1000
        self.job(key, check())

    def select_instance(self, version):
        page = self.launcher_page
        launcher = getattr(page, 'launcher', None)
        if not launcher or self._state['instanceLocked'] or getattr(launcher, 'running', False):
            raise ValueError('请先退出当前游戏，再切换游戏配置。')
        if version not in self._state['instances']:
            raise ValueError('这个实例已不可用，请在首页重新选择。')
        page.settings_manager.set_setting('minecraft.version.enable', version)
        page.settings_manager.save_settings()
        main = getattr(page, 'parent', None)
        popup = getattr(getattr(main, 'title_bar', None), 'version_popup', None)
        if popup:
            main.title_bar.refresh_versions()
            popup.set_selected(version)
        page.set_minecraft_version(version)

    def detect_instance(self):
        if self.closed:
            return
        page = self.launcher_page
        launcher = getattr(page, 'launcher', None)
        if not launcher:
            return
        settings = page.settings_manager
        running = getattr(page, 'running_instance', None) if page.current_client else None
        if not running and getattr(launcher, 'start_thread', None) is not None:
            running = getattr(page, '_launch_instance', None)
        running = running or self.external_running
        source = running or (launcher.minecraft_directory, launcher.minecraft_version,
                             settings.get_minecraft_isolation_directory())
        directory, version, game_directory = source
        installed = installed_instance_ids(directory)
        self.patch(instances=installed, instanceId=version or '', instanceLocked=bool(running))
        if source == self.instance_source and not self._state['instanceError']:
            return
        self.instance_source = source
        self.game = {}
        self.creation = None
        self.generation = uuid.uuid4().hex
        self.instance_job = None
        self.patch(version='', loader='vanilla', loaderVersion='', step=0, busy=False,
                   instanceLoading=False, instanceError='', error='')
        if not directory or not version:
            return
        key = 'instance:' + uuid.uuid4().hex
        self.instance_job = key
        self.patch(instanceLoading=True)
        self.job(key, asyncio.to_thread(instance_metadata, directory, version, game_directory))

    def detect_runtime(self):
        page = self.launcher_page
        launcher = getattr(page, 'launcher', None)
        if launcher and not self.runtime_job and not self.closed:
            self.runtime_job = True
            self.job('runtime', asyncio.to_thread(running_games, launcher.minecraft_directory))

    def require_instance(self):
        if self._state['instanceLoading']:
            raise ValueError('正在读取所选游戏实例，请稍候。')
        if not self.game.get('version'):
            raise ValueError('请先从上方选择已安装的游戏实例。' if not self._state['instanceError']
                             else self._state['instanceError'])

    def probe(self, data):
        self.require_available_node()
        self.require_instance()
        port = int(data.get('port') or 0)
        if not 1 <= port <= 65535:
            raise ValueError('请查找世界，或填写游戏显示的端口（1–65535）。')
        game = dict(self.game)
        self.creation = {'path': self.node_path, 'game': game, 'port': port}
        self.patch(busy=True, error='')
        async def inspect_world():
            return await native_bridge().request('game.status', {'port': port, 'timeout_ms': 4000})
        self.job('probe:' + self.generation, inspect_world())

    def create(self, data):
        self.require_available_node()
        if not self.creation or self._state['step'] != 1:
            raise ValueError('请先确认游戏世界可以连接。')
        if self.creation['path'] != self.node_path:
            raise ValueError('节点已切换，请返回上一步重新确认世界。')
        title = data.get('title', '').strip()
        if not title or len(title) > 80:
            raise ValueError('房间名称需要 1–80 个字符。')
        game_chat_enabled = data.get('gameChatEnabled', False)
        if type(game_chat_enabled) is not bool:
            raise ValueError('游戏聊天同步开关无效，请重新选择。')
        game_chat_name = None
        if game_chat_enabled:
            from hookup.chat_validation import bridge_player_name
            game_chat_name = bridge_player_name(data.get('gameChatName', 'BuggChat'))
            current = getattr(getattr(self.launcher_page, 'auth_manager', None), 'current', None)
            username = getattr(current, 'username', '')
            if isinstance(username, str) and game_chat_name.casefold() == username.casefold():
                raise ValueError('虚拟玩家不能与当前游戏玩家重名，请更换英文名称。')
        public, require_invite = data.get('public', False), data.get('requireInvite', False)
        if type(public) is not bool or type(require_invite) is not bool:
            raise ValueError('房间公开和邀请码设置无效，请重新选择。')
        settings = {'title': title, 'public': public, 'require_invite': not public or require_invite,
                    'capacity': 100, 'game': self.creation['game']}
        directory = self.instance_source[2] if self.instance_source else None
        endpoint = TunnelHost(self.profile(), game_port=self.creation['port'], room_settings=settings,
                              game_directory=directory, game_chat_enabled=game_chat_enabled,
                              game_chat_name=game_chat_name,
                              transport_policy=data.get('transport', 'auto'))
        name = self.start(endpoint, title)
        self.creation = None
        if self.pending_friend_invite and self.pending_friend_invite[0] == self.social_generation:
            self.pending_friend_invite = (*self.pending_friend_invite[:2], name)
            self.patch(notice='正在创建房间，连接成功后自动发送好友邀请…')

    def join(self, invitation, *, room_id=None):
        self.require_available_node()
        invite = RoomInvite.decode(invitation.strip())
        if room_id and invite.room_id != room_id:
            raise ValueError('邀请码不属于所选房间，请向该房主获取正确邀请码。')
        self.pending = (self.node_path, invite)
        self.patch(page='join', invitePrompt=False, error='', notice='', busy=False)
        self.continue_join()

    def continue_join(self):
        if self.pending is None:
            return
        path, invite = self.pending
        if self.node_path != path:
            self.pending = None
            raise ValueError('节点已切换，请重新加入。')
        profile = self.require_available_node()
        for name, endpoint in list(self.service.endpoints.items()):
            if endpoint.role == 'client' and endpoint.profile == profile and endpoint.invite == invite:
                if self.records[name]['state'] in ('error', 'stopped'):
                    self.service.remove(name)
                else:
                    self.patch(page='connected', selected=name, needsVersion=False, busy=False)
                    self.publish_connections()
                    self.pending = None
                    return
        # Room chat and metadata are available before game files are installed.
        self.start(TunnelClient(profile, invite, listen_port=0,
                                transport_policy=self._state['transportPolicy']), '好友的房间')
        self.pending = None

    def start(self, endpoint, title):
        name = uuid.uuid4().hex
        endpoint.on_status = lambda state, detail: self.status.emit(name, state, detail)
        self.records[name] = {'id': name, 'title': title, 'role': endpoint.role,
                              'state': 'connecting', 'detail': '', 'warning': '',
                              'public': bool((endpoint.room_settings or {}).get('public', False)),
                              'requireInvite': (endpoint.room_settings or {}).get('require_invite', True),
                              'game': dict((endpoint.room_settings or {}).get('game', {})),
                              'compatibility': '',
                              'transportPolicy':endpoint.transport_policy,
                              'transport':'',
                              'preparing': False, 'prepareStatus': '', 'prepareProgress': 0,
                              'prepareMaximum': 0, 'mods': [],
                              'chatMessages': [], 'chatState': '正在连接聊天',
                              'chatSending': False, 'chatDraft': '', 'chatError': '',
                              'bridgeStatus': endpoint.bridge_status if endpoint.role == 'host' else
                                              '正在读取房主的游戏聊天设置…'}
        self.records[name]['availability'] = 'ready'
        page = self.launcher_page
        current = getattr(getattr(page, 'auth_manager', None), 'current', None)
        nickname = getattr(current, 'username', '') or '玩家'
        endpoint.chat_name = ''.join(ch for ch in nickname if ch.isprintable() and ch != '§')[:32] or '玩家'
        endpoint.on_chat = lambda event: self.chat_event.emit(name, event)
        self.service.add(name, endpoint)
        self.publish_connections()
        self.patch(page='connected', selected=name, busy=False, error='', needsVersion=False, notice='')
        self.publish_connections()
        return name

    def publish_connections(self):
        records = [dict(record) for record in reversed(self.records.values())]
        selected = next((r for r in records if r['id'] == self._state['selected']), {})
        self.patch(connections=records, chatMessages=selected.get('chatMessages', []),
                   chatState=selected.get('chatState', '加入房间后连接'),
                   chatError=selected.get('chatError', ''),
                   chatDraft=selected.get('chatDraft', ''), chatSending=selected.get('chatSending', False),
                   bridgeStatus=selected.get('bridgeStatus', '房主连接游戏后，游戏聊天会同步到大厅。'))

    @Slot(str, object)
    def update_chat(self, name, event):
        record = self.records.get(name)
        if not record or not isinstance(event, dict):
            return
        if event.get('type') == 'room':
            if event.get('state') == 'closed':
                self.forget_room(name, str(event.get('reason') or '房主已结束联机，房间已关闭。'))
                return
            record['availability'] = event.get('state', 'ready')
            record['presenceDetail'] = str(event.get('reason', ''))[:160]
            if event.get('transport') in ('p2p', 'relay', 'auto'):
                record['transport'] = event['transport']
            for key in ('members', 'capacity', 'game_players', 'latency_ms'):
                if key in event:
                    value = event[key]
                    record[key] = value if type(value) is int and 0 <= value <= 1000000 else None
            if isinstance(event.get('game'), dict):
                record['game'] = event['game']
                self.check_room_compatibility(record)
            if event.get('title'):
                record['title'] = event['title']
        elif event.get('type') == 'ready':
            record['chatState'] = '在线'
            record['bridgeStatus'] = str(event.get('bridge', record['bridgeStatus']))[:160]
        elif event.get('type') == 'message':
            account = event.get('account')
            if isinstance(account, str) and re.fullmatch('[0-9a-f]{32}\\.[0-9a-f]{32}', account):
                friend = next((c['name'] for c in self._state['contacts'] if c.get('account') == account), None)
                event = dict(event, identityLabel=('好友账号 · ' + friend if friend else '账号 · ' + account[:8]))
            else:
                event = dict(event, identityLabel='未验证账号')
            messages = record['chatMessages']
            if not any(message.get('id') == event.get('id') for message in messages):
                messages.append(event)
                del messages[:-200]
        elif event.get('type') == 'bridge':
            record['bridgeStatus'] = str(event.get('status', ''))[:160]
        elif event.get('type') == 'offline':
            record['chatState'] = '重连中'
        elif event.get('type') == 'error':
            record['chatError'] = str(event.get('error', ''))[:160]
        self.publish_connections()

    @Slot(str, object)
    def finish_chat(self, name, future):
        record = self.records.get(name)
        if not record or self.closed:
            return
        record['chatSending'] = False
        try:
            future.result()
            record.update(chatDraft='', chatError='')
        except Exception as exc:
            record['chatError'] = str(exc) or '消息发送失败，请检查聊天记录后重试。'
        self.publish_connections()

    @Slot(str, str, str)
    def update_status(self, name, state, detail):
        record = self.records.get(name)
        if not record:
            return
        if state in ('closed', 'stopped', 'error'):
            if self.pending_friend_invite and self.pending_friend_invite[2:] == (name,):
                self.pending_friend_invite = None
                self.patch(pendingFriendInvite='', socialError='房间未能保持连接，未发送好友邀请。请创建房间后重新邀请。')
            self.forget_room(name, detail if state != 'stopped' else '已退出房间。')
            return
        if state == 'warning':
            record['warning'] = detail
        else:
            record.update(state=state, detail=detail)
            if state in ('stopped', 'error', 'reconnecting'):
                record['chatState'] = '已断开'
        endpoint = self.service.endpoints.get(name)
        if endpoint and endpoint.room_info:
            record['availability'] = endpoint.room_info.get('availability', record.get('availability', 'ready'))
            record['title'] = endpoint.room_info.get('title', record['title'])
            record['game'] = endpoint.room_info.get('game', record.get('game', {}))
            record['public'] = endpoint.room_info.get('public', False)
            record['requireInvite'] = endpoint.room_info.get('require_invite', not record['public'])
            self.check_room_compatibility(record)
        self.publish_connections()

        if (state == 'online' and record.get('availability', 'ready') == 'ready'
                and self.pending_friend_invite
                and self.pending_friend_invite[0] == self.social_generation
                and self.pending_friend_invite[2:] == (name,)):
            account = self.pending_friend_invite[1]
            self.pending_friend_invite = None
            self.patch(pendingFriendInvite='')
            try:
                self.invite_friend(account)
            except (ValueError, OSError) as exc:
                self.patch(socialError='房间已创建，但邀请未发送：' + str(exc))

    def check_room_compatibility(self, record):
        remote = record.get('game') or {}
        if record.get('role') == 'host' or not remote.get('version'):
            record['compatibility'] = ''
            return
        if not self.game.get('version'):
            record['compatibility'] = '还没有选择游戏配置'
            return
        errors, warnings = compatibility(self.game, remote)
        record['compatibility'] = '、'.join(errors or warnings)

    def launch_room(self):
        name = self._state['selected']
        record = self.records.get(name)
        endpoint = self.service.endpoints.get(name)
        page = self.launcher_page
        if not record or not endpoint or record['state'] != 'online':
            raise ValueError('房间尚未连接。')
        if record.get('availability') == 'waiting' and record['role'] != 'host':
            raise ValueError('房主不在游戏内，请等待世界重新开放。')
        if record.get('compatibility'):
            raise ValueError('游戏配置与房间不符；请选择匹配配置或准备新配置。')
        if page.current_client or self.external_running or getattr(page.launcher, 'running', False):
            self.patch(notice='游戏已经运行。请进入世界并对局域网开放。' if record['role'] == 'host' else
                       '游戏已经运行。请在多人游戏列表中选择这个房间，或复制地址连接。')
            return
        if not page.auth_manager.is_authenticated():
            raise ValueError('请先在首页设置正版或离线角色，然后启动游戏。')
        page.started_game(server=f'127.0.0.1:{endpoint.listen_port}' if record['role'] == 'client' else None)
        self.patch(notice='游戏正在启动，将自动进入房间。' if record['role'] == 'client' else
                   '游戏正在启动。进入世界后对局域网开放，即可让朋友加入。')

    def sync_room_version(self):
        name = self._state['selected']
        record = self.records.get(name)
        endpoint = self.service.endpoints.get(name)
        if not record or not endpoint or record['role'] != 'host':
            raise ValueError('只有房主可以更新房间版本。')
        if self._state['instanceLocked']:
            raise ValueError('正在运行的游戏版本不能更改。')
        self.require_instance()
        self.job('syncgame:' + name, endpoint.update_game(self.game))
        self.patch(busy=True)

    def prepare_room(self):
        name = self._state['selected']
        record = self.records.get(name)
        endpoint = self.service.endpoints.get(name)
        page = self.launcher_page
        if not record or not endpoint or record['role'] != 'client' or record['state'] != 'online':
            raise ValueError('请先加入一个房间。')
        if page.current_client or self.external_running or getattr(page.launcher, 'running', False):
            raise ValueError('请先退出正在运行的游戏，再准备新的游戏配置。')
        if record['preparing']:
            return
        settings = page.settings_manager
        directory = settings.get_setting('minecraft.directory.enable')
        if not directory:
            raise ValueError('请先在设置中选择游戏目录。')
        from hookup.preparation import prepare_configuration
        cancel = threading.Event()
        self.preparations[name] = cancel
        record.update(preparing=True, prepareStatus='正在核对房间文件…', prepareProgress=0,
                      prepareMaximum=0)
        self.publish_connections()
        def report(status, done, total):
            self.preparation_progress.emit(name, str(status)[:160], done, total)
        java = settings.get_version_setting('java.path', None)
        source = settings.get_setting('settings.general.mirrors', '自动')
        self.job('prepare:' + name, prepare_configuration(endpoint, directory, java, source, cancel, report))

    @Slot(str, str, object, object)
    def update_preparation(self, name, status, done, total):
        record = self.records.get(name)
        if record and record.get('preparing'):
            record.update(prepareStatus=status, prepareProgress=done, prepareMaximum=total)
            self.publish_connections()

    def forget_room(self, name, notice):
        cancel = self.preparations.get(name)
        if cancel:
            cancel.set()
        self.records.pop(name, None)
        if name in self.service.endpoints:
            self.service.remove(name)
        if self._state['selected'] == name:
            self.patch(selected='', page='connections' if self.records else 'hall', notice=notice, error='')
        else:
            self.patch(notice=notice)
        self.publish_connections()

    def refresh_friends(self):
        if self.closed:
            return
        profile = None
        try:
            profile = self.profile()
            from hookup.social import credential, status
            credential(profile)
        except ExpiredNodeCredential:
            self.mark_node_expired()
            return
        except Exception as error:
            self.patch(contacts=[], friendRequests=[], friendInvitations=[], socialReady=False,
                       socialAccount='', socialName='', socialLoading=False,
                       socialError=str(error) if profile and profile.token.startswith('acct1.') else '')
            return
        path = self.node_path
        if not self._state['socialReady']:
            self.patch(socialLoading=True)
        async def check():
            return dict(path=path, state=await status(profile))
        self.job('socialstatus:' + self.social_generation + ':' + path, check())

    def social_operation(self, operation, account, **fields):
        if not self._state['socialReady']:
            raise ValueError('请先登录节点账号。')
        from hookup.social import operate
        path, profile = self.node_path, self.profile()
        self.patch(friendBusy=True, socialError='')
        async def perform():
            return dict(path=path, operation=operation, target=account,
                        state=await operate(profile, operation, account, **fields))
        self.job('socialop:' + self.social_generation + ':' + uuid.uuid4().hex, perform())

    def invite_friend(self, account):
        if not self._state['socialReady']:
            raise ValueError('请先登录节点账号。')
        friend = next((item for item in self._state['contacts'] if item['account'] == account), None)
        if not friend or not friend['online']:
            raise ValueError('好友当前不在线，请在对方上线后邀请。')
        candidates = [name for name, record in self.records.items()
                      if record.get('role') == 'host' and record['state'] == 'online'
                      and record.get('availability', 'ready') == 'ready']
        selected = self._state['selected']
        name = selected if selected in candidates else next(iter(candidates), '')
        endpoint = self.service.endpoints.get(name)
        if endpoint is None or not endpoint.connection:
            self.require_available_node()
            self.navigate('create')
            self.pending_friend_invite = (self.social_generation, account)
            self.patch(pendingFriendInvite=friend['name'],
                       notice='先创建并开放房间，成功后会自动邀请 ' + friend['name'] + '。')
            return
        outgoing = dict(self._state['outgoingInvitations'])
        outgoing[account] = dict(status='发送中…', room=endpoint.invite.room_id, at=time.time())
        self.patch(outgoingInvitations=outgoing)
        self.social_operation('invite', account, room=endpoint.invite.room_id)

    def apply_social_state(self, state):
        import re
        if (not isinstance(state, dict) or not isinstance(state.get('account'), str) or
                not re.fullmatch(r'[0-9a-f]{32}\.[0-9a-f]{32}', state['account']) or
                not isinstance(state.get('username'), str)):
            raise ValueError('好友服务返回的数据无效。')
        for group, limit in (('friends',64), ('requests',128), ('invitations',256)):
            entries = state.get(group)
            if not isinstance(entries, list) or len(entries) > limit:
                raise ValueError('好友服务返回的数据无效。')
            for entry in entries:
                if (not isinstance(entry, dict) or not isinstance(entry.get('account'), str) or
                        not re.fullmatch(r'[0-9a-f]{32}\.[0-9a-f]{32}', entry['account']) or
                        not isinstance(entry.get('username'), str) or
                        not re.fullmatch('[A-Za-z0-9_-]{3,32}', entry['username'])):
                    raise ValueError('好友服务返回的数据无效。')
        contacts = [dict(name=c['username'], account=c['account'], online=c.get('online') is True,
                         index=i) for i,c in enumerate(state['friends'])]
        invitations = [item for item in state['invitations'] if isinstance(item.get('id'), str)
                       and item['id'] not in self.ignored_friend_invitations]
        previous = self.seen_friend_invitations
        unseen = [item for item in invitations if item['id'] not in previous]
        self.seen_friend_invitations.update(item['id'] for item in invitations)
        live_ids = {item['id'] for item in state['invitations'] if isinstance(item.get('id'), str)}
        self.seen_friend_invitations.intersection_update(live_ids)
        self.ignored_friend_invitations.intersection_update(live_ids)
        outgoing = {account: dict(item, status='邀请已过期，请重新邀请')
                    if time.time() - item['at'] >= 300 else item
                    for account, item in self._state['outgoingInvitations'].items()}
        self.patch(contacts=contacts, friendRequests=state['requests'], friendInvitations=invitations,
                   socialReady=True, socialLoading=False, socialAccount=state['account'],
                   socialName=state['username'], socialError='', outgoingInvitations=outgoing)
        for invitation in unseen:
            self.friend_invited.emit(dict(invitation))

    def lookup_friend(self, data):
        if not self._state['socialReady']:
            raise ValueError('匿名接入没有好友功能，请在节点网页登录并领取个人接入码。')
        identifier = str(data.get('identifier', '')).strip()
        if not re.fullmatch('[A-Za-z0-9_-]{3,32}', identifier):
            raise ValueError('请输入有效的用户名。')
        path, profile = self.node_path, self.profile()
        key = 'friendlookup:' + uuid.uuid4().hex
        self.friend_request = dict(key=key, node=path)
        self.patch(friendBusy=True)
        async def lookup_and_request():
            values = await lookup_account(profile, identifier)
            if len(values) != 1:
                raise ValueError('找不到唯一匹配的用户名，请核对拼写后重试。')
            from hookup.social import operate
            return await operate(profile, 'request', values[0]['account'])
        self.job(key, lookup_and_request())

    def cancel_friend_lookup(self):
        self.friend_request = None
        self.patch(friendBusy=False)

    @Slot(str, object, object)
    def finish(self, key, value, error):
        self.jobs.discard(key)
        if key == 'diagnostics':
            self.patch(error='日志导出失败：' + error if error else '',
                       notice='' if error else '网络与游戏诊断日志已导出：' + str(value))
            return
        if key == 'runtime':
            self.runtime_job = False
            running = value[0] if not error and len(value) == 1 else None
            if running != self.external_running:
                self.external_running = running
                self.detect_instance()
            return
        if key.startswith('manifest:'):
            record = self.records.get(key[9:])
            if record:
                record['mods'] = value if not error else []
                record['modError'] = error or ''
                self.publish_connections()
            return
        if key.startswith('syncgame:'):
            record = self.records.get(key[9:])
            if record and not error:
                record['game'] = value
            self.patch(busy=False, error=error or '', notice='' if error else '房间版本已同步，玩家已收到更新。')
            self.publish_connections()
            return
        if key.startswith('prepare:'):
            name = key[8:]
            self.preparations.pop(name, None)
            record = self.records.get(name)
            if record:
                record['preparing'] = False
                record['prepareStatus'] = error or '配置已安装，正在启动游戏…'
                self.publish_connections()
            if error:
                self.patch(error='配置准备失败：' + error)
                return
            try:
                if not record:
                    return
                self.detect_instance()
                self.select_instance(value)
                self.detect_instance()
                # Metadata refresh is asynchronous. The selected room is now
                # isolated and verified; startup uses its local proxy address.
                endpoint = self.service.endpoints.get(name)
                page = self.launcher_page
                if endpoint and page.auth_manager.is_authenticated() and record.get('availability') != 'waiting':
                    page.started_game(server=f'127.0.0.1:{endpoint.listen_port}')
                    self.patch(notice='配置已准备完成，游戏正在启动并连接房间。')
                else:
                    self.patch(notice='配置已准备完成。等待房主开放世界后，可以快速启动。' if record.get('availability') == 'waiting'
                               else '配置已准备完成。请在首页设置角色后点击快速启动。')
            except Exception as exc:
                self.patch(error=str(exc))
            return
        if key.startswith('retarget:'):
            if key[9:] not in self.records:
                return
            self.patch(busy=False, error=error or '',
                       page='worldPicker' if error else 'connected',
                       notice='' if error else '世界已重新开放，朋友可以重新进入游戏。')
            return
        if key.startswith('rooms:'):
            if key.startswith('rooms:' + self.room_generation + ':'):
                first = key.rsplit(':', 1)[1] == '0'
                if not error and value.get('node_name') and self.store:
                    self.store.data['node_names'][self.node_path] = value['node_name']
                    self.store.save()
                    self.reload_store()
                if error:
                    self.patch(loading=False, loadingMore=False,
                               nodeAvailable=False, nodeLatencyMs=None, roomError='暂时无法连接节点，请检查网络后重试。')
                else:
                    rooms = [] if first else list(self._state['rooms'])
                    seen = {room['id'] for room in rooms}
                    for room in value['rooms']:
                        if room['id'] not in seen:
                            rooms.append(room)
                            seen.add(room['id'])
                    self.patch(loading=False, loadingMore=False, nodeAvailable=True, rooms=rooms,
                               nodeLatencyMs=self.valid_latency(value.get('node_latency_ms')),
                               roomNext=value['next'], roomTotal=value['total'], roomError='')
            return
        if key.startswith('nodehealth:'):
            if key == 'nodehealth:' + self.node_check_generation:
                self.patch(nodeAvailable=not bool(error),
                           nodeLatencyMs=None if error else self.valid_latency(value),
                           roomError='暂时无法连接节点，请检查网络后重试。' if error else '')
            return
        if key.startswith('socialstatus:') or key.startswith('socialop:'):
            if key.split(':', 2)[1] != self.social_generation:
                return
            if error:
                outgoing = {account: dict(item, status='发送失败，重试') if item.get('status') == '发送中…' else item
                            for account, item in self._state['outgoingInvitations'].items()}
                self.patch(socialError=str(error), friendBusy=False, socialLoading=False, outgoingInvitations=outgoing)
                if key.startswith('socialstatus:'):
                    self.patch(socialReady=False, socialAccount='', socialName='', contacts=[], friendRequests=[], friendInvitations=[])
                self.friend_finished.emit(False, str(error)) if key.startswith('socialop:') else None
                return
            if value['path'] != self.node_path:
                return
            try:
                if value.get('operation') == 'join':
                    self.join(value['state']['invite'])
                    self.ignored_friend_invitations.update(item['id'] for item in self._state['friendInvitations']
                                                           if item['account'] == value.get('target'))
                    self.patch(friendInvitations=[item for item in self._state['friendInvitations']
                                                  if item['id'] not in self.ignored_friend_invitations])
                    self.window.showNormal()
                    self.window.raise_()
                    self.window.activateWindow()
                else:
                    self.apply_social_state(value['state'])
                self.patch(friendBusy=False)
                if key.startswith('socialop:'):
                    if value.get('operation') == 'invite':
                        outgoing = dict(self._state['outgoingInvitations'])
                        account = value.get('target')
                        if account:
                            outgoing[account] = dict(outgoing[account], status='已发送')
                        self.patch(outgoingInvitations=outgoing, notice='邀请已发送，对方会在好友窗口收到提醒。')
                        self.friend_finished.emit(True, '已发送联机邀请。')
                    else:
                        self.friend_finished.emit(True, '已更新。')
            except Exception as exc:
                self.patch(friendBusy=False, socialError=str(exc))
                self.friend_finished.emit(False, str(exc))
            return
        if key.startswith('friendlookup:'):
            pending = self.friend_request
            if not pending or key != pending['key']:
                return
            self.friend_request = None
            self.patch(friendBusy=False)
            if pending['node'] != self.node_path:
                return
            try:
                if error:
                    raise ValueError(str(error))
                self.apply_social_state(value)
                self.friend_finished.emit(True, '好友申请已发送，请等待对方同意。')
            except Exception as exc:
                self.friend_finished.emit(False, str(exc))
            return
        if key.startswith('nodecode:'):
            if key != 'nodecode:' + self.generation:
                return
            if error:
                self.patch(busy=False, error='添加失败：无法验证节点身份或连接，请检查添加码和网络。', notice='')
                return
            try:
                if not self.store:
                    raise ValueError('请先修复本地配置。')
                profile = value
                matches = self.matching_nodes(profile)
                if matches:
                    self.pending_node_update = profile
                    personal = profile.token.startswith('acct1.')
                    message = ('此节点已添加。是否用新的个人接入码更新？更新后立即重新验证账号并加载好友。'
                               if personal else '此节点已添加。是否更新为匿名接入码？更新后此节点将无法使用账号好友功能。')
                    self.patch(busy=False, nodeUpdatePrompt=True, nodeUpdateMessage=message, notice='')
                else:
                    self.save_verified_node(profile)
            except Exception as exc:
                self.patch(busy=False, error=str(exc), notice='')
            return
        if key.startswith('instance:'):
            if key != getattr(self, 'instance_job', None):
                return
            self.game = {} if error else value
            self.patch(version=self.game.get('version', ''), loader=self.game.get('loader', 'vanilla'),
                       loaderVersion=self.game.get('loader_version', ''), instanceLoading=False,
                       instanceError='所选实例读取失败，请在首页检查安装或切换实例。' if error else '')
            for record in self.records.values():
                self.check_room_compatibility(record)
            if not error and self.instance_source:
                for name, endpoint in list(self.service.endpoints.items()):
                    record = self.records.get(name)
                    if (record and endpoint.role == 'host' and record.get('availability') == 'waiting'
                            and record.get('game') != self.game):
                        self.job('syncgame:' + name, endpoint.update_game(self.game, self.instance_source[2]))
            self.publish_connections()
            if self.pending:
                self.patch(busy=False)
                if self.game.get('version'):
                    try:
                        self.continue_join()
                    except Exception as exc:
                        self.patch(error=str(exc))
                else:
                    self.patch(needsVersion=True)
            return
        if key.split(':', 1)[-1] != self.generation:
            return
        self.patch(busy=False)
        if error:
            message = ('无法连接这个世界。请确认已对局域网开放，并检查端口。'
                       if key.startswith('probe:') else '操作未完成：' + error)
            self.patch(error=message)
            return
        if key.startswith('lan:'):
            self.patch(worlds=value, error='' if value else '没有找到世界。确认已对局域网开放，或手动填写端口。')
        elif key.startswith('probe:') and self.creation:
            detected = value.get('version', '')
            if re.fullmatch(r'\d+\.\d+(?:\.\d+)?', detected) and detected != self.creation['game']['version']:
                self.creation = None
                self.patch(error='查找到的世界与当前游戏实例版本不一致，请选择对应实例。')
                return
            self.creation['game']['protocol'] = value['protocol']
            self.patch(step=1, worldPort=value['port'], error='')
        elif key.startswith('resolve:'):
            if value['path'] != self.node_path:
                self.patch(error='节点已切换，请重新选择房间。')
                return
            if value['room'].get('require_invite', False):
                self.pending = None
                self.patch(invitePrompt=True, joinRoomId=value['room']['id'],
                           joinRoomTitle=value['room']['title'], error='', notice='', busy=False)
                return
            try:
                self.join(RoomInvite(value['secret']).encode())
            except Exception as exc:
                self.patch(error=str(exc))

    @Slot()
    def close(self):
        if not self.closed:
            self.closed = True
            self.room_search_timer.stop()
            self.friend_timer.stop()
            for cancel in self.preparations.values():
                cancel.set()
            self.service.close()
