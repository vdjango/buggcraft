"""Qt presentation state; all multiplayer I/O belongs to the C++ bridge."""
import asyncio
import hashlib
import json
import logging
import math
from pathlib import Path
import re
import threading
import time
import uuid
import webbrowser

from PySide6.QtCore import QObject, Property, Signal, Slot, QStandardPaths, QTimer, Qt
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

from hookup.profiles import RelayProfile, RoomInvite
from hookup.native_transport import TunnelHost, TunnelClient, TunnelService
from hookup.native_routes import manager as native_bridge
from hookup.rooms import instance_metadata, list_room_page, resolve_room, compatibility, lookup_account
from hookup.friend_codes import friend_code
from hookup.storage import LobbyStore
from hookup.nodes import probe, save_json, profile_data, remember, node_identity
from hookup.social import check_expiry, credential_expiry, ExpiredNodeCredential, EXPIRED_CODE_MESSAGE
from core.content_mirrors import configured_source
from utils.instances import installed_instance_ids, running_games, lan_world_token
from utils.clipboard import cancel_copy, copy_text
from ui.room_preparation import RoomPreparation


class MultiplayerController(RoomPreparation, QObject):
    changed = Signal()
    completed = Signal(str, object, object)
    network_type_detected = Signal(str, str)
    status = Signal(str, str, str)
    chat_event = Signal(str, object)
    chat_sent = Signal(str, object)
    preparation_progress = Signal(str, str, object, object)
    preparation_event = Signal(str, object)
    copied = Signal(str)
    friend_finished = Signal(bool, str)
    friend_invited = Signal(object)
    social_notification = Signal(str)
    route_changed = Signal(str, str)
    roomSettingsSaved = Signal()
    room_notification = Signal(str)

    def __init__(self, window, storage_path=None):
        super().__init__(window)
        self.window = window
        self.launcher_page = getattr(window, "launcher_page", None) or window.parent()
        self.service = TunnelService()
        self.jobs = set()
        self.feedback_dialog = None
        self.feedback_draft = ''
        self.game = {}
        self.pending = None
        self.creation = None
        self.quick_creation_data = None
        self.clipboard_invite = ''
        self.consumed_clipboard_invite = ''
        self.generation = uuid.uuid4().hex
        self.closed = False
        self.records = {}
        self.chat_state = '加入房间后连接'
        self.bridge_status = '游戏聊天同步由房主创建房间时设置。'
        self.node_path = ''
        self.friend_request = None
        self.social_path = ''
        self.social_identity = None
        self.social_failures = 0
        self.player_network_profile = {'type': 'unknown', 'direct_successes': 0, 'relay_successes': 0}
        self.player_network_profile_at = 0
        self.player_network_profile_task = None
        self.credential_prompted_node = ''
        self.credential_prompt_dialog = None
        self.social_generation = uuid.uuid4().hex
        self.pending_node_update = None
        self.device_login = None
        self.device_refresh_attempts = {}
        self.device_refresh_denied = set()
        self.device_login_timer = QTimer(self)
        self.device_login_timer.setInterval(1000)
        self.device_login_timer.timeout.connect(self.poll_device_login)
        self.device_refresh_timer = QTimer(self)
        self.device_refresh_timer.setInterval(60000)
        self.device_refresh_timer.timeout.connect(self.renew_device_login)
        self.device_refresh_timer.start()
        self.node_display_names = {}
        self.node_display_regions = {}
        self.pending_room_info = None
        self.pending_friend_invites = {}
        self.social_operations = {}
        from ui.social_notifications import SocialNotifications
        self.social_notifications = SocialNotifications()
        self.seen_friend_invitations = set()
        self.ignored_friend_invitations = set()
        self.instance_job = None
        self.instance_source = None
        self.preparations = {}
        self.preparation_tasks = {}
        self.pending_preparation_check = None
        self.external_running = None
        self.runtime_job = False
        self.auto_lan_job = False
        self.auto_lan_seen = set()
        self.auto_lan_absences = {}
        self.auto_lan_token = None
        self.room_generation = uuid.uuid4().hex
        self.node_check_generation = uuid.uuid4().hex
        self.room_search_timer = QTimer(self)
        self.room_search_timer.setSingleShot(True)
        self.room_search_timer.setInterval(300)
        self.room_search_timer.timeout.connect(self.refresh)
        self.init_preparation()
        self._state = dict(page='hall', step=0, nodes=[], nodeIndex=-1, nodeAvailable=False, nodeLatencyMs=None,
                           rooms=[], contacts=[], friendRequests=[], friendInvitations=[], friendLookupResults=[], socialAccount='', socialName='', socialReady=False, socialState='offline', socialError='',
                           playerNetworkProfile=dict(type='unknown', direct_successes=0, relay_successes=0), playerNetworkTypeReady=False, playerNetworkProfileReady=False,
                           connections=[], worlds=[], worldScanning=False, selected='', busy=False, friendBusy=False, socialLoading=False, loading=False,
                           openWorldPrompt=False, openWorldPort=0, openWorldMode='create',
                           pendingFriendInvite='', outgoingInvitations={}, friendInviteAccount='', joiningFriendAccount='',
                           joinRequests=[], socialCapabilities={}, requestedJoinAccount='',
                           nodeAccessExpired=False, nodeCredentialRequired=False, nodeAccessMessage='',
                           error='', notice='', roomError='', needsVersion=False,
                           deviceLoginBusy=False, deviceOrigin='https://node.bugg.icu', deviceManaged=False,
                           deviceLoginUrl='', deviceLoginStage='idle', deviceLoginMessage='',
                           joinRoomId='', joinRoomTitle='', invitePrompt=False,
                           transportPolicy='auto',
                           nodeUpdatePrompt=False, nodeUpdateMessage='',
                           roomQuery='', roomNext=None, roomTotal=None, loadingMore=False,
                           version='', loader='vanilla', loaderVersion='', localModsCount=0, worldPort=0,
                           instances=[], instanceId='', instanceLoading=False, instanceError='',
                           instanceLocked=False, chatMessages=[], chatState=self.chat_state,
                           bridgeStatus=self.bridge_status, chatError='', chatDraft='', chatSending=False)
        start_page = self.launcher_page
        main_window = getattr(start_page, 'parent', None)
        cache = getattr(main_window, 'cache_path', None)
        from utils.storage_paths import cache_directory
        root = Path(cache) / 'multiplayer' if cache else cache_directory('multiplayer')
        try:
            self.store = LobbyStore(storage_path or root / 'lobby.json')
        except (OSError, ValueError) as exc:
            self.store = None
            self._state['notice'] = '本地配置未能读取，原文件已保留：' + str(exc)
        self.completed.connect(self.finish)
        self.network_type_detected.connect(self.update_network_type)
        self.status.connect(self.update_status)
        self.chat_event.connect(self.update_chat)
        self.chat_sent.connect(self.finish_chat)
        self.preparation_progress.connect(self.update_preparation)
        self.preparation_event.connect(self.update_preparation_event)
        self.route_changed.connect(self.show_route_tip)
        QApplication.instance().aboutToQuit.connect(self.close)
        self.reload_store()
        self.friend_timer = QTimer(self)
        self.friend_timer.setInterval(5000)
        self.friend_timer.timeout.connect(self.refresh_friends)
        self.friend_timer.start()
        self.network_profile_timer = QTimer(self)
        self.network_profile_timer.setInterval(600000)
        self.network_profile_timer.timeout.connect(self.refresh_network_profile)
        self.network_profile_timer.start()
        self.refresh_network_profile()

    @Property('QVariantMap', notify=changed)
    def view(self):
        self._state['defaultRoomTitle'] = self.default_room_title()
        owner = self._state.get('socialAccount') or self.node_path
        preferences = self.store.data.get('friend_preferences', {}).get(owner, {}) if self.store else {}
        contacts = [dict(contact, **preferences.get(contact['account'], {}))
                    for contact in self._state['contacts']]
        pending = self.pending_friend_invite
        pending_name = next((c.get('alias') or c['name'] for c in contacts if pending and c['account'] == pending[1]), '')
        short_codes = self._state.get('socialCapabilities', {}).get('friend_code') is True
        contacts = [dict(c, friendCode=friend_code(c['account']) if short_codes else c['account']) for c in contacts]
        candidates = [dict(c, friendCode=friend_code(c['account'])) if short_codes else c
                      for c in self._state.get('friendLookupResults', [])]
        account = self._state.get('socialAccount', '')
        return dict(self._state, contacts=contacts, friendLookupResults=candidates,
                    friendEntryAvailable=self.friend_entry_available(),
                    socialFriendCode=friend_code(account) if account and short_codes else account,
                    friendInviteFlow=self.friend_invite_flow(contacts),
                    pendingFriendInvite=pending_name, pendingFriendInviteCount=len(self.pending_friend_invites),
                    socialMutationBusy=bool(self.friend_request) or any(item[0] != 'invite' for item in self.social_operations.values()),
                    friendNotifications=self.social_notifications.view(self._state))

    def friend_entry_available(self):
        # A configured personal account has an entry even before its first
        # successful request. Availability of the service is reported separately.
        selected = next((node for node in self._state['nodes'] if node['path'] == self.node_path), {})
        return bool(selected.get('personalCode') or self._state['socialAccount'] or
                    self._state['socialReady'] or self._state['socialLoading'])

    def social_failure(self, source, error):
        self.social_failures += 1
        reason = str(error).lower()
        credential_required = any(text in reason for text in (
            'personal launcher credential is required', 'personal credential expired',
            'invalid personal credential', 'invalid delegated key', 'delegated key mismatch',
            'node authentication failed', '匿名接入没有好友功能'))
        logging.getLogger('hookup.social').warning(
            'social_ui_sync_failed source=%s consecutive=%s contacts=%s ready=%s entry_available=%s',
            source, self.social_failures, len(self._state['contacts']), self._state['socialReady'],
            self.friend_entry_available())
        contacts = [dict(item, online=False, presenceStale=True) for item in self._state['contacts']]
        device_managed = bool(self.node_path and Path(self.node_path + '.device.json').is_file())
        self.patch(socialLoading=False, socialState='stale', contacts=contacts,
                   nodeCredentialRequired=credential_required or self._state['nodeCredentialRequired'],
                   socialError=('节点账号登录已失效，请在浏览器重新登录并授权此设备。'
                                if credential_required else '好友节点同步失败：' + str(error)))
        if credential_required:
            self.prompt_node_credential_update()

    @staticmethod
    def operation_error(error):
        text = str(error or '')
        if 'room directory unavailable' in text.lower():
            return '暂时无法连接房间目录。请刷新或切换在线节点后重试；若同时提示登录失效，请在浏览器重新登录。'
        return text

    def prompt_node_credential_update(self):
        device_managed = bool(self.node_path and Path(self.node_path + '.device.json').is_file())
        if device_managed and self.renew_device_login():
            return
        if not self.node_path or self.credential_prompted_node == self.node_path:
            return
        if self.credential_prompt_dialog is not None:
            self.credential_prompt_dialog.close()
        self.credential_prompted_node = self.node_path
        path = self.node_path
        title = '节点账号需要重新登录'
        message = ('此设备的节点账号登录已失效或无法通过验证。\n\n'
                   '请到“联机节点”页，使用原节点的 HTTPS 地址重新通过浏览器登录并授权此设备。'
                   '原节点配置不会删除。')
        action = '前往重新登录'
        box = QMessageBox(QMessageBox.Warning, title, message, QMessageBox.NoButton, self.window)
        replace = box.addButton(action, QMessageBox.AcceptRole)
        box.addButton('稍后', QMessageBox.RejectRole)
        box.setWindowModality(Qt.NonModal)
        self.credential_prompt_dialog = box
        def finish(result):
            if self.credential_prompt_dialog is box:
                self.credential_prompt_dialog = None
            if box.clickedButton() is replace and self.node_path == path:
                self.act('reloginNode', {})
            box.deleteLater()
        box.finished.connect(finish)
        box.show()

    @property
    def pending_friend_invite(self):
        focused = getattr(self, '_state', {}).get('friendInviteAccount')
        return self.pending_friend_invites.get(focused) or next(iter(self.pending_friend_invites.values()), None)

    @pending_friend_invite.setter
    def pending_friend_invite(self, value):
        if value is None:
            self.pending_friend_invites.clear()
        else:
            self.pending_friend_invites[value[1]] = value

    def friend_invite_flow(self, contacts):
        """Keep the next step visible until an invitation finishes or is cancelled."""
        account = self._state.get('friendInviteAccount', '')
        outgoing = self._state['outgoingInvitations'].get(account)
        if not account or not outgoing:
            return {}
        friend = next((c for c in contacts if c['account'] == account), {})
        flow = dict(account=account, friend=friend.get('alias') or friend.get('name') or '好友',
                    stage='error', step=2, title='邀请未发送',
                    detail='请检查房间与网络后重试。', action='retry')
        pending = self.pending_friend_invites.get(account)
        if pending and pending[1] == account:
            record = self.records.get(pending[2], {}) if len(pending) > 2 else {}
            if not record:
                flow.update(stage='create', step=0, title='先创建房间，邀请还未发送',
                            detail='选好世界并创建房间后，自动发送邀请。', action='continue')
            elif record.get('availability') == 'waiting' and record.get('state') == 'online':
                flow.update(stage='waiting', step=1, title='等待你在游戏中开放世界',
                            detail='进入世界 → 暂停菜单 → 对局域网开放，完成后自动邀请。', action='continue')
            else:
                flow.update(stage='connecting', step=0, title='正在连接房间，邀请还未发送',
                            detail='连接成功且世界开放后，自动发送邀请。', action='continue')
        elif outgoing['status'] == '发送中…':
            flow.update(stage='sending', title='正在发送邀请…',
                        detail='房间已就绪，正在通知好友。', action='')
        elif outgoing['status'] == '已发送':
            flow.update(stage='sent', step=3, title='邀请已发送，等待好友加入',
                        detail='对方会在好友窗口收到提醒。', action='dismiss')
        elif outgoing['status'] == '邀请已过期，请重新邀请':
            flow.update(title='邀请已过期', detail='好友还未加入，可以重新发送邀请。')
        if len(self.pending_friend_invites) > 1 and pending:
            flow['detail'] = '共 ' + str(len(self.pending_friend_invites)) + ' 位好友，房间就绪后分别发送邀请。'
        return flow

    def default_room_title(self):
        current = getattr(getattr(self.launcher_page, 'auth_manager', None), 'current', None)
        username = getattr(current, 'username', '')
        username = username.strip() if isinstance(username, str) else ''
        return (username or '玩家')[:77] + '的房间'

    def join_from_clipboard(self):
        if self.closed or self._state['connections'] or self._state['busy']:
            return
        if self.launcher_page and self.launcher_page.settings_manager.get_setting('multiplayer.quick_action', '首页提示') == '关闭':
            self.clipboard_invite = ''
            return
        if self._state['page'] not in ('hall', 'join', 'nodes'):
            return
        text = QApplication.clipboard().text().strip()
        try:
            RoomInvite.decode(text)
        except ValueError:
            self.clipboard_invite = ''
            return
        if text == self.consumed_clipboard_invite:
            return
        self.clipboard_invite = text
        if not self._state['nodeAvailable']:
            self.patch(notice='已识别房间邀请码，节点连接成功后自动加入。')
            if not self.node_path:
                self.patch(page='nodes')
            return
        self.clipboard_invite = ''
        self.consumed_clipboard_invite = text
        self.act('join', {'invite': text})

    def patch(self, **values):
        self._state.update(values)
        self.changed.emit()

    @staticmethod
    def valid_latency(value):
        return (round(value, 1) if type(value) in (int, float) and
                math.isfinite(value) and value >= 0 else None)

    def reload_store(self, select=None, refresh_identity=False):
        nodes = []
        profiles = {}
        previous = {node['path']: node for node in self._state['nodes']}
        for path in self.store.data['nodes'] if self.store else []:
            personal_code = False
            expired = False
            try:
                profile = RelayProfile.load(path)
                profiles[path] = profile
                title = self.store.data['node_names'].get(path, '社区节点')
                personal_code = profile.token.startswith('acct1.')
                expiry = credential_expiry(profile)
                expired = expiry is not None and expiry <= time.time()
            except (OSError, ValueError, TypeError) as exc:
                title = '配置不可用 · ' + Path(path).name
                # A failed read does not establish a new identity. Retain the
                # last verified capability until the configuration can be read.
                personal_code = previous.get(path, {}).get('personalCode', False)
                expired = previous.get(path, {}).get('codeExpired', False)
                logging.getLogger('hookup.social').warning(
                    'social_profile_read_failed error_type=%s selected=%s retained_identity=%s',
                    type(exc).__name__, path == self.node_path, path in previous)
            nodes.append({'title': title, 'path': path, 'personalCode': personal_code,
                          'codeExpired': expired, 'deviceManaged': Path(path + '.device.json').is_file()})
        paths = [node['path'] for node in nodes]
        target = select or self.node_path
        index = paths.index(target) if target in paths else (0 if paths else -1)
        self.patch(nodes=nodes, nodeIndex=index)
        self.patch(nodeAccessExpired=bool(index >= 0 and nodes[index]['codeExpired']),
                   nodeAccessMessage=EXPIRED_CODE_MESSAGE if index >= 0 and nodes[index]['codeExpired'] else '')
        new_path = paths[index] if index >= 0 else ''
        device_managed = bool(new_path and Path(new_path + '.device.json').is_file())
        device_origin = 'https://node.bugg.icu'
        if device_managed:
            try:
                from hookup.device_login import validate_origin
                metadata = json.loads(Path(new_path + '.device.json').read_text(encoding='utf-8'))
                device_origin = validate_origin(metadata['origin'])
            except (OSError, ValueError, TypeError, KeyError):
                device_origin = ''
        if (new_path != self.node_path or refresh_identity or
                device_managed != self._state['deviceManaged']):
            self.patch(deviceManaged=device_managed, deviceOrigin=device_origin)
        if new_path != self.node_path or refresh_identity:
            self.node_path = new_path
            self.patch(rooms=[], roomError='', nodeAvailable=False)
            self.refresh()
        profile = profiles.get(new_path)
        if not new_path:
            identity = None
        elif profile is not None:
            identity = (new_path, hashlib.sha256(profile.token.encode()).hexdigest())
        else:
            identity = self.social_identity if new_path == self.social_path else (new_path, None)
        if identity != self.social_identity or (refresh_identity and profile is not None):
            logging.getLogger('hookup.social').info(
                'social_identity_reset reason=%s profile_read=%s contacts=%s',
                'explicit_refresh' if refresh_identity else 'verified_identity_change',
                profile is not None, len(self._state['contacts']))
            self.social_identity = identity
            self.social_failures = 0
            self.credential_prompted_node = ''
            if self.credential_prompt_dialog is not None:
                self.credential_prompt_dialog.close()
            self.social_generation = uuid.uuid4().hex
            from ui.social_notifications import SocialNotifications
            self.social_notifications = SocialNotifications()
            self.pending_friend_invite = None
            self.social_operations.clear()
            self.seen_friend_invitations.clear()
            self.ignored_friend_invitations.clear()
            self.friend_request = None
            self.social_path = new_path
            self.patch(contacts=[], friendRequests=[], friendInvitations=[], friendLookupResults=[], socialAccount='', socialName='', socialReady=False,
                       socialError='', nodeCredentialRequired=self._state['nodeAccessExpired'], friendBusy=False, socialLoading=False, pendingFriendInvite='', outgoingInvitations={},
                       friendInviteAccount='', joiningFriendAccount='', joinRequests=[], socialCapabilities={}, requestedJoinAccount='')
            self.refresh_friends()
            if self._state['nodeAccessExpired']:
                self.mark_node_expired()
        elif new_path and profile is None:
            self.social_failure('configuration', '节点配置读取失败，请检查文件权限或使用节点地址重新登录。')

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

    def copy_failed(self):
        self.patch(error='剪贴板暂时不可用，请再次点击复制。')

    @Slot(str, 'QVariantMap')
    def act(self, action, data):
        try:
            if action == 'moreMembers':
                self.more_members()
            elif action in ('requestMemberLogs', 'answerLogRequest', 'revokeLogAccess', 'viewMemberLogs'):
                self.log_action(action, data)
            elif action in ('kickMember', 'unblockMember', 'offerOwner', 'cancelOwner', 'answerOwner'):
                self.member_action(action, data)
            elif action == 'copyPrepareLog':
                record = self.records.get(self._state['selected'], {})
                text = '\n'.join(row['time'] + ' [' + row['category'] + '] ' + row['text']
                    for row in record.get('remoteLogs' if data.get('remote') else 'prepareLogs', []))
                copy_text(self, text, lambda: self.patch(notice='安装日志已复制。'), self.copy_failed)
            elif action == 'exportPrepareLog':
                path, _ = QFileDialog.getSaveFileName(self.window, '保存安装日志', 'room-install.log', '日志 (*.log)')
                if path:
                    record = self.records.get(self._state['selected'], {})
                    Path(path).write_text('\n'.join(row['time'] + ' [' + row['category'] + '] ' + row['text']
                        for row in record.get('remoteLogs' if data.get('remote') else 'prepareLogs', [])), encoding='utf-8')
                    self.patch(notice='安装日志已保存。')
            elif action == 'exportDiagnostics':
                from datetime import datetime
                from utils.diagnostics import export_connection_diagnostics
                path, _ = QFileDialog.getSaveFileName(self.window, '导出联机诊断日志',
                    'Buggcraft-diagnostics-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.zip',
                    'ZIP (*.zip)')
                if path:
                    if not path.lower().endswith('.zip'):
                        path += '.zip'
                    self.patch(notice='正在采集网络拓扑与游戏诊断日志…')
                    self.job('diagnostics', export_connection_diagnostics(path))
            elif action == 'submitDiagnostics':
                if 'feedback-upload' in self.jobs:
                    return
                if not self.node_path or not self._state['socialReady']:
                    raise ValueError('请先选择节点并使用个人账号登录')
                self.show_feedback()
            elif action == 'clearError':
                record = self.records.get(self._state['selected'])
                if record:
                    record['chatError'] = ''
                self.patch(error='', chatError='')
            elif action == 'openFriends':
                if not self.friend_entry_available():
                    raise ValueError('当前为匿名或未验证状态，请先在浏览器登录节点账号。')
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
                self.patch(busy=True, worldScanning=True, error='', worlds=[])
                excluded = [e.listen_port for e in self.service.endpoints.values() if e.role == 'client']
                async def discover():
                    result = await native_bridge().request('game.discover', {'exclude': excluded, 'duration_ms': 3000})
                    return result.get('worlds', [])
                self.job('lan:' + self.generation, discover())
            elif action == 'createFromOpenWorld':
                port = int(data.get('port') or self._state.get('openWorldPort') or 0)
                if port:
                    self.auto_lan_seen.add(port)
                if self._state.get('openWorldMode') == 'associate':
                    host = next(((name, record) for name, record in self.records.items()
                                 if record.get('role') == 'host' and record.get('availability') == 'waiting'), None)
                    if not host:
                        self.patch(openWorldPrompt=False, error='等待中的房间已关闭，请重新创建房间。')
                        return
                    if data.get('automatic'):
                        host[1]['automaticPublicGuide'] = True
                    self.patch(openWorldPrompt=False, page='connected', selected=host[0], worlds=[], error='', notice='')
                    self.act('applyWorld', {'port':port})
                    return
                already_open = self._state['page'] == 'create'
                self._state['pendingOpenWorldPort'] = port
                self.patch(openWorldPrompt=False, page='create', worlds=[], error='', notice='')
                if already_open:
                    self.act('discover', {})
            elif action == 'dismissOpenWorld':
                port = int(self._state.get('openWorldPort') or 0)
                if port:
                    self.auto_lan_seen.add(port)
                self.patch(openWorldPrompt=False, openWorldPort=0)
            elif action == 'probe':
                self.probe(data)
            elif action == 'quickCreate':
                self.require_available_node()
                self.require_instance()
                port = int(data.get('port') or 0)
                if port:
                    self.quick_creation_data = (self.generation, dict(data))
                    self.probe(data)
                else:
                    self.creation = {'path': self.node_path, 'game': dict(self.game), 'port': 0}
                    self._state['step'] = 1
                    self.create(data)
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
                self.pending_room_info = None
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
            elif action == 'updateRoomSettings':
                name = self._state['selected']
                record = self.records.get(name, {})
                endpoint = self.service.endpoints.get(name)
                if not endpoint or not record.get('isManager', record.get('role') == 'host') or record.get('state') != 'online':
                    raise ValueError('只有在线房主可以修改房间设置。')
                if self._state['busy']:
                    return
                title = str(data.get('title', '')).strip()
                public, require_invite = data.get('public'), data.get('requireInvite')
                if not title or len(title) > 80:
                    raise ValueError('房间名称需要 1–80 个字符。')
                if type(public) is not bool or type(require_invite) is not bool:
                    raise ValueError('请选择房间的加入方式。')
                allow_mod_transfer = data.get('allowModTransfer', bool(
                    (endpoint.room_settings or {}).get('allow_mod_transfer', False)))
                if type(allow_mod_transfer) is not bool:
                    raise ValueError('模组共享设置无效。')
                mod_transfer_limit_kib = data.get('modTransferLimitKib', int(
                    (endpoint.room_settings or {}).get('mod_transfer_limit_kib', 512)))
                if type(mod_transfer_limit_kib) is not int or not 64 <= mod_transfer_limit_kib <= 10240:
                    raise ValueError('模组上传限速需要在 64–10240 KiB/s 之间。')
                self.patch(busy=True, error='', notice='')
                self.job('configure:' + name, endpoint.update_settings(
                    title, public, require_invite, allow_mod_transfer, mod_transfer_limit_kib))
            elif action == 'dismissPublicGuide':
                record = self.records.get(self._state['selected'])
                if record:
                    record['publicGuide'] = False
                    self.publish_connections()
            elif action == 'prepareRoom':
                self.prepare_room(data.get('mode', 'fresh'))
            elif action == 'cancelPreparation':
                cancel = self.preparations.get(self._state['selected'])
                if cancel:
                    cancel.set()
            elif action == 'loadMods':
                name = self._state['selected']
                endpoint = self.service.endpoints.get(name)
                if endpoint:
                    if 'manifest:' + name in self.jobs:
                        return
                    self.records[name].update(modLoading=True, modError='')
                    self.publish_connections()
                    from hookup.modpack import fetch_manifest
                    self.job('manifest:' + name, fetch_manifest(endpoint))
            elif action == 'copyInvite':
                endpoint = self.service.endpoints.get(data['id'])
                if endpoint and self.records[data['id']]['state'] == 'online':
                    copy_text(self, endpoint.invite.encode(), lambda: self.copied.emit('invite'),
                              self.copy_failed)
            elif action == 'copyAddress':
                endpoint = self.service.endpoints.get(data['id'])
                if endpoint and endpoint.role == 'client' and endpoint.listener:
                    copy_text(self, f'127.0.0.1:{endpoint.listen_port}', lambda: self.copied.emit('address'),
                              self.copy_failed)
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
            elif action in ('setFriendFavorite', 'setFriendAlias'):
                account = str(data.get('account', ''))
                if not self.store or not any(c['account'] == account for c in self._state['contacts']):
                    raise ValueError('好友已不在列表中，请刷新后重试。')
                owner = self._state.get('socialAccount') or self.node_path
                if action == 'setFriendFavorite':
                    if type(data.get('favorite')) is not bool:
                        raise ValueError('收藏设置无效。')
                    self.store.set_friend_preference(owner, account, favorite=data['favorite'])
                    self.patch(error='', notice='已收藏好友。' if data['favorite'] else '已取消收藏。')
                else:
                    alias = str(data.get('alias', '')).strip()
                    if len(alias) > 32 or any(not c.isprintable() for c in alias):
                        raise ValueError('备注最多 32 个字符。')
                    self.store.set_friend_preference(owner, account, alias=alias)
                    self.patch(error='', notice='备注已保存。')
            elif action == 'copySocialName':
                if not self._state['socialReady']:
                    raise ValueError('好友服务连接成功后才能复制账号 ID。')
                account = self._state['socialAccount']
                copy_text(self, friend_code(account) if self._state.get('socialCapabilities', {}).get('friend_code') else account,
                          lambda: self.patch(error='', notice='好友码已复制，发给好友即可添加。'),
                          self.copy_failed)
            elif action == 'copyFriendName':
                friend = next((c for c in self._state['contacts'] if c['account'] == data.get('account')), None)
                if not friend:
                    raise ValueError('好友已不在列表中，请刷新后重试。')
                account = friend['account']
                copy_text(self, friend_code(account) if self._state.get('socialCapabilities', {}).get('friend_code') else account,
                          lambda: self.patch(error='', notice='好友码已复制。'), self.copy_failed)
            elif action == 'joinFriend':
                self.require_available_node()
                if any(record.get('state') not in ('stopped', 'error') for record in self.records.values()):
                    raise ValueError('请先退出当前房间，再接受新的联机邀请。')
                if not any(item['id'] == data['id'] and item['account'] == data['account']
                           for item in self._state['friendInvitations']):
                    raise ValueError('邀请已过期或已处理，请好友重新邀请。')
                self.patch(joiningFriendAccount=data['account'], notice='正在接受邀请并连接房间…', error='')
                try:
                    self.social_operation('join', data['account'], ref=data['id'])
                except (ValueError, OSError):
                    self.patch(joiningFriendAccount='', notice='')
                    raise
            elif action == 'ignoreFriendInvite':
                self.ignored_friend_invitations.add(data['id'])
                self.patch(friendInvitations=[item for item in self._state['friendInvitations']
                                              if item['id'] != data['id']])
            elif action == 'acknowledgeFriendHome':
                self.social_notifications.acknowledge_home(self._state)
                self.changed.emit()
            elif action == 'readFriendNotifications':
                if self.social_notifications.mark_read(self._state, data.get('kind')):
                    self.changed.emit()
            elif action == 'cancelFriendInvite':
                account = data.get('account') or self._state['friendInviteAccount']
                pending = self.pending_friend_invites.pop(account, None)
                outgoing = dict(self._state['outgoingInvitations'])
                if pending:
                    outgoing.pop(pending[1], None)
                self.patch(outgoingInvitations=outgoing)
                focused = next(iter(self.pending_friend_invites), '')
                self.patch(pendingFriendInvite='', friendInviteAccount=focused, notice='已取消这位好友的待发送邀请。')
            elif action == 'continueFriendInvite':
                pending = self.pending_friend_invites.get(data.get('account')) or self.pending_friend_invite
                if pending and len(pending) > 2 and pending[2] in self.records:
                    self.patch(page='connected', selected=pending[2])
                elif pending:
                    self.navigate('create')
            elif action == 'dismissFriendInvite':
                if not self.pending_friend_invite:
                    self.patch(friendInviteAccount='')
            elif action == 'acceptFriend':
                self.social_operation('accept', data['account'], ref=data['id'])
            elif action in ('declineFriend', 'removeFriend'):
                self.social_operation('remove', data['account'])
            elif action == 'inviteFriend':
                self.invite_friend(data['account'])
            elif action == 'requestJoinFriend':
                if not self._state['socialCapabilities'].get('join_requests'):
                    raise ValueError('当前节点尚未支持申请加入，请让好友发送联机邀请。')
                if any(r.get('state') not in ('stopped', 'error') for r in self.records.values()):
                    raise ValueError('你正在房间中，请先退出当前房间，再申请加入好友。')
                friend = next((c for c in self._state['contacts'] if c['account'] == data['account']), None)
                room = (friend or {}).get('room') or {}
                if not friend or not friend['online'] or not room.get('can_request'):
                    raise ValueError('好友还没有开放可加入的房间。')
                self.social_operation('request_join', data['account'], room=room['id'])
                self.patch(requestedJoinAccount=data['account'], notice='正在发送加入申请…')
            elif action in ('acceptJoinRequest', 'declineJoinRequest'):
                request = next((r for r in self._state['joinRequests'] if r.get('incoming') and
                                r['account'] == data['account'] and r['id'] == data['id']), None)
                if not request:
                    raise ValueError('加入申请已过期或已处理，请刷新列表。')
                self.social_operation('accept_join' if action == 'acceptJoinRequest' else 'decline_join',
                                      request['account'], ref=request['id'], room=request['room'])
            elif action == 'refreshFriends':
                self.refresh_friends()
            elif action in ('reloginNode', 'replaceNodeCode'):
                self.navigate('nodes')
                self.patch(notice='使用原节点的 HTTPS 地址，在浏览器重新登录并授权此设备。')
            elif action == 'editFriend':
                index = int(data['index'])
                contact = self.store.data['contacts'][index]
                self.patch(page='friendForm', error='', editIndex=index, friendName=contact['name'], friendAccount=contact.get('account', ''))
            elif action == 'loginOfficialDevice':
                self.login_official_device(bool(data.get('remember', True)), str(data.get('origin', 'https://node.bugg.icu')))
            elif action == 'deviceOrigin':
                self.patch(deviceOrigin=str(data.get('text', ''))[:320])
            elif action == 'cancelDeviceLogin':
                self.device_login = None
                self.device_login_timer.stop()
                self.device_login_generation = uuid.uuid4().hex
                self.patch(deviceLoginBusy=False, deviceLoginUrl='', deviceLoginStage='idle',
                           deviceLoginMessage='已取消本次登录。', busy=False, notice='已取消本次登录。')
            elif action == 'openDeviceBrowser':
                self.open_device_browser()
            elif action == 'copyDeviceLoginUrl':
                if self.device_login and self._state['deviceLoginUrl']:
                    copy_text(self, self._state['deviceLoginUrl'],
                              lambda: self.patch(deviceLoginMessage='登录链接已复制，请在浏览器打开并授权。'),
                              self.copy_failed)
            elif action == 'confirmNodeUpdate':
                pending = self.pending_node_update
                if pending:
                    self.pending_node_update = None
                    self.patch(nodeUpdatePrompt=False)
                    self.save_verified_node(pending)
            elif action == 'cancelNodeUpdate':
                self.pending_node_update = None
                self.patch(nodeUpdatePrompt=False, busy=False, notice='已取消更新，原节点配置继续保留。')
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
            self.quick_creation_data = None
            self.patch(error=str(exc) or '操作未完成，请重试。', busy=False, worldScanning=False)

    def navigate(self, page):
        if page not in ('hall', 'create', 'join', 'friends', 'friendForm', 'connections', 'connected', 'nodes'):
            return
        if (page == 'friends' and not self.friend_entry_available() or
                page == 'friendForm' and not self._state['socialReady']):
            raise ValueError('匿名接入没有好友功能，请先在浏览器登录节点账号。')
        if page in ('create', 'join'):
            self.require_available_node()
        if page == 'connected' and self._state['selected'] not in self.records:
            page = 'hall'
        if page == 'connections' and not self._state['connections']:
            page = 'hall'
        self.generation = uuid.uuid4().hex
        self.pending = self.creation = None
        self.quick_creation_data = None
        self.patch(page=page, error='', notice='', busy=False, worldScanning=False, step=0, needsVersion=False,
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
        if self.renew_device_login():
            self.patch(nodeAvailable=False, nodeAccessExpired=False, notice='正在自动恢复账号登录…')
            return
        if not self._state['nodeAccessExpired'] or self._state['socialReady']:
            logging.getLogger('hookup.social').warning('social_access_expired contacts=%s', len(self._state['contacts']))
        nodes = [dict(node, codeExpired=True) if node['path'] == self.node_path else node
                 for node in self._state['nodes']]
        device_managed = bool(self.node_path and Path(self.node_path + '.device.json').is_file())
        expired_message = ('节点账号登录已失效，请在浏览器重新登录并授权此设备。' if device_managed
                           else EXPIRED_CODE_MESSAGE)
        self.patch(nodes=nodes, nodeAccessExpired=True, nodeCredentialRequired=True,
                   nodeAccessMessage=expired_message,
                   nodeAvailable=False, socialReady=False, socialLoading=False,
                   contacts=[], friendRequests=[], friendInvitations=[],
                   socialAccount='', socialName='', socialError=expired_message,
                   roomError=expired_message, loading=False, loadingMore=False)
        self.prompt_node_credential_update()

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

    def save_verified_node(self, profile, *, reload=True):
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
        if reload:
            self.reload_store(self.node_path if self._state['connections'] else chosen, refresh_identity=True)
        notice = ('节点账号已更新，正在重新加载好友；现有房间保持连接，新身份用于后续联机。'
                  if profile.token.startswith('acct1.') else '匿名节点已保存；匿名接入不提供好友功能。')
        if self.node_path != chosen:
            notice = '节点已保存；当前房间结束后，切换到该节点即可使用新的接入身份。'
        self.patch(busy=False, error='', notice=notice)

    @Slot()
    def login_official_device(self, remember=True, origin='https://node.bugg.icu'):
        if self._state['deviceLoginBusy'] or self._state['busy']:
            return
        from hookup.device_login import validate_origin
        origin = validate_origin(origin)
        self.patch(deviceLoginBusy=True, deviceOrigin=origin, deviceLoginUrl='', deviceLoginStage='preparing',
                   deviceLoginMessage='正在连接节点并准备登录页面…', error='', notice='')
        async def begin():
            from hookup.device_login import begin
            import platform
            name = (platform.node() or 'Buggcraft PC')
            return await begin(name, remember, origin)
        self.device_login_generation = uuid.uuid4().hex
        self.job('device-login-start:' + self.device_login_generation, begin())

    def open_device_browser(self):
        if not self.device_login or not self._state['deviceLoginUrl']:
            return
        url = self._state['deviceLoginUrl']
        try:
            opened = webbrowser.open(url)
        except Exception:
            opened = False
        if not opened:
            try:
                opened = QDesktopServices.openUrl(QUrl(url))
            except Exception:
                opened = False
        self.patch(deviceLoginMessage=('已打开默认浏览器，请登录节点账号并授权；完成后会自动连接。' if opened else
                   '无法自动打开浏览器，请复制登录链接，在浏览器打开并授权。'))

    @Slot()
    def poll_device_login(self):
        if not self.device_login:
            self.device_login_timer.stop()
            return
        result, key, generation = self.device_login
        if 'device-login-poll:' + generation in self.jobs:
            return
        self.job('device-login-poll:' + generation, self._poll_device_login(result, key, generation))

    async def _poll_device_login(self, result, key, generation):
        from hookup.device_login import poll
        return await poll(result, key)

    @Slot()
    def renew_device_login(self):
        if self.closed or not self.node_path or self.node_path in self.device_refresh_denied:
            return False
        path = self.node_path
        metadata = Path(path + '.device.json')
        self.patch(deviceManaged=metadata.is_file())
        if not metadata.is_file():
            return False
        try:
            profile = RelayProfile.load(path)
            expiry = credential_expiry(profile)
        except Exception:
            return False
        if expiry is None or expiry > time.time() + 86400:
            return False
        key = 'device-refresh:' + path
        if key in self.jobs:
            return True
        if time.monotonic() - self.device_refresh_attempts.get(path, -120) < 60:
            return False
        self.device_refresh_attempts[path] = time.monotonic()
        from hookup.device_login import refresh
        self.job(key, refresh(path))
        return True

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
                result = await request(connection, 'ping')
                return result.get('node_latency_ms') if result.get('node_latency_method') == 'application-echo' else None
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

    def detect_instance(self, force=False):
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
        if not force and source == self.instance_source and not self._state['instanceError']:
            return
        self.instance_source = source
        self.game = {}
        self.creation = None
        self.generation = uuid.uuid4().hex
        self.instance_job = None
        self.patch(version='', loader='vanilla', loaderVersion='', localModsCount=0, step=0, busy=False,
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
        # The native scanner already probes Java listeners. Process command-line
        # detection must not prevent discovery (other launchers can hide it).
        waiting_hosts = [record for record in self.records.values()
                         if record.get('role') == 'host' and record.get('state') == 'online'
                         and record.get('availability') == 'waiting']
        quick_enabled = bool(waiting_hosts) or not page or page.settings_manager.get_setting('multiplayer.quick_action', '首页提示') != '关闭'
        if not quick_enabled and self._state['openWorldPrompt']:
            self.patch(openWorldPrompt=False, openWorldPort=0)
        if (quick_enabled and launcher and (waiting_hosts or len(getattr(launcher, 'sessions', [])) <= 1) and not self.closed and not self.auto_lan_job
                and (not self._state['connections'] or any(record.get('role') == 'host' and record.get('availability') == 'waiting'
                                                          for record in self.records.values()))):
            source = getattr(launcher, 'running_instance', None) or self.external_running or self.instance_source
            token = lan_world_token(source[2]) if source else None
            if token and token != self.auto_lan_token:
                self.auto_lan_token = token
                self.auto_lan_seen.discard(token[0])
                self.auto_lan_absences.pop(token[0], None)
            self.auto_lan_job = True
            excluded = [e.listen_port for e in self.service.endpoints.values() if e.role == 'client']
            async def discover_open_worlds():
                result = await native_bridge().request('game.discover', {'exclude': excluded, 'duration_ms': 2500})
                return result.get('worlds', [])
            self.job('auto-lan:' + self.generation, discover_open_worlds())

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
        title = data.get('title', '').strip() or self.default_room_title()
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
        name = self.start(endpoint, title, automatic=data.get('automatic') is True)
        self.creation = None
        if self.pending_friend_invites:
            self.pending_friend_invites = {account: (*pending[:2], name) if len(pending) == 2 else pending
                                           for account, pending in self.pending_friend_invites.items()}
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
        endpoint = TunnelClient(profile, invite, listen_port=0,
                                transport_policy=self._state['transportPolicy'])
        if self.pending_room_info and self.pending_room_info.get('id') == invite.room_id:
            endpoint.room_info = dict(self.pending_room_info)
        self.start(endpoint, '好友的房间')
        self.pending_room_info = None
        self.pending = None

    def start(self, endpoint, title, *, automatic=False):
        name = uuid.uuid4().hex
        node_info = {}
        try:
            node_info = json.loads(Path(self.node_path + '.device.json').read_text(encoding='utf-8'))
        except (OSError, ValueError, TypeError):
            pass
        endpoint.on_status = lambda state, detail: self.status.emit(name, state, detail)
        self.records[name] = {'id': name, 'title': title, 'role': endpoint.role,
                              'automaticPublicGuide': automatic,
                              'state': 'connecting', 'detail': '', 'warning': '',
                              'public': bool((endpoint.room_settings or {}).get('public', False)),
                              'requireInvite': (endpoint.room_settings or {}).get('require_invite', True),
                              'allowModTransfer': (endpoint.room_settings or {}).get('allow_mod_transfer', False),
                              'modTransferLimitKib': int((endpoint.room_settings or {}).get('mod_transfer_limit_kib', 512)),
                              'game': dict((endpoint.room_settings or {}).get('game', {})),
                              'nodeName': (endpoint.room_info or {}).get('node_name') or node_info.get('name', self.node_display_names.get(self.node_path, '')),
                              'nodeRegion': (endpoint.room_info or {}).get('node_region') or node_info.get('region', self.node_display_regions.get(self.node_path, '')),
                              'compatibility': '',
                              'transportPolicy':endpoint.transport_policy,
                              'transport':'',
                              'roomId': endpoint.invite.room_id,
                              'preparing': False, 'prepareStatus': '', 'prepareProgress': 0,
                              'prepareMaximum': 0, 'mods': [],
                              'chatMessages': [], 'chatState': '正在连接聊天',
                              'chatSending': False, 'chatDraft': '', 'chatError': '',
                              'bridgeStatus': endpoint.bridge_status if endpoint.role == 'host' else
                                              '正在读取房主的游戏聊天设置…'}
        # A room may exist before its Minecraft world is open. Preserve the
        # native snapshot; a new host without a game port starts out waiting.
        self.records[name]['availability'] = (endpoint.room_info or {}).get('availability') or (
            'waiting' if endpoint.role == 'host' and not endpoint.game_port else 'ready')
        if endpoint.role == 'host':
            self.records[name]['lockedSource'] = self.instance_source
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

    def offer_public_room_guide(self, record):
        if not (record.get('automaticPublicGuide') and record.get('role') == 'host'
                and record.get('state') == 'online' and record.get('availability') == 'ready'):
            return
        record['automaticPublicGuide'] = False
        settings = getattr(self.launcher_page, 'settings_manager', None)
        if (settings is not None and not record.get('public')
                and not settings.get_setting('multiplayer.public_guide_seen', False)):
            settings.set_setting('multiplayer.public_guide_seen', True)
            settings.save_settings()
            record['publicGuide'] = True

    @Slot(str, object)
    def update_chat(self, name, event):
        record = self.records.get(name)
        if not record or not isinstance(event, dict):
            return
        if event.get('type') == 'members' and isinstance(event.get('snapshot'), dict):
            self.apply_members(name, event['snapshot'])
            return
        elif event.get('type') == 'removed':
            self.forget_room(name, '你已被房主移出房间。')
            return
        elif event.get('type') == 'transport':
            transport = event.get('transport')
            if transport in ('p2p', 'relay', 'auto'):
                record['transport'] = transport
        elif event.get('type') == 'room':
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
            if event.get('state') == 'ready' or record.get('availability') == 'ready':
                self._dispatch_pending_friend_invite(name)
            self.offer_public_room_guide(record)
        elif event.get('type') == 'latency':
            value = event.get('latency_ms')
            record['latency_ms'] = value if type(value) is int and 0 <= value <= 1000000 else None
            record['latency_state'] = event.get('state', 'unavailable')
        elif event.get('type') == 'node-latency':
            record['nodeLatencyMs'] = self.valid_latency(event.get('latency_ms'))
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
            failed = [account for account, pending in self.pending_friend_invites.items() if pending[2:] == (name,)]
            if failed:
                for account in failed:
                    del self.pending_friend_invites[account]
                outgoing = dict(self._state['outgoingInvitations'])
                for account in failed:
                    outgoing[account] = dict(outgoing.get(account, {}), status='房间未建立，点击重试', at=time.time())
                self.patch(friendInviteAccount=next(iter(self.pending_friend_invites), failed[0]),
                           outgoingInvitations=outgoing,
                           socialError='房间未能保持连接，未发送好友邀请。请重试邀请。')
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
            record['nodeName'] = str(endpoint.room_info.get('node_name', record.get('nodeName', '')))[:80]
            record['nodeRegion'] = str(endpoint.room_info.get('node_region') or record.get('nodeRegion', ''))[:80]
            if endpoint.room_info.get('lobby'):
                self.apply_members(name, endpoint.room_info['lobby'])
            record['availability'] = endpoint.room_info.get('availability', record.get('availability', 'ready'))
            record['title'] = endpoint.room_info.get('title', record['title'])
            record['game'] = endpoint.room_info.get('game', record.get('game', {}))
            record['public'] = endpoint.room_info.get('public', False)
            record['requireInvite'] = endpoint.room_info.get('require_invite', not record['public'])
            if endpoint.role == 'host':
                record['allowModTransfer'] = bool((endpoint.room_settings or {}).get('allow_mod_transfer', False))
                record['modTransferLimitKib'] = int((endpoint.room_settings or {}).get('mod_transfer_limit_kib', 512))
            self.check_room_compatibility(record)
        self.offer_public_room_guide(record)
        self.publish_connections()

        if state == 'online':
            self._dispatch_pending_friend_invites(name)

    def _dispatch_pending_friend_invite(self, name):
        """Compatibility wrapper for earlier callers and tests."""
        self._dispatch_pending_friend_invites(name)

    def _dispatch_pending_friend_invites(self, name):
        """Send every queued invite for a room, one independent request at a time."""
        if not self.pending_friend_invites:
            return
        record = self.records.get(name, {})
        endpoint = self.service.endpoints.get(name)
        if not (record.get('state') == 'online' and
                record.get('isManager', record.get('role') == 'host') and endpoint and getattr(endpoint, 'connection', None) and getattr(endpoint, 'invite', None)):
            return
        pending_accounts = [account for account, pending in self.pending_friend_invites.items()
                            if pending[0] == self.social_generation and pending[2:] == (name,)]
        if not pending_accounts or self._state['friendBusy'] and any(
                operation != 'invite' for operation, _ in self.social_operations.values()):
            return
        outgoing = dict(self._state['outgoingInvitations'])
        for account in pending_accounts:
            self.pending_friend_invites.pop(account, None)
            outgoing[account] = dict(outgoing.get(account, {}), status='房间已就绪，准备发送',
                                     room=self.service.endpoints[name].invite.room_id, at=time.time())
        account = pending_accounts[0]
        self.patch(pendingFriendInvite='', friendInviteAccount=account, outgoingInvitations=outgoing)
        for account in pending_accounts:
            try:
                self.invite_friend(account)
            except (ValueError, OSError) as exc:
                outgoing = dict(self._state['outgoingInvitations'])
                outgoing[account] = dict(outgoing.get(account, {}), status='发送失败，重试', at=time.time())
                self.patch(socialError='房间已创建，但邀请未发送：' + str(exc), outgoingInvitations=outgoing)

    def _friend_room_presence(self):
        for name, record in self.records.items():
            endpoint = self.service.endpoints.get(name)
            if (record.get('state') == 'online' and record.get('role') in ('host', 'client') and
                    endpoint and endpoint.connection and endpoint.invite):
                availability = record.get('availability', 'ready')
                return dict(room=endpoint.invite.room_id, room_role='host' if record.get('isManager', record['role'] == 'host') else 'client',
                            room_title=record.get('title', '好友的世界')[:80],
                            room_state=availability if availability in ('ready', 'waiting') else 'waiting')
        return None

    def check_room_compatibility(self, record):
        remote = record.get('game') or {}
        local = record.get('preparedGame') or self.game
        record['loaderWarning'] = ''
        if record.get('role') == 'host' or not remote.get('version'):
            record['compatibility'] = ''
            return
        if not local.get('version'):
            record['compatibility'] = '还没有选择游戏配置'
            return
        errors, warnings = compatibility(local, remote)
        record['compatibility'] = '、'.join(errors or [item for item in warnings if item != '加载器版本不一致'])
        record['loaderWarning'] = '加载器版本与房主不同，已保持同类型；若游戏拒绝连接，请使用房主的版本。' if '加载器版本不一致' in warnings else ''

    def launch_room(self):
        name = self._state['selected']
        record = self.records.get(name)
        endpoint = self.service.endpoints.get(name)
        page = self.launcher_page
        if not record or not endpoint or record['state'] != 'online':
            raise ValueError('房间尚未连接。')
        pinned = record.get('lockedSource') or record.get('preparedSource')
        if pinned:
            actual = instance_metadata(*pinned)
            if compatibility(actual, record.get('game', {}))[0]:
                raise ValueError('锁定配置的文件已改变，请重新同步房间配置。')
        if not pinned and record.get('compatibility'):
            raise ValueError('游戏配置与房间不符；请选择匹配配置或准备新配置。')
        if record['role'] == 'client' and (record.get('game', {}).get('mods_count') or
                record.get('game', {}).get('loader', 'vanilla') != 'vanilla'):
            if self._state['instanceLoading'] and not pinned:
                raise ValueError('正在核对游戏加载器，请稍候再启动。')
            expected = record['game'].get('loader', 'vanilla')
            if expected == 'vanilla' or (actual if pinned else self.game).get('loader', 'vanilla') != expected:
                raise ValueError('当前实例没有与房主一致的加载器，请先准备房间配置。')
        if page.current_client or self.external_running or getattr(page.launcher, 'running', False):
            self.patch(notice='游戏已经运行。请进入世界并对局域网开放。' if record['role'] == 'host' else
                       '游戏已经运行。请在多人游戏列表中选择这个房间，或复制地址连接。')
            return
        if not page.auth_manager.is_authenticated():
            raise ValueError('请先在首页设置正版或离线角色，然后启动游戏。')
        if pinned:
            page.launcher.minecraft_directory = pinned[0]
            page.launcher.minecraft_version = pinned[1]
            page.launcher.minecraft_isolation_directory = pinned[2]
        joining = record['role'] == 'client' and record.get('availability') != 'waiting'
        page.started_game(server=f'127.0.0.1:{endpoint.listen_port}' if joining else None)
        self.report_room_state(name, 'starting')
        self.patch(notice='游戏正在启动，将自动进入房间。' if joining else
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
        record['_pendingSource'] = self.instance_source
        self.job('syncgame:' + name, endpoint.update_game(self.game, self.instance_source[2] if self.instance_source else None))
        self.patch(busy=True)

    def prepare_room(self, mode='fresh', retry_task_id=None):
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
        if mode not in ('fresh', 'existing'):
            raise ValueError('请选择全新配置或已有配置。')
        if mode == 'existing' and not self.instance_source:
            raise ValueError('请先选择一个已安装的游戏配置。')
        if record.get('prepareFailed') and record.get('prepareMode') == mode:
            retry_task_id = retry_task_id or record.get('prepareHistoryTask')
        settings = page.settings_manager
        directory = settings.get_setting('minecraft.directory.enable') or ''
        if not directory:
            from utils.path_helper import get_default_minecraft_dir
            directory = str(get_default_minecraft_dir())
            Path(directory).mkdir(parents=True, exist_ok=True)
            installed = settings.get_setting('minecraft.directory.installed', []) or []
            if directory not in installed:
                installed.append(directory)
            settings.set_setting('minecraft.directory.installed', installed)
            settings.set_setting('minecraft.directory.enable', directory)
            settings.save_settings()
        from hookup.preparation import prepare_configuration
        cancel = threading.Event()
        self.preparations[name] = cancel
        history = self.preparation_history()
        def retry(task_id):
            if self.service.endpoints.get(name) is not endpoint or name not in self.records:
                raise ValueError('房间已断开，请重新加入房间后重试。')
            self.patch(selected=name, error='', notice='')
            self.prepare_room(mode, retry_task_id=task_id)
        if history:
            self.preparation_tasks[name] = history.track_room_preparation(
                record.get('title') or '房间配置', directory, record.get('game', {}), cancel,
                retry=retry, task_id=retry_task_id)
            record['prepareHistoryTask'] = self.preparation_tasks[name]
        record.update(preparing=True, prepareStatus='正在核对房间文件…', prepareProgress=0,
                      prepareMaximum=0, prepareFile='', prepareFileDone=0, prepareFileTotal=0,
                      prepareIndex=0, prepareCount=0, prepareSpeed='', modError='',
                      prepareFailed=False, prepareMode=mode)
        record.update(prepareTask=uuid.uuid4().hex, prepareLogs=[])
        self.add_prepare_log(record, '开始核对房间配置', 'configuration')
        self.report_room_state(name, 'checking', 'configuration')
        self.publish_connections()
        preparation_task = record['prepareTask']
        def report(status, done, total):
            self.preparation_event.emit(name, dict(kind='status', task=preparation_task,
                status=str(status)[:160], done=done, total=total))
        java = settings.get_version_setting('java.path', None)
        source = settings.get_setting('settings.general.mirrors', '自动')
        existing_instance = ({'version': self.instance_source[1], 'game_directory': self.instance_source[2]}
                             if mode == 'existing' else None)
        self.job('prepare:' + name, prepare_configuration(endpoint, directory, java, source, cancel, report,
                 event=lambda event: self.preparation_event.emit(name, dict(event, task=preparation_task)),
                 existing_instance=existing_instance,
                 content_source=configured_source(settings)))

    def preparation_history(self):
        parent = getattr(self.launcher_page, 'parent', None)
        main = parent() if callable(parent) else parent
        # The launcher page is a child of the main window in production; walk
        # upward for test hosts and embedded windows that add one wrapper.
        while main is not None and not hasattr(main, 'download_page'):
            parent = getattr(main, 'parent', None)
            main = parent() if callable(parent) else parent
        return getattr(getattr(main, 'download_page', None), 'tasks_page', None)

    @Slot(str, object)
    def update_preparation_event(self, name, event):
        record = self.records.get(name)
        if not record or not record.get('preparing') or event.get('task', record.get('prepareTask')) != record.get('prepareTask'):
            return
        if event.get('kind') == 'status':
            self.update_preparation(name, event['status'], event['done'], event['total'])
            return
        task_id = self.preparation_tasks.get(name)
        history = self.preparation_history()
        if task_id and history:
            history.room_preparation_event(task_id, event)
        kind = event.get('kind')
        if kind == 'manifest':
            record.update(mods=[dict(item, state='pending') for item in event['files']],
                          prepareCount=len(event['files']), modLoading=False)
        elif kind == 'file':
            from core.downloads import download_error_message
            self.add_prepare_log(record, event['name'] + ' · ' + {
                'downloading': '开始下载', 'verified': '校验完成', 'failed': '下载失败',
                'skipped': '可选内容已跳过'}.get(event['state'], event['state']) +
                ((' · ' + download_error_message(event['error'])) if event.get('error') else ''),
                event.get('content', 'mods'), 'error' if event['state'] == 'failed' else 'info')
            record['mods'] = [dict(item, state=event['state']) if item['name'] == event['name'] else item
                              for item in record.get('mods', [])]
            if event['state'] == 'downloading':
                record.update(prepareFile=event['name'], prepareFileDone=0, prepareFileTotal=event['size'],
                              prepareIndex=event.get('index', 1), prepareCount=event.get('count', record.get('prepareCount', 0)),
                              _downloadStarted=time.monotonic(), prepareSpeed='')
            elif event['state'] == 'verified' and record.get('prepareFile') == event['name']:
                record['prepareFileDone'] = event['size']
        elif kind in ('progress', 'download'):
            from core.transfer_metrics import speed_label
            record.update(prepareFile=event['name'], prepareFileDone=event.get('done', 0),
                          prepareFileTotal=event.get('total', 0), prepareIndex=event.get('index', 0),
                          prepareCount=event.get('count', 0), prepareSpeed=speed_label(event.get('task_speed', 0)))
            self.report_room_state(name, 'downloading', record.get('prepareStage', 'game'),
                done=record.get('prepareProgress', 0), total=record.get('prepareMaximum', 0),
                speed=event.get('task_speed', 0))
        self.publish_connections()

    @Slot(str, str, object, object)
    def update_preparation(self, name, status, done, total):
        task_id = self.preparation_tasks.get(name)
        history = self.preparation_history()
        if task_id and history:
            history.update_status(task_id, status)
            history.update_progress(task_id, done, total)
        record = self.records.get(name)
        if record and record.get('preparing'):
            stage = next((key for word, key in [('Java', 'java'), ('资源', 'assets'), ('模组', 'mods'),
                ('加载器', 'loader'), ('校验', 'verify'), ('配置', 'configuration'), ('库', 'libraries')] if word in status), 'game')
            record['prepareStage'] = stage
            self.add_prepare_log(record, status, stage)
            record.update(prepareStatus=status, prepareProgress=max(0, min(done, total)) if total > 0 else 0,
                          prepareMaximum=max(0, total))
            self.report_room_state(name, 'verifying' if stage == 'verify' else 'installing' if stage in ('game', 'loader', 'java') else 'downloading',
                                   stage, done=max(0, done), total=max(0, total))
            self.publish_connections()

    def forget_room(self, name, notice):
        cancel = self.preparations.get(name)
        if cancel:
            cancel.set()
        self.records.pop(name, None)
        self.room_reports.pop(name, None)
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
            self.social_failure('credential', error)
            return
        path = self.node_path
        if not self._state['socialReady']:
            self.patch(socialLoading=True)
        async def check():
            presence = ((self._friend_room_presence() or {})
                        if self._state['socialCapabilities'].get('room_presence') else None)
            network_profile = dict(self.player_network_profile)
            if presence is not None:
                presence['network_profile'] = dict(network_profile)
            return dict(path=path, network_profile=network_profile,
                        state=await status(profile, presence) if presence is not None else await status(profile))
        self.job('socialstatus:' + self.social_generation + ':' + path, check())

    def refresh_network_profile(self):
        if self.closed or self.player_network_profile_task:
            return
        self.player_network_profile_task = True
        async def collect():
            from utils.network_profile import collect_network_profile
            return await collect_network_profile(
                on_type=lambda network_type: self.network_type_detected.emit(self.generation, network_type))
        self.job('network-profile:' + self.generation, collect())

    @Slot(str, str)
    def update_network_type(self, generation, network_type):
        if self.closed or generation != self.generation or not self.player_network_profile_task:
            return
        if network_type not in ('direct_easier', 'relay_likely', 'unknown'):
            network_type = 'unknown'
        self.player_network_profile['type'] = network_type
        self.patch(playerNetworkProfile=dict(self.player_network_profile), playerNetworkTypeReady=True)

    def social_operation(self, operation, account, **fields):
        if not self._state['socialReady']:
            raise ValueError('请先登录节点账号。')
        if self.friend_request or (self.social_operations and
                (operation != 'invite' or any(op != 'invite' for op, _ in self.social_operations.values()))):
            raise ValueError('正在处理好友操作，请稍候。')
        from hookup.social import operate
        path, profile = self.node_path, self.profile()
        key = 'socialop:' + self.social_generation + ':' + uuid.uuid4().hex
        self.social_operations[key] = (operation, account)
        self.patch(friendBusy=True, socialError='')
        async def perform():
            return dict(path=path, operation=operation, target=account,
                        state=await operate(profile, operation, account, **fields))
        self.job(key, perform())

    def invite_friend(self, account):
        if account in self.pending_friend_invites:
            return
        if self._state['friendBusy'] and (self.friend_request or any(
                operation != 'invite' for operation, _ in self.social_operations.values())):
            raise ValueError('正在处理其他好友操作，请稍候。')
        if not self._state['socialReady']:
            raise ValueError('请先登录节点账号。')
        friend = next((item for item in self._state['contacts'] if item['account'] == account), None)
        if not friend or not friend['online']:
            raise ValueError('好友当前不在线，请在对方上线后邀请。')
        candidates = [name for name, record in self.records.items()
                      if record.get('isManager', record.get('role') == 'host') and record['state'] == 'online']
        selected = self._state['selected']
        name = selected if selected in candidates else next(iter(candidates), '')
        endpoint = self.service.endpoints.get(name)
        if endpoint is None or not endpoint.connection:
            self.require_available_node()
            waiting = [key for key, record in self.records.items()
                       if record.get('role') == 'host' and record.get('state') in ('online', 'connecting', 'reconnecting')]
            waiting_name = selected if selected in waiting else next(iter(waiting), '')
            self.pending_friend_invites[account] = (self.social_generation, account)
            if waiting_name:
                self.pending_friend_invites[account] += (waiting_name,)
                self.patch(page='connected', selected=waiting_name)
            elif self._state['page'] != 'create':
                self.navigate('create')
            outgoing = dict(self._state['outgoingInvitations'])
            outgoing[account] = dict(status='等待房间开放，自动发送', room='', at=time.time())
            self.patch(pendingFriendInvite=friend['name'], friendInviteAccount=account,
                       outgoingInvitations=outgoing,
                       notice='先创建并开放房间，成功后会自动邀请 ' + friend['name'] + '。')
            return
        outgoing = dict(self._state['outgoingInvitations'])
        if outgoing.get(account, {}).get('status') == '发送中…':
            raise ValueError('正在给这位好友发送邀请，请稍候。')
        outgoing[account] = dict(status='发送中…', room=endpoint.invite.room_id, at=time.time())
        self.patch(outgoingInvitations=outgoing, friendInviteAccount=account)
        try:
            self.social_operation('invite', account, room=endpoint.invite.room_id)
        except (ValueError, OSError):
            outgoing[account] = dict(outgoing[account], status='发送失败，重试')
            self.patch(outgoingInvitations=outgoing)
            raise

    def apply_social_state(self, state):
        import re
        if (not isinstance(state, dict) or not isinstance(state.get('account'), str) or
                not re.fullmatch(r'[0-9a-f]{32}\.[0-9a-f]{32}', state['account']) or
                not isinstance(state.get('username'), str)):
            raise ValueError('好友服务返回的数据无效。')
        for group, limit in (('friends',64), ('requests',128), ('invitations',256), ('joinRequests',128)):
            entries = state.get(group, []) if group == 'joinRequests' else state.get(group)
            if not isinstance(entries, list) or len(entries) > limit:
                raise ValueError('好友服务返回的数据无效。')
            for entry in entries:
                if (not isinstance(entry, dict) or not isinstance(entry.get('account'), str) or
                        not re.fullmatch(r'[0-9a-f]{32}\.[0-9a-f]{32}', entry['account']) or
                        not isinstance(entry.get('username'), str) or
                        not re.fullmatch('[A-Za-z0-9_-]{3,32}', entry['username'])):
                    raise ValueError('好友服务返回的数据无效。')
                if group == 'friends' and entry.get('room') is not None:
                    room = entry['room']
                    if (not isinstance(room, dict) or not re.fullmatch('[0-9a-f]{32}', str(room.get('id', ''))) or
                            not isinstance(room.get('title'), str) or len(room['title']) > 80 or
                            room.get('role') not in ('host', 'client') or room.get('availability') not in ('ready', 'waiting') or
                            type(room.get('can_request')) is not bool):
                        raise ValueError('好友房间状态无效，请刷新列表。')
                if group == 'friends' and entry.get('network_profile') is not None:
                    self._validate_network_profile(entry['network_profile'])
                if group == 'joinRequests' and (
                        not re.fullmatch('[0-9a-f]{32}', str(entry.get('id', ''))) or
                        not re.fullmatch('[0-9a-f]{32}', str(entry.get('room', ''))) or
                        type(entry.get('incoming')) is not bool or
                        entry.get('status') not in ('pending', 'declined')):
                    raise ValueError('好友加入申请无效，请刷新列表。')
        capabilities = state.get('capabilities', {})
        if not isinstance(capabilities, dict) or any(type(capabilities.get(k, False)) is not bool
                for k in ('room_presence', 'join_requests', 'friend_code')):
            raise ValueError('好友服务功能信息无效。')
        if state.get('networkProfile') is not None:
            self._validate_network_profile(state['networkProfile'])
        contacts = [dict(name=c['username'], account=c['account'], online=c.get('online') is True,
                         room=c.get('room'), networkProfile=c.get('network_profile'), index=i)
                    for i,c in enumerate(state['friends'])]
        invitations = [item for item in state['invitations'] if isinstance(item.get('id'), str)
                       and item['id'] not in self.ignored_friend_invitations]
        previous = self.seen_friend_invitations
        unseen = [item for item in invitations if item['id'] not in previous]
        self.seen_friend_invitations.update(item['id'] for item in invitations)
        live_ids = {item['id'] for item in state['invitations'] if isinstance(item.get('id'), str)}
        self.seen_friend_invitations.intersection_update(live_ids)
        self.ignored_friend_invitations.intersection_update(live_ids)
        outgoing = {account: dict(item, status='邀请已过期，请重新邀请')
                    if item.get('status') == '已发送' and time.time() - item['at'] >= 300 else item
                    for account, item in self._state['outgoingInvitations'].items()}
        self.patch(contacts=contacts, friendRequests=state['requests'], friendInvitations=invitations,
                   joinRequests=state.get('joinRequests', []), socialCapabilities=capabilities,
                   socialReady=True, socialState='online', socialLoading=False, socialAccount=state['account'],
                   socialName=state['username'], socialError='', nodeCredentialRequired=False,
                   playerNetworkProfile=state.get('networkProfile') or self._state['playerNetworkProfile'],
                   outgoingInvitations=outgoing)
        notification = self.social_notifications.update(self._state)
        if notification:
            self.social_notification.emit(notification)
        for invitation in unseen:
            self.friend_invited.emit(dict(invitation))

    @staticmethod
    def _validate_network_profile(profile):
        if (not isinstance(profile, dict) or set(profile) != {
                'type', 'direct_successes', 'relay_successes'} or
                profile.get('type') not in ('direct_easier', 'relay_likely', 'unknown') or
                any(type(profile.get(key)) is not int or not 0 <= profile[key] <= 100000
                    for key in ('direct_successes', 'relay_successes'))):
            raise ValueError('好友网络情况无效，请刷新列表。')

    def lookup_friend(self, data):
        if not self._state['socialReady']:
            raise ValueError('匿名接入没有好友功能，请先在浏览器登录节点账号。')
        identifier = str(data.get('identifier', '')).strip()
        if not re.fullmatch(r'(?:[A-Za-z0-9_-]{3,32}|[0-9a-f]{32}\.[0-9a-f]{32})', identifier):
            raise ValueError('请输入好友码、用户名或完整账号 ID。')
        path, profile = self.node_path, self.profile()
        key = 'friendlookup:' + uuid.uuid4().hex
        self.friend_request = dict(key=key, node=path)
        self.patch(friendBusy=True, friendLookupResults=[])
        async def lookup_and_request():
            values = await lookup_account(profile, identifier)
            if not values:
                raise ValueError('找不到匹配的账号，请核对好友码或用户名后重试。')
            if len(values) > 1:
                return {'candidates': values}
            if values[0]['account'] == self._state.get('socialAccount'):
                raise ValueError('这是你自己的账号 ID，请选择朋友的账号。')
            if any(c['account'] == values[0]['account'] for c in self._state['contacts']):
                raise ValueError('你们已经是好友，可以直接邀请联机。')
            from hookup.social import operate
            return await operate(profile, 'request', values[0]['account'])
        self.job(key, lookup_and_request())

    def cancel_friend_lookup(self):
        self.friend_request = None
        self.patch(friendBusy=bool(self.social_operations), friendLookupResults=[])

    @Slot(str, object, object)
    def finish(self, key, value, error):
        if error:
            error = self.operation_error(error)
        self.jobs.discard(key)
        if key.startswith('network-profile:'):
            self.player_network_profile_task = False
            if key == 'network-profile:' + self.generation:
                try:
                    if not error:
                        self._validate_network_profile(value)
                        self.player_network_profile = dict(value)
                    self.player_network_profile_at = time.monotonic()
                    self.patch(playerNetworkProfile=self.player_network_profile, playerNetworkTypeReady=True, playerNetworkProfileReady=True)
                except ValueError:
                    logging.getLogger('hookup.network_diagnostics').warning('network_profile_invalid')
                    self.player_network_profile = {'type': 'unknown', 'direct_successes': 0, 'relay_successes': 0}
                    self.player_network_profile_at = time.monotonic()
                    self.patch(playerNetworkProfile=self.player_network_profile, playerNetworkTypeReady=True, playerNetworkProfileReady=True)
            return
        if key.startswith('device-refresh:'):
            path = key[len('device-refresh:'):]
            if error:
                if any(word in error for word in ('授权已失效', '设备密钥不可用', '设备已变更', '凭据库中的设备')):
                    self.device_refresh_denied.add(path)
                    if path == self.node_path:
                        self.patch(nodeCredentialRequired=True, notice='登录已失效，请点击浏览器登录重新授权。')
                        try:
                            expired = credential_expiry(RelayProfile.load(path)) <= time.time()
                        except (OSError, ValueError, TypeError):
                            expired = False
                        if expired:
                            self.mark_node_expired()
                        else:
                            self.prompt_node_credential_update()
                elif path == self.node_path:
                    self.patch(notice='暂时无法续期登录，将自动重试；可在有效期内继续联机。')
                    try:
                        expired = credential_expiry(RelayProfile.load(path)) <= time.time()
                    except (OSError, ValueError, TypeError):
                        expired = False
                    if expired:
                        self.mark_node_expired()
            elif path == self.node_path:
                self.device_refresh_denied.discard(path)
                self.reload_store(path, refresh_identity=True)
                self.patch(notice='账号登录已自动续期。', nodeCredentialRequired=False)
            return
        if key.startswith('device-login-start:'):
            if self.closed or key != 'device-login-start:' + getattr(self, 'device_login_generation', '') or not self._state['deviceLoginBusy']:
                return
            if error:
                self.patch(deviceLoginBusy=False, deviceLoginStage='error',
                           deviceLoginMessage='无法发起网页登录：' + error, error='无法发起网页登录：' + error)
                return
            result, private_key = value
            self.device_login = (result, private_key, self.device_login_generation)
            self.patch(deviceLoginUrl=result['verification_uri'], deviceLoginStage='waiting', notice='')
            self.open_device_browser()
            self.device_login_timer.start()
            self.poll_device_login()
            return
        if key.startswith('device-login-poll:'):
            if self.closed or not self.device_login or key != 'device-login-poll:' + self.device_login[2]:
                return
            if error:
                self.device_login = None
                self.device_login_timer.stop()
                self.patch(deviceLoginBusy=False, deviceLoginUrl='', deviceLoginStage='error',
                           deviceLoginMessage='网页登录未完成：' + error, error='网页登录未完成：' + error)
                return
            if value is None:
                return
            self.device_login_timer.stop()
            self.patch(deviceLoginStage='verifying', deviceLoginMessage='浏览器已授权，正在验证节点连接…')
            result, private_key, generation = self.device_login
            from hookup.device_login import approved_profile
            async def verify_approved():
                profile = approved_profile(value, private_key)
                await probe(profile, topology=False)
                return profile, result, private_key
            self.job('device-login-verified:' + generation, verify_approved())
            return
        if key.startswith('device-login-verified:'):
            if self.closed or not self.device_login or key != 'device-login-verified:' + self.device_login[2]:
                return
            self.device_login = None
            self.patch(deviceLoginBusy=False, deviceLoginUrl='')
            if error:
                self.patch(deviceLoginStage='error', deviceLoginMessage='登录已授权，但连接验证未完成：' + error,
                           error='登录已授权，但连接验证未完成：' + error)
                return
            try:
                from hookup.device_login import save_private_key, claims
                profile, result, private_key = value
                grant = claims(profile.token)['g']
                if grant['r'] != result['id'] or grant['o'] != result['origin']:
                    raise ValueError('授权与本次登录请求不匹配。')
                save_private_key(result['id'], private_key)
                self.save_verified_node(profile, reload=False)
                matches = self.matching_nodes(profile)
                if not matches:
                    raise ValueError('节点配置保存失败。')
                path = matches[0]
                self.node_display_names[path] = str(profile._name)[:80]
                self.node_display_regions[path] = str(profile._region)[:80]
                save_json(path + '.device.json', {'id': result['id'], 'origin': result['origin'],
                                                   'name': self.node_display_names[path],
                                                   'region': self.node_display_regions[path]})
                self.device_refresh_denied.discard(path)
                self.reload_store(self.node_path if self._state['connections'] else path, refresh_identity=True)
                self.patch(page='hall', deviceLoginStage='complete', deviceLoginMessage='节点已连接，授权已保存。',
                           notice='已登录并连接节点，后续会自动保持登录。')
            except Exception as exc:
                self.patch(deviceLoginStage='error', deviceLoginMessage='保存登录失败：' + str(exc),
                           error='保存登录失败：' + str(exc))
            return
        if self.finish_room_action(key, value, error):
            return
        if key == 'feedback-upload':
            if error:
                self.patch(error=error, notice='上传未完成，请先在节点反馈页检查已有反馈；也可使用“导出日志”保存到本机。')
            else:
                self.feedback_draft = ''
                self.patch(error='', notice='反馈已提交，编号：' + str((value or {}).get('issue', '未知')))
            return
        if key == 'diagnostics':
            self.patch(error='日志导出失败：' + error if error else '',
                       notice='' if error else '网络与游戏诊断日志已导出：' + str(value))
            return
        if key == 'runtime':
            self.runtime_job = False
            running = value[0] if not error and len(value) == 1 else None
            if running != self.external_running:
                self.external_running = running
                if running is None and not getattr(getattr(self.launcher_page, 'launcher', None), 'running', False):
                    self.auto_lan_seen.clear()
                    self.auto_lan_absences.clear()
                    self.patch(openWorldPrompt=False, openWorldPort=0)
                self.detect_instance()
            return
        if key.startswith('auto-lan:'):
            self.auto_lan_job = False
            if key != 'auto-lan:' + self.generation or error:
                return
            waiting = [(name, record) for name, record in self.records.items()
                       if record.get('role') == 'host' and record.get('state') == 'online'
                       and record.get('availability') == 'waiting']
            if not waiting and self.launcher_page and self.launcher_page.settings_manager.get_setting('multiplayer.quick_action', '首页提示') == '关闭':
                self.patch(openWorldPrompt=False, openWorldPort=0)
                return
            ports = {int(world.get('port') or 0) for world in value}
            previous = self.auto_lan_seen | ({self._state['openWorldPort']} if self._state['openWorldPrompt'] else set())
            # One missed LAN broadcast must not make a handled world look new.
            self.auto_lan_absences = {port: self.auto_lan_absences.get(port, 0) + 1
                                      for port in previous - ports - {0}}
            self.auto_lan_seen.difference_update(port for port, misses in self.auto_lan_absences.items() if misses >= 2)
            if len(value) != 1:
                for name, record in waiting:
                    record['worldChoiceRequired'] = len(value) > 1
                if waiting:
                    self.publish_connections()
                if (self._state['openWorldPrompt'] and
                        (ports or self.auto_lan_absences.get(self._state['openWorldPort'], 0) >= 2)):
                    self.patch(openWorldPrompt=False, openWorldPort=0)
                return
            port = int(value[0].get('port') or 0)
            if port > 0 and port not in self.auto_lan_seen and len(waiting) == 1:
                name, record = waiting[0]
                endpoint = self.service.endpoints.get(name)
                detected_version = value[0].get('version')
                if detected_version and detected_version != record.get('game', {}).get('version'):
                    self.patch(notice='发现的世界版本与房间配置不同，请启动房间中选择的游戏。')
                    return
                record['worldChoiceRequired'] = False
                if endpoint and 'auto-world:' + name not in self.jobs:
                    self.job('auto-world:' + name, endpoint.retarget_world(port))
            elif port > 0 and port not in self.auto_lan_seen and not self._state['connections']:
                self.patch(openWorldPrompt=True, openWorldPort=port, openWorldMode='create')
            return
        if key.startswith('auto-world:'):
            record = self.records.get(key[11:])
            if record:
                if error:
                    record['worldChoiceRequired'] = True
                    self.patch(notice='世界暂未连接成功，将自动重试；也可以选择世界。')
                else:
                    record['worldChoiceRequired'] = False
                    self.patch(openWorldPrompt=False, openWorldPort=0,
                               notice='世界已自动连接，朋友现在可以进入游戏。')
                self.publish_connections()
            return
        if key.startswith('manifest:'):
            record = self.records.get(key[9:])
            if record:
                # Keep verified/download states when reopening the list mid-install.
                previous = {item['name']: item.get('state', '') for item in record.get('mods', [])}
                record['mods'] = [dict(item, state=previous.get(item['name'], '')) for item in value] if not error else []
                record['modError'] = error or ''
                record['modLoading'] = False
                self.publish_connections()
            return
        if key.startswith('syncgame:'):
            record = self.records.get(key[9:])
            if record and not error:
                record['game'] = value
                record['lockedSource'] = record.pop('_pendingSource', record.get('lockedSource'))
            self.patch(busy=False, error=error or '', notice='' if error else '房间版本已同步，玩家已收到更新。')
            self.publish_connections()
            return
        if key.startswith('prepare:'):
            from core.downloads import download_error_message
            display_error = download_error_message(error)
            name = key[8:]
            cancel = self.preparations.pop(name, None)
            task_id = self.preparation_tasks.pop(name, None)
            history = self.preparation_history()
            if task_id and history:
                history.finish_room_preparation(task_id, not error, error or '房间模组与加载器已安装并校验完成',
                                                cancelled=bool(cancel and cancel.is_set()))
            record = self.records.get(name)
            if record:
                record['preparing'] = False
                record['prepareFailed'] = bool(error)
                record['prepareStatus'] = display_error or '配置已安装，正在复核加载器和模组…'
                self.publish_connections()
            if error:
                if record:
                    self.add_prepare_log(record, display_error, 'configuration', 'error')
                    self.report_room_state(name, 'cancelled' if cancel and cancel.is_set() else 'failed',
                                           code='cancelled' if cancel and cancel.is_set() else 'install_failed')
                self.patch(error='配置准备失败：' + display_error)
                return
            try:
                if not record:
                    return
                self.detect_instance()
                self.pending_preparation_check = (name, value)
                self.select_instance(value)
                # The room install has just written its mod directory. Force a
                # metadata scan even when the selected source tuple is unchanged.
                self.detect_instance(force=True)
                self.patch(notice='配置已准备完成，正在复核加载器和模组…')
            except Exception as exc:
                self.pending_preparation_check = None
                self.patch(error=str(exc))
            return
        if key.startswith('retarget:'):
            if key[9:] not in self.records:
                return
            self.patch(busy=False, error=error or '',
                       page='worldPicker' if error else 'connected',
                       notice='' if error else '世界已重新开放，朋友可以重新进入游戏。')
            return
        if key.startswith('configure:'):
            record = self.records.get(key[10:])
            if not record:
                return
            if not error:
                endpoint = self.service.endpoints.get(key[10:])
                record.update(title=value.get('title', record.get('title', '房间')),
                              public=value.get('public', False),
                              requireInvite=value.get('require_invite', True),
                              allowModTransfer=bool((endpoint.room_settings or {}).get('allow_mod_transfer', False))
                              if endpoint else False,
                              modTransferLimitKib=int((endpoint.room_settings or {}).get('mod_transfer_limit_kib', 512))
                              if endpoint else 512)
                record['publicGuide'] = False
                self.publish_connections()
            self.patch(busy=False, error=error or '', notice='' if error else '房间设置已保存。')
            if not error:
                self.roomSettingsSaved.emit()
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
                               nodeLatencyMs=self.valid_latency(value.get('node_latency_ms'))
                               if value.get('node_latency_method') == 'application-echo' else None,
                               roomNext=value['next'], roomTotal=value['total'], roomError='')
                    if self.clipboard_invite:
                        QTimer.singleShot(0, self.join_from_clipboard)
            return
        if key.startswith('nodehealth:'):
            if key == 'nodehealth:' + self.node_check_generation:
                self.patch(nodeAvailable=not bool(error),
                           nodeLatencyMs=None if error else self.valid_latency(value),
                           roomError='暂时无法连接节点，请检查网络后重试。' if error else '')
                if not error and self.clipboard_invite:
                    QTimer.singleShot(0, self.join_from_clipboard)
            return
        if key.startswith('socialstatus:') or key.startswith('socialop:'):
            if key.split(':', 2)[1] != self.social_generation:
                return
            operation, target = self.social_operations.pop(key, ('', ''))
            friend_busy = bool(self.social_operations or self.friend_request)
            if error:
                outgoing = dict(self._state['outgoingInvitations'])
                if operation == 'invite' and target in outgoing and outgoing[target].get('status') == '发送中…':
                    outgoing[target] = dict(outgoing[target], status='发送失败，重试')
                self.social_failure('request', error)
                self.patch(friendBusy=friend_busy, outgoingInvitations=outgoing,
                           joiningFriendAccount='')
                self.friend_finished.emit(False, str(error)) if key.startswith('socialop:') else None
                return
            try:
                if value['path'] != self.node_path:
                    return
                if value.get('operation') == 'join':
                    self.join(value['state']['invite'])
                    self.patch(joiningFriendAccount='')
                    self.ignored_friend_invitations.update(item['id'] for item in self._state['friendInvitations']
                                                           if item['account'] == value.get('target'))
                    self.patch(friendInvitations=[item for item in self._state['friendInvitations']
                                                  if item['id'] not in self.ignored_friend_invitations])
                    self.window.showNormal()
                    self.window.raise_()
                    self.window.activateWindow()
                else:
                    self.apply_social_state(value['state'])
                    if isinstance(value.get('network_profile'), dict):
                        self.patch(playerNetworkProfile=dict(value['network_profile']))
                    if self.social_failures:
                        logging.getLogger('hookup.social').info(
                            'social_ui_sync_recovered failures=%s contacts=%s',
                            self.social_failures, len(self._state['contacts']))
                        self.social_failures = 0
                self.patch(friendBusy=friend_busy)
                if key.startswith('socialop:'):
                    if value.get('operation') == 'invite':
                        outgoing = dict(self._state['outgoingInvitations'])
                        account = value.get('target')
                        if account:
                            outgoing[account] = dict(outgoing.get(account, {}), status='已发送', at=time.time())
                        self.patch(outgoingInvitations=outgoing, notice='邀请已发送，对方会在好友窗口收到提醒。')
                        self.friend_finished.emit(True, '已发送联机邀请。')
                    elif value.get('operation') == 'request_join':
                        self.patch(notice='申请已发送，等待房主同意；同意后会收到联机邀请。')
                        self.friend_finished.emit(True, '申请已发送，等待房主同意。')
                    elif value.get('operation') == 'accept_join':
                        self.patch(notice='已同意加入，对方将收到联机邀请。')
                        self.friend_finished.emit(True, '已同意并发送联机邀请。')
                    elif value.get('operation') == 'decline_join':
                        self.friend_finished.emit(True, '已拒绝加入申请。')
                    else:
                        self.friend_finished.emit(True, '已更新。')
                for name in list(self.records):
                    self._dispatch_pending_friend_invites(name)
            except Exception as exc:
                if key.startswith('socialstatus:'):
                    self.social_failure('response', exc)
                if (operation == 'invite' and target in self._state['outgoingInvitations'] and
                        self._state['outgoingInvitations'][target].get('status') == '发送中…'):
                    outgoing = dict(self._state['outgoingInvitations'])
                    outgoing[target] = dict(outgoing[target], status='发送失败，重试')
                    self.patch(outgoingInvitations=outgoing)
                self.patch(friendBusy=friend_busy, socialError=str(exc), joiningFriendAccount='')
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
                if isinstance(value, dict) and 'candidates' in value:
                    self.patch(friendLookupResults=value['candidates'])
                    self.friend_finished.emit(False, '找到同名账号，请核对账号 ID 后选择。')
                    return
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
                    message = ('此节点已添加。是否更新账号授权？更新后立即重新验证账号并加载好友。'
                               if personal else '此节点已添加。是否改用匿名接入？更新后此节点将无法使用账号好友功能。')
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
                       loaderVersion=self.game.get('loader_version', ''), localModsCount=self.game.get('mods_count', 0), instanceLoading=False,
                       instanceError='所选实例读取失败，请在首页检查安装或切换实例。' if error else '')
            for record in self.records.values():
                self.check_room_compatibility(record)
            if not error and self.instance_source:
                for name, endpoint in list(self.service.endpoints.items()):
                    record = self.records.get(name)
                    if (record and not record.get('lockedSource') and endpoint.role == 'host' and record.get('availability') == 'waiting'
                            and record.get('game') != self.game):
                        self.job('syncgame:' + name, endpoint.update_game(self.game, self.instance_source[2]))
            self.publish_connections()
            if self.pending_preparation_check:
                name, version = self.pending_preparation_check
                self.pending_preparation_check = None
                record = self.records.get(name)
                if record and self._state['instanceId'] == version:
                    if error or record.get('compatibility'):
                        detail = '房间配置复核失败：' + (error or record['compatibility'])
                        record['prepareStatus'] = detail
                        self.patch(error=detail)
                    elif record.get('availability') == 'waiting':
                        record['prepareStatus'] = '已准备好，等待房主开放世界。'
                        self.patch(notice=record['prepareStatus'])
                    else:
                        record['prepareStatus'] = '已准备好，点击“进入游戏”即可加入，也可以继续等待。'
                        self.patch(notice=record['prepareStatus'])
                    if not error and not record.get('compatibility'):
                        record['preparedSource'] = self.instance_source
                        record['preparedGame'] = dict(self.game)
                        self.report_room_state(name, 'ready')
                        self.add_prepare_log(record, '配置复核完成，已准备好', 'verify')
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
        if key.startswith('lan:'):
            self._state['worldScanning'] = False
        self.patch(busy=False)
        if error:
            self.quick_creation_data = None
            message = ('无法连接这个世界。请确认已对局域网开放，并检查端口。'
                       if key.startswith('probe:') else '操作未完成：' + error)
            self.patch(error=message)
            return
        if key.startswith('lan:'):
            pending_port = int(self._state.get('pendingOpenWorldPort') or 0)
            selected = next((item for item in value if int(item.get('port') or 0) == pending_port), None)
            self.patch(worlds=value, error='' if value else '暂未发现已开放的世界。进入单人世界后，在暂停菜单选择“对局域网开放”，启动器会自动查找。',
                       pendingOpenWorldPort=0)
            if selected:
                self.patch(worldPort=selected['port'], notice='已找到刚才开放的世界，确认后即可继续创建房间。')
        elif key.startswith('probe:') and self.creation:
            detected = value.get('version', '')
            if re.fullmatch(r'\d+\.\d+(?:\.\d+)?', detected) and detected != self.creation['game']['version']:
                self.creation = None
                self.quick_creation_data = None
                self.patch(error='查找到的世界与当前游戏实例版本不一致，请选择对应实例。')
                return
            self.creation['game']['protocol'] = value['protocol']
            self.patch(step=1, worldPort=value['port'], error='')
            pending, self.quick_creation_data = self.quick_creation_data, None
            if pending and pending[0] == self.generation:
                self.act('create', pending[1])
        elif key.startswith('resolve:'):
            if value['path'] != self.node_path:
                self.patch(error='节点已切换，请重新选择房间。')
                return
            self.pending_room_info = dict(value['room'])
            if value['room'].get('require_invite', False):
                self.pending = None
                self.patch(invitePrompt=True, joinRoomId=value['room']['id'],
                           joinRoomTitle=value['room']['title'], error='', notice='', busy=False)
                return
            try:
                self.join(RoomInvite(value['secret']).encode())
            except Exception as exc:
                self.patch(error=str(exc))

    def show_feedback(self):
        if self.feedback_dialog is not None:
            self.feedback_dialog.show()
            self.feedback_dialog.raise_()
            self.feedback_dialog.activateWindow()
            return
        from ui.dialog.feedback import FeedbackDialog
        node = next((item.get('title', '当前节点') for item in self._state['nodes']
                     if item.get('path') == self.node_path), '当前节点')
        profile = self.profile()
        dialog = FeedbackDialog(self.window, content=self.feedback_draft, node=node)
        self.feedback_dialog = dialog
        # Bind this report to the selected account/node before opening the form.

        def submit(title, description):
            from utils.feedback_upload import submit_diagnostics
            self.feedback_draft = description
            self.patch(notice='正在提交问题并收集排查信息…', error='')
            self.job('feedback-upload', submit_diagnostics(profile, title, description, consent=True))

        def finished(_result):
            self.feedback_draft = dialog.controller.data.get('content', '')
            self.feedback_dialog = None
            dialog.shutdown()
            QTimer.singleShot(0, dialog, dialog.deleteLater)

        dialog.submitted.connect(submit)
        dialog.finished.connect(finished)
        dialog.show()

    @Slot()
    def close(self):
        cancel_copy(self)
        if not self.closed:
            self.closed = True
            if self.feedback_dialog is not None:
                self.feedback_dialog.reject()
            if self.credential_prompt_dialog is not None:
                self.credential_prompt_dialog.close()
            self.room_report_timer.stop()
            self.room_reports.clear()
            self.room_search_timer.stop()
            self.friend_timer.stop()
            self.network_profile_timer.stop()
            self.device_login_timer.stop()
            self.device_refresh_timer.stop()
            self.device_login = None
            for cancel in self.preparations.values():
                cancel.set()
            self.service.close()
