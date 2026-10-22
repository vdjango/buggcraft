"""Independent modeless contacts window sharing the lobby's store and service."""
from PySide6.QtCore import QObject, Property, Signal, Slot, Qt, QUrl
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QDialog, QVBoxLayout


class FriendsController(QObject):
    changed = Signal()

    def __init__(self, window, backend):
        super().__init__(window)
        self.window, self.backend = window, backend
        self.local = dict(page='friends', editIndex=-1, friendName='', friendAccount='', error='', notice='')
        backend.changed.connect(self.changed)
        backend.friend_finished.connect(self.finish_lookup)

    @Slot(bool, str)
    def finish_lookup(self, success, message):
        self.local.update(error='' if success else message, notice=message if success else '')
        if success:
            self.local['page'] = 'friends'
        self.changed.emit()

    @Property('QVariantMap', notify=changed)
    def view(self):
        return {**self.backend.view, **self.local}

    @Slot(str, 'QVariantMap')
    def act(self, action, data):
        try:
            if action == 'navigate':
                self.backend.cancel_friend_lookup()
                self.local.update(page=data['page'], editIndex=-1, friendName='', friendAccount='', error='', notice='')
            elif action == 'editFriend':
                self.backend.cancel_friend_lookup()
                index = int(data['index'])
                self.local.update(page='friendForm', editIndex=index, error='', notice='',
                                  friendName=self.backend.store.data['contacts'][index]['name'],
                                  friendAccount=self.backend.store.data['contacts'][index].get('account', ''))
            elif action == 'saveFriend':
                identifier = str(data.get('identifier', '')).strip()
                self.backend.lookup_friend({'identifier': identifier,
                                            'index': data.get('index', -1)})
                self.local.update(error='', notice='正在发送好友申请…')
            elif action == 'removeFriend':
                self.backend.social_operation('remove', data['account'])
                self.local.update(page='friends', error='', notice='')
            elif action in ('acceptFriend', 'declineFriend', 'inviteFriend', 'refreshFriends'):
                self.backend.act(action, data)
                if self.backend.view['error']:
                    raise ValueError(self.backend.view['error'])
            elif action == 'joinFriend':
                self.backend.act(action, data)
                if self.backend.view['error']:
                    raise ValueError(self.backend.view['error'])
                self.backend.window.showNormal()
                self.backend.window.raise_()
                self.backend.window.activateWindow()
            elif action == 'clearError':
                self.local['error'] = ''
            elif action == 'close':
                self.backend.cancel_friend_lookup()
                self.window.close()
            elif action == 'minimize':
                self.window.showMinimized()
            elif action == 'drag' and self.window.windowHandle():
                self.window.windowHandle().startSystemMove()
        except Exception as exc:
            self.local['error'] = str(exc) or '操作未完成，请重试。'
        self.changed.emit()


class FriendsDialog(QDialog):
    def __init__(self, owner, resources):
        # Anchor to the launcher, not to the hideable lobby. This window must
        # remain independently usable when opened directly from the home page.
        anchor = owner.parentWidget()
        while anchor is not None and not anchor.isWindow():
            anchor = anchor.parentWidget()
        super().__init__(anchor or owner, Qt.Window | Qt.FramelessWindowHint)
        self.setWindowModality(Qt.NonModal)
        self.setWindowTitle('Buggcraft · 好友')
        self.setFixedSize(410, 470)
        self.backend = FriendsController(self, owner.backend)
        self.quick = QQuickWidget(self)
        self.quick.setResizeMode(QQuickWidget.SizeRootObjectToView)
        self.quick.rootContext().setContextProperty('lobby', self.backend)
        self.quick.setSource(QUrl.fromLocalFile(str(resources / 'qml/multiplayer/FriendsWindow.qml')))
        if self.quick.status() == QQuickWidget.Error:
            raise RuntimeError('好友窗口加载失败：' + '\n'.join(e.toString() for e in self.quick.errors()))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.quick)

    def shutdown(self):
        self.quick.setSource(QUrl())
        self.close()

    def closeEvent(self, event):
        self.backend.backend.cancel_friend_lookup()
        super().closeEvent(event)
