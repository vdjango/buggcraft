"""QML multiplayer window embedded in the existing launcher."""
from pathlib import Path

from PySide6.QtCore import QEvent, Qt, QTimer, QUrl
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QInputDialog, QMessageBox, QVBoxLayout, QWidget, QSystemTrayIcon

from ui.multiplayer_controller import MultiplayerController
from utils.app_icon import get_app_icon


class MultiplayerDialog(QDialog):
    def __init__(self, parent=None, storage_path=None):
        # A native owned dialog is minimized automatically with its owner on
        # Windows. Lifecycle remains explicitly managed by the launcher.
        super().__init__(None, Qt.Window | Qt.FramelessWindowHint)
        self.launcher_page = parent
        self._shutdown = False
        if parent is not None:
            parent.destroyed.connect(self.deleteLater)
        self.setWindowTitle('BUGG·联机大厅')
        # Match the launcher's original collapsed canvas (926 - 205, 505).
        main_window = getattr(parent, 'parent', None)
        background = getattr(main_window, 'bg_image', None)
        width = background.width() - main_window.menu_width if background else 721
        height = background.height() if background else 505
        self.setFixedSize(width, height)
        resources = Path(getattr(parent, 'resource_path', None) or
                         Path(__file__).resolve().parents[4] / 'resources')
        self.resources = resources
        self.setWindowIcon(get_app_icon(resources))
        from utils.windows_taskbar import install_taskbar_identity
        install_taskbar_identity(self, resources)
        self.friends_window = None
        self.invitation_dialog = None
        self._invitation = None
        self._invitation_queue = []
        self.backend = MultiplayerController(self, storage_path)
        QApplication.instance().installEventFilter(self)
        from utils.social_sound import SocialSound
        self.social_sound = SocialSound(resources)
        self.backend.social_notification.connect(self.notify_social)
        self.backend.room_notification.connect(self.notify_room)
        self.backend.friend_invited.connect(self.show_friend_invitation)
        self.backend.changed.connect(self.refresh_invitation)
        if hasattr(parent, 'friends_btn'):
            visible = lambda: self.backend.view['friendEntryAvailable']
            self.backend.changed.connect(lambda: parent.friends_btn.setVisible(visible()))
            parent.friends_btn.setVisible(visible())
        if parent is not None and hasattr(parent, 'instance_changed'):
            parent.instance_changed.connect(self.backend.detect_instance)
        self.service = self.backend.service
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.quick = QQuickWidget(self)
        self.quick.setResizeMode(QQuickWidget.SizeRootObjectToView)
        self.quick.rootContext().setContextProperty('lobby', self.backend)
        tutorial = getattr(getattr(parent, 'parent', None), 'tutorial_controller', None)
        if tutorial is not None:
            self.quick.rootContext().setContextProperty('tutorial', tutorial)
        self.quick.setSource(QUrl.fromLocalFile(str(resources / 'qml/multiplayer/Lobby.qml')))
        if self.quick.status() == QQuickWidget.Error:
            self.backend.close()
            raise RuntimeError('联机页面加载失败：' + '\n'.join(e.toString() for e in self.quick.errors()))
        layout.addWidget(self.quick)
        self.timer = QTimer(self)
        self.timer.setInterval(15000)
        self.timer.timeout.connect(self.backend.check_node)
        self.timer.start()
        self.backend.detect_instance()
        self.runtime_timer = QTimer(self)
        self.runtime_timer.setInterval(3000)
        self.runtime_timer.timeout.connect(self.backend.detect_runtime)
        self.runtime_timer.start()
        self.backend.detect_runtime()

    def detect_instance(self):
        self.backend.detect_instance()

    def eventFilter(self, watched, event):
        # QQuickWidget's Escape shortcut can otherwise consume the key before
        # a native child dialog receives it, closing the lobby behind the
        # still-open confirmation. Let the active native dialog handle Escape
        # through its normal keyPressEvent (No/cancel), without rejecting it
        # or modifying the lobby's room/connection state ourselves.
        if event.type() == QEvent.ShortcutOverride and event.key() == Qt.Key_Escape:
            modal = QApplication.activeModalWidget()
            if isinstance(watched, QWidget) and isinstance(modal, (QMessageBox, QInputDialog, QFileDialog)):
                # QWidget.isAncestorOf stops at a native window boundary;
                # these dialogs are windows owned by, not inside, the lobby.
                owner = modal.parentWidget()
                while owner is not None and owner is not self:
                    owner = owner.parentWidget()
                if owner is self and (watched is modal or modal.isAncestorOf(watched)):
                    event.accept()
                    return True
        return super().eventFilter(watched, event)

    def showEvent(self, event):
        super().showEvent(event)
        tutorial = getattr(getattr(self.launcher_page, 'parent', None), 'tutorial_controller', None)
        if not self._shutdown and not (tutorial is not None and tutorial.visible):
            self.backend.join_from_clipboard()

    def show_friends(self, invitations=False):
        from ui.dialog.FriendsDialog import FriendsDialog
        if self.friends_window is None:
            self.friends_window = FriendsDialog(self, self.resources)
        self.friends_window.showNormal()
        self.backend.act('acknowledgeFriendHome', {})
        if invitations:
            self.friends_window.backend.local['friendTab'] = 2
            self.friends_window.backend.changed.emit()
            self.friends_window.backend.showInvitations.emit()
        self.friends_window.raise_()
        self.friends_window.activateWindow()

    def notify_room(self, message):
        self.notify_social('invite')
        if QSystemTrayIcon.isSystemTrayAvailable():
            tray = getattr(self, '_room_tray', None)
            if tray is None:
                tray = self._room_tray = QSystemTrayIcon(self.windowIcon(), self)
                tray.setToolTip('Buggcraft · 房间准备')
                tray.activated.connect(lambda _: self.show())
                tray.show()
            tray.showMessage('房间准备', message, QSystemTrayIcon.Information, 6000)

    def notify_social(self, priority):
        if self._shutdown:
            return
        settings = getattr(self.launcher_page, 'settings_manager', None)
        if settings is None or settings.get_setting('multiplayer.notification_sound', True):
            self.social_sound.play(priority)
        if priority == 'invite':
            QApplication.alert(self.launcher_page.window() if self.launcher_page else self, 5000)

    def show_friend_invitation(self, invitation):
        """Keep invitations visible even when the friends window is closed."""
        if self._shutdown or not self.backend.view.get('socialReady'):
            return
        invitation = dict(invitation)
        invitation_id = invitation.get('id')
        if (invitation_id and
                (invitation_id == (self._invitation or {}).get('id') or
                 any(item.get('id') == invitation_id for item in self._invitation_queue))):
            return
        if self.invitation_dialog is not None:
            self._invitation_queue.append(invitation)
            QApplication.alert(self.launcher_page.window() if self.launcher_page else self, 0)
            return
        QApplication.alert(self.launcher_page.window() if self.launcher_page else self, 0)
        from ui.dialog.qml_dialog import QmlDialog
        self._invitation = invitation
        dialog = QmlDialog(self, resources=self.resources, title='收到联机邀请',
                           message=invitation['username'] + ' 邀请你加入房间',
                           detail='邀请在发送后 5 分钟内有效。加入前请准备兼容的游戏实例。',
                           actions=['稍后', '查看邀请', '加入房间'], width=500, height=290)
        dialog.setWindowModality(Qt.NonModal)
        dialog.setAttribute(Qt.WA_ShowWithoutActivating)
        self.invitation_dialog = dialog
        dialog.controller.actionRequested.connect(self.invitation_action)
        dialog.finished.connect(self.close_invitation)
        dialog.show()

    def _show_next_invitation(self):
        if (self._shutdown or not self.backend.view.get('socialReady') or
                self.invitation_dialog is not None):
            return
        live = {item.get('id'): item for item in self.backend.view.get('friendInvitations', [])}
        while self._invitation_queue:
            candidate = self._invitation_queue.pop(0)
            invitation_id = candidate.get('id')
            if invitation_id in live:
                self.show_friend_invitation(live[invitation_id])
                return

    def invitation_action(self, action):
        invitation = self._invitation
        if self.invitation_dialog:
            self.invitation_dialog.reject()
        if not invitation:
            return
        if action == '加入房间':
            self.backend.act('joinFriend', dict(account=invitation['account'], id=invitation['id']))
            self.showNormal()
            self.raise_()
            self.activateWindow()
        elif action == '查看邀请':
            self.show_friends(invitations=True)

    def refresh_invitation(self):
        live = {item.get('id') for item in self.backend.view.get('friendInvitations', [])}
        self._invitation_queue = [item for item in self._invitation_queue if item.get('id') in live]
        if self.invitation_dialog and (not self.backend.view['socialReady'] or
                not self._invitation or self._invitation.get('id') not in live):
            self.invitation_dialog.reject()

    def close_invitation(self, *_):
        dialog, self.invitation_dialog = self.invitation_dialog, None
        self._invitation = None
        if dialog:
            dialog.shutdown()
            dialog.deleteLater()
        if self._invitation_queue and not self._shutdown:
            QTimer.singleShot(0, self._show_next_invitation)

    def shutdown(self):
        if self._shutdown:
            return
        self._shutdown = True
        if self.invitation_dialog:
            self.invitation_dialog.reject()
        self.timer.stop()
        self.runtime_timer.stop()
        if self.friends_window:
            self.friends_window.shutdown()
        # Destroy bindings while the QObject context is still alive.
        self.quick.setSource(QUrl())
        self.backend.close()
        self.close()
