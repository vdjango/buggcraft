"""Independent modeless contacts window sharing the lobby's store and service."""
from PySide6.QtCore import QObject, Property, Signal, Slot, Qt, QUrl, QTimer
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QDialog, QVBoxLayout
from utils.app_icon import get_app_icon


class FriendsController(QObject):
    changed = Signal()
    showInvitations = Signal()

    def __init__(self, window, backend):
        super().__init__(window)
        self.window, self.backend = window, backend
        self.local = dict(page='friends', friendTab=0, editIndex=-1, friendName='', friendAccount='', error='', notice='')
        self.adding_friend = False
        self.active = False
        backend.changed.connect(self.changed)
        backend.friend_finished.connect(self.finish_lookup)

    @Slot(bool, str)
    def finish_lookup(self, success, message):
        self.local.update(error='' if success else message, notice=message if success else '')
        if success:
            self.local['page'] = 'friends'
            if self.adding_friend:
                self.local['friendTab'] = 1
        self.adding_friend = False
        self.changed.emit()

    @Property('QVariantMap', notify=changed)
    def view(self):
        return {**self.backend.view, **self.local, 'friendWindowActive': self.active}

    @Slot(str, 'QVariantMap')
    def act(self, action, data):
        try:
            if action == 'navigate':
                self.backend.cancel_friend_lookup()
                self.adding_friend = False
                self.local.update(page=data['page'], editIndex=-1, friendName='', friendAccount='', error='', notice='')
            elif action == 'editFriend':
                self.backend.cancel_friend_lookup()
                index = int(data['index'])
                self.local.update(page='friendForm', editIndex=index, error='', notice='',
                                  friendName=self.backend.store.data['contacts'][index]['name'],
                                  friendAccount=self.backend.store.data['contacts'][index].get('account', ''))
            elif action == 'saveFriend':
                identifier = str(data.get('identifier', '')).strip()
                state = self.backend.view
                self.adding_friend = True
                self.backend.lookup_friend({'identifier': identifier,
                                            'index': data.get('index', -1)})
                self.local.update(error='', notice='正在发送好友申请…')
            elif action == 'removeFriend':
                self.backend.social_operation('remove', data['account'])
                self.local.update(page='friends', error='', notice='')
            elif action in ('setFriendFavorite', 'setFriendAlias', 'copyFriendName', 'copySocialName',
                            'acceptFriend', 'declineFriend', 'inviteFriend', 'refreshFriends',
                            'ignoreFriendInvite', 'cancelFriendInvite', 'continueFriendInvite', 'dismissFriendInvite',
                            'readFriendNotifications', 'requestJoinFriend', 'acceptJoinRequest', 'declineJoinRequest'):
                self.backend.act(action, data)
                if self.backend.view['error']:
                    raise ValueError(self.backend.view['error'])
                if action in ('setFriendFavorite', 'setFriendAlias', 'copyFriendName', 'copySocialName'):
                    self.local.update(notice=self.backend.view.get('notice', ''), error='')
                if action in ('inviteFriend', 'cancelFriendInvite', 'dismissFriendInvite'):
                    self.local.update(notice='', error='')
                if (action == 'inviteFriend' and self.backend.view.get('pendingFriendInvite')) or action == 'continueFriendInvite':
                    self.backend.window.showNormal()
                    self.backend.window.raise_()
                    self.backend.window.activateWindow()
            elif action in ('reloginNode', 'replaceNodeCode'):
                self.backend.act(action, data)
                self.backend.window.showNormal()
                self.backend.window.raise_()
                self.backend.window.activateWindow()
            elif action == 'joinFriend':
                self.backend.act(action, data)
                if self.backend.view['error']:
                    raise ValueError(self.backend.view['error'])
                self.local.update(error='', notice='正在接受邀请并连接房间…')
            elif action == 'clearError':
                self.local.update(error='', notice='')
            elif action == 'close':
                self.backend.cancel_friend_lookup()
                self.window.close()
            elif action == 'minimize':
                self.window.showMinimized()
            elif action == 'drag' and self.window.windowHandle():
                self.window.windowHandle().startSystemMove()
        except Exception as exc:
            if action == 'saveFriend':
                self.adding_friend = False
            self.local['error'] = str(exc) or '操作未完成，请重试。'
        self.changed.emit()


class FriendsDialog(QDialog):
    def hideEvent(self, event):
        self.backend.active = False
        self.backend.changed.emit()
        super().hideEvent(event)

    def __init__(self, owner, resources):
        # Anchor to the launcher, not to the hideable lobby. This window must
        # remain independently usable when opened directly from the home page.
        anchor = getattr(owner, 'launcher_page', None) or owner.parentWidget()
        while anchor is not None and not anchor.isWindow():
            anchor = anchor.parentWidget()
        super().__init__(anchor or owner, Qt.Window | Qt.FramelessWindowHint)
        self.setWindowModality(Qt.NonModal)
        self.setWindowTitle('BUGG · 好友')
        self.setWindowIcon(get_app_icon(resources))
        from utils.windows_taskbar import install_taskbar_identity
        install_taskbar_identity(self, resources)
        self.setFixedSize(520, 540)
        self.backend = FriendsController(self, owner.backend)
        self.quick = QQuickWidget(self)
        self.quick.setResizeMode(QQuickWidget.SizeRootObjectToView)
        self.quick.rootContext().setContextProperty('lobby', self.backend)
        self._source = QUrl.fromLocalFile(str(resources / 'qml/multiplayer/FriendsWindow.qml'))
        self.quick.setSource(self._source)
        if self.quick.status() == QQuickWidget.Error:
            raise RuntimeError('好友窗口加载失败：' + '\n'.join(e.toString() for e in self.quick.errors()))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.quick)
        quick = self.quick
        from shiboken6 import isValid
        self.destroyed.connect(lambda: quick.setSource(QUrl()) if isValid(quick) else None)

    def shutdown(self):
        self.quick.setSource(QUrl())
        self.close()

    def closeEvent(self, event):
        self.backend.backend.cancel_friend_lookup()
        # Release bindings before their QObject context can be destroyed; the
        # model remains available when this independent window is reopened.
        # A QML close button can still be executing its handler at this point.
        QTimer.singleShot(0, self, self._release_content)
        super().closeEvent(event)

    def _release_content(self):
        if not self.isVisible():
            self.quick.setSource(QUrl())

    def showEvent(self, event):
        if self.quick.source().isEmpty():
            self.quick.setSource(self._source)
        super().showEvent(event)
        self.backend.active = True
        self.backend.changed.emit()
