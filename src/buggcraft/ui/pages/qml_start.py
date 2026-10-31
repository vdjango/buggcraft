"""Home controller: account and game state with a QML-only visual layout."""
import logging
from pathlib import Path

from PySide6.QtCore import QObject, Property, QTimer, QUrl, Signal, Slot
from PySide6.QtWidgets import QApplication

from config.settings import get_settings_manager
from core.auth.microsoft import Authenticator, MinecraftSignals
from core.game_sessions import GameSessions
from ui.dialog.LoginDialog import LoginWaitDialog
from ui.pages.qml_host import QmlPage
from utils.helpers import get_physical_resolution

logger = logging.getLogger(__name__)


class HomeController(QObject):
    changed = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.page = parent
        self.collapsed = False
        self.status = ''
        self.title = ''
        self.subtitle = ''
        self.launch_enabled = True
        self.social_ready = False
        self.friend_entry_available = False
        self.friend_notifications = {}
        self.multiplayer_action = ''

    @Property('QVariantMap', notify=changed)
    def view(self):
        page = self.page
        user = page.auth_manager.current
        avatar = user.avatar if user.avatar and Path(user.avatar).is_file() else str(Path(page.resource_path) / 'images/user/unlogged_avatar.png')
        sessions = []
        for record in page.launcher.sessions:
            process = record['launcher'].process
            sessions.append(dict(id=record['id'], label=f"{record['instance'][1]} · PID {process.pid}" if process else f"{record['instance'][1]} · 启动中"))
        return dict(collapsed=self.collapsed, mode=page.auth_manager.current_mode,
                    username=user.username or '未登录', authenticated=bool(user.username),
                    avatar=QUrl.fromLocalFile(str(avatar)).toString(), status=self.status,
                    launchTitle=self.title, launchSubtitle=self.subtitle,
                    launchEnabled=self.launch_enabled, sessions=sessions,
                    selectedSession=page.launcher.selected_id or 0, friendsVisible=self.friend_entry_available,
                    friendNotifications=self.friend_notifications,
                    multiplayerTitle={'create': '创建房间', 'join': '加入房间', 'associate': '开放房间'}.get(self.multiplayer_action, '联机'),
                    multiplayerAttention=self.multiplayer_action in ('create', 'join', 'associate'),
                    allowMultiple=bool(sessions) and page.settings_manager.get_setting('launcher.allow_multiple', False),
                    resources=QUrl.fromLocalFile(str(Path(page.resource_path).resolve()) + '/').toString())

    @Slot(str)
    def chooseMode(self, mode):
        if mode not in ('offline', 'online'):
            return
        self.page.auth_manager.current_mode = mode
        self.status = ''
        self.changed.emit()

    @Slot(str)
    def loginOffline(self, username):
        username = username.strip()
        if not username:
            self.status = '请输入用户名。'
            self.changed.emit()
            return
        from core.launch_options import offline_uuid
        user = self.page.auth_manager.offline
        user.username, user.uuid = username, offline_uuid(username)
        self.page.auth_manager.current_mode = 'offline'
        self.page.handle_auth_success(username, {'type': 'offline'})

    @Slot()
    def loginOnline(self):
        self.page.auth_manager.cancel_refresh()
        self.page.login_dialog.start_login_process()
        self.page.login_dialog.exec()

    @Slot()
    def switchAccount(self):
        self.page.auth_manager.cancel_refresh()
        self.page.auth_manager.current.clear()
        self.page.auth_manager.save(self.page.cache_path)
        self.changed.emit()

    @Slot(bool)
    def launch(self, additional=False):
        self.page.started_game(additional=additional)

    @Slot()
    def stopSelected(self):
        if self.page.launcher.running:
            self.page.launcher.stop()

    @Slot(int)
    def selectSession(self, identity):
        if any(record['id'] == identity for record in self.page.launcher.sessions):
            self.page.launcher.selected_id = identity
            self.page.refresh_game_sessions()

    @Slot(str)
    def social(self, destination):
        if destination == 'friends':
            self.page.show_friends_dialog()
        else:
            self.page.show_multiplayer_dialog()


class StartGamePage(QmlPage):
    started_changed = Signal()
    login_success = Signal(dict, str)
    instance_changed = Signal()

    def __init__(self, parent, resource_path, cache_path):
        self.parent = parent
        self.resource_path = resource_path
        self.cache_path = cache_path
        self.settings_manager = get_settings_manager()
        self.auth_manager = Authenticator()
        self.current_client = False
        controller = HomeController(parent)
        # The controller needs its business state before QML evaluates bindings.
        controller.page = self
        self.launcher = GameSessions(config_path=parent.config_path, parent=parent)
        controller.title = '启动游戏' if self.launcher.minecraft_version else '选择游戏'
        controller.subtitle = self.launcher.minecraft_version or '请下载或导入游戏'
        super().__init__(parent, resource_path, 'Home.qml', 'homePage', controller)
        self.launcher.setParent(self)
        controller.setParent(self)
        self.signals = MinecraftSignals()
        self.login_dialog = LoginWaitDialog(resource_path, cache_path, self)
        self.login_dialog.cancel_signal.connect(lambda: self.handle_auth_failure('取消登录'))
        self.auth.signals.success.connect(self.handle_auth_success)
        self.auth.signals.failure.connect(self.handle_auth_failure)
        self.auth.signals.progress.connect(self.handle_auth_progress)
        self.auth_manager.signals.success.connect(self.handle_auth_success)
        self.auth_manager.signals.failure.connect(self.handle_auth_failure)
        self.auth_manager.signals.progress.connect(self.handle_auth_progress)
        self.launcher.changed.connect(self.refresh_game_sessions)
        self.launcher.signals.started.connect(self.minecraft_handle_started)
        self.launcher.signals.stopped.connect(self.minecraft_handle_stopped)
        self.launcher.signals.error.connect(self.minecraft_handle_error)
        self._pending_auth_launch = None
        self.auth_manager.load(cache_path)
        self.auth_refresh_timer = QTimer(self)
        self.auth_refresh_timer.setInterval(60000)
        self.auth_refresh_timer.timeout.connect(self.is_expired_token)
        self.auth_refresh_timer.start()
        self.refresh_game_sessions()
        # Saved nodes also monitor opened worlds before the hall is shown.
        QTimer.singleShot(1500, self, self._start_background_social)
        self._quick_action_scheduled = False
        self._handled_multiplayer_invite = ''
        QApplication.clipboard().dataChanged.connect(self._clipboard_changed)
        self._refresh_multiplayer_entry()

    @property
    def auth(self):
        return self.login_dialog.auth

    def _launch_state(self, title, subtitle=None, enabled=True):
        self.controller.title = title
        self.controller.subtitle = subtitle if subtitle is not None else self.launcher.minecraft_version or '请下载或导入游戏'
        self.controller.launch_enabled = enabled
        self.controller.changed.emit()

    def started_game(self, server=None, additional=False):
        server = server if isinstance(server, str) else None
        if self.current_client and not additional:
            self._launch_state('正在停止游戏…', self.launcher.selected['instance'][1], False)
            self.launcher.stop()
            return
        if additional and not self.settings_manager.get_setting('launcher.allow_multiple', False):
            return
        if not self.launcher.minecraft_version:
            self.parent.switch_pages('实例')
            return
        if not self.auth_manager.is_authenticated():
            self._launch_state('请先设置角色')
            return
        if self.auth_manager.current_mode == 'online' and not self.auth_manager.online.is_token_valid():
            self._pending_auth_launch = (server, additional)
            self._launch_state('正在刷新正版登录…', enabled=False)
            self.auth_manager.refresh_login()
            return
        self._launch_state('启动中…', enabled=False)
        language = self.settings_manager.get_setting('game.language', 'zh_cn')
        self.launcher.set_language(language)
        size = self.settings_manager.get_version_setting('launcher.window_size', '默认')
        fullscreen, width, height = False, None, None
        if size == '默认':
            width, height = 854, 480
        elif size == '与启动器一致':
            width, height = get_physical_resolution(self.parent.width(), self.parent.height())
            width, height = str(int(width)), str(int(height))
        elif size == '最大化':
            fullscreen = True
        user = self.auth_manager.current
        self.launcher.set_options(uuid=user.uuid, username=user.username, token=user.token, server=server,
                                  version=self.launcher.minecraft_version,
                                  memory=self.settings_manager.get_version_setting('memory.allocation', 2048),
                                  width=width, height=height, fullscreen=fullscreen)
        self._launch_instance = (self.launcher.minecraft_directory, self.launcher.minecraft_version,
                                 self.launcher.minecraft_isolation_directory)
        self.parent._launch_error_reported = False
        self.launcher.start()
        self.instance_changed.emit()

    def set_minecraft_version(self, version):
        self.launcher.minecraft_version = version or None
        self.launcher.minecraft_isolation_directory = self.settings_manager.get_minecraft_isolation_directory()
        self.refresh_game_sessions()

    def refresh_game_sessions(self):
        self.current_client = self.launcher.running
        self.running_instance = self.launcher.running_instance
        selected = self.launcher.selected
        multiple = self.settings_manager.get_setting('launcher.allow_multiple', False)
        title = ('启动中…' if self.launcher.starting else '停止游戏' if self.current_client and not multiple
                 else '启动游戏' if self.launcher.minecraft_version else '选择游戏')
        self._launch_state(title, selected['instance'][1] if selected and not multiple else self.launcher.minecraft_version or '请下载或导入游戏',
                           not self.launcher.starting)
        self.instance_changed.emit()

    def minecraft_handle_started(self):
        self._ensure_multiplayer_dialog()
        self.refresh_game_sessions()

    def minecraft_handle_stopped(self, exit_code):
        self.refresh_game_sessions()

    def minecraft_handle_error(self, message):
        if not self.launcher.running:
            self.refresh_game_sessions()
        self.controller.status = ''
        self.controller.changed.emit()

    def show_multiplayer_dialog(self):
        self._acknowledge_multiplayer_invite()
        self._ensure_multiplayer_dialog()
        self._multiplayer_dialog.detect_instance()
        backend = self._multiplayer_dialog.backend
        if (backend.view.get('openWorldPrompt') and
                self.settings_manager.get_setting('multiplayer.quick_action', '首页提示') != '关闭'):
            backend.act('createFromOpenWorld', {'port': backend.view['openWorldPort']})
        self._show_multiplayer_window()

    def _show_multiplayer_window(self):
        self._multiplayer_dialog.showNormal()
        self._multiplayer_dialog.raise_()
        self._multiplayer_dialog.activateWindow()
        tutorial = getattr(self.parent, 'tutorial_controller', None)
        if tutorial is not None:
            tutorial.attach_lobby(self._multiplayer_dialog)
        self._social_changed()

    def _social_changed(self):
        self.controller.social_ready = self._multiplayer_dialog.backend.view['socialReady']
        self.controller.friend_entry_available = self._multiplayer_dialog.backend.view['friendEntryAvailable']
        self.controller.friend_notifications = self._multiplayer_dialog.backend.view.get('friendNotifications', {})
        self._refresh_multiplayer_entry()

    def _clipboard_changed(self):
        self._refresh_multiplayer_entry()

    @staticmethod
    def _clipboard_room_invite():
        from hookup.profiles import RoomInvite
        text = QApplication.clipboard().text().strip()
        try:
            RoomInvite.decode(text)
        except ValueError:
            return ''
        return text

    def _acknowledge_multiplayer_invite(self):
        invite = self._clipboard_room_invite()
        if invite:
            self._handled_multiplayer_invite = invite

    def _refresh_multiplayer_entry(self):
        if getattr(self.parent, '_closing', False) or getattr(self.parent, '_close_after_game', False):
            return
        dialog = getattr(self, '_multiplayer_dialog', None)
        state = dialog.backend.view if dialog else {}
        invite = self._clipboard_room_invite()
        if invite and dialog and invite == dialog.backend.consumed_clipboard_invite:
            self._handled_multiplayer_invite = invite
        action = 'join' if invite and invite != self._handled_multiplayer_invite else ''
        if state.get('openWorldPrompt'):
            action = state.get('openWorldMode', 'create')
        elif state.get('connections'):
            action = ''
        if self.settings_manager.get_setting('multiplayer.quick_action', '首页提示') == '关闭':
            action = ''
        self.controller.multiplayer_action = action
        self.controller.changed.emit()
        if (action in ('create', 'join', 'associate') and self.settings_manager.get_setting('multiplayer.quick_action', '首页提示') == '自动创建或加入'
                and not self._quick_action_scheduled):
            self._quick_action_scheduled = True
            QTimer.singleShot(0, self._run_auto_multiplayer)

    def _run_auto_multiplayer(self):
        self._quick_action_scheduled = False
        tutorial = getattr(self.parent, 'tutorial_controller', None)
        if tutorial is not None and tutorial.visible:
            return
        if (getattr(self.parent, '_closing', False) or getattr(self.parent, '_close_after_game', False) or
                self.settings_manager.get_setting('multiplayer.quick_action', '首页提示') != '自动创建或加入'):
            return
        if self.controller.multiplayer_action not in ('create', 'join', 'associate'):
            return
        dialog = self._ensure_multiplayer_dialog()
        backend = dialog.backend
        if backend.closed:
            return
        state = backend.view
        if state.get('openWorldPrompt'):
            if not state['nodeAvailable'] or state['instanceLoading'] or state['busy']:
                return
            if state['openWorldMode'] == 'associate':
                self._acknowledge_multiplayer_invite()
                backend.act('createFromOpenWorld', {'port': state['openWorldPort'], 'automatic': True})
            else:
                port = state['openWorldPort']
                self._acknowledge_multiplayer_invite()
                backend.act('dismissOpenWorld', {})
                backend.act('quickCreate', {'port': port, 'title': backend.default_room_title(), 'automatic': True})
            self._show_multiplayer_window()
        else:
            if state['busy'] or state['page'] not in ('hall', 'join', 'nodes'):
                return
            self._acknowledge_multiplayer_invite()
            backend.join_from_clipboard()
            self._show_multiplayer_window()
        self._refresh_multiplayer_entry()

    def show_friends_dialog(self):
        self._ensure_multiplayer_dialog()
        if not self._multiplayer_dialog.backend.view['friendEntryAvailable']:
            self.show_multiplayer_dialog()
            return
        self._multiplayer_dialog.show_friends()

    def _ensure_multiplayer_dialog(self, *, background=False):
        from ui.dialog.MultiplayerDialog import MultiplayerDialog
        if not hasattr(self, '_multiplayer_dialog'):
            self._multiplayer_dialog = MultiplayerDialog(self, background=background)
            self._multiplayer_dialog.backend.changed.connect(self._social_changed)
        elif not background:
            self._multiplayer_dialog.load_ui()
        return self._multiplayer_dialog

    def _start_background_social(self):
        if hasattr(self, '_multiplayer_dialog'):
            return
        try:
            dialog = self._ensure_multiplayer_dialog(background=True)
            nodes = dialog.backend.view.get('nodes', [])
            selected = next((node for node in nodes if node['path'] == dialog.backend.node_path), {})
            if not selected.get('personalCode'):
                personal = next((node for node in nodes if node.get('personalCode')), None)
                if personal is not None:
                    dialog.backend.reload_store(select=personal['path'])
        except Exception:
            logger.debug('background social session unavailable', exc_info=True)

    def handle_auth_success(self, username, data):
        mode = data.get('type', 'offline')
        self.auth_manager.current_mode = 'online' if mode == 'online' else 'offline'
        user = self.auth_manager.current
        user.username = username
        if mode == 'online':
            for field in ('uuid', 'token', 'refresh_token', 'expires_at'):
                setattr(user, field, data.get(field))
        skin = data.get('skin')
        if skin and Path(skin).is_file():
            user.avatar = skin
        self.auth_manager.save(self.cache_path)
        self.controller.status = ''
        self.controller.changed.emit()
        self.login_success.emit({'uuid': user.uuid, 'username': username, 'token': user.token}, mode)
        pending, self._pending_auth_launch = self._pending_auth_launch, None
        if pending:
            QTimer.singleShot(0, lambda: self.started_game(pending[0], additional=pending[1]))

    def handle_auth_progress(self, progress):
        self.controller.status = str(progress)
        self.controller.changed.emit()

    def handle_auth_failure(self, message):
        self._pending_auth_launch = None
        self.refresh_game_sessions()
        self.controller.status = str(message)
        self.controller.changed.emit()
        self.signals.error.emit(f'登录失败: {message}')

    def is_expired_token(self):
        if (self.auth_manager.current_mode == 'online' and self.auth_manager.online.token
                and not self.auth_manager.online.is_token_valid()):
            self.auth_manager.refresh_login()

    def on_page_activate(self):
        self.refresh_game_sessions()

    def on_page_deactivate(self):
        pass

    def toggle_menu(self, menu_collapsed=False):
        self.controller.collapsed = menu_collapsed
        self.controller.changed.emit()
