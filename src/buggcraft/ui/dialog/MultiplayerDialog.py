"""QML multiplayer window embedded in the existing launcher."""
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QDialog, QVBoxLayout

from ui.multiplayer_controller import MultiplayerController


class MultiplayerDialog(QDialog):
    def __init__(self, parent=None, storage_path=None):
        # A native owned dialog is minimized automatically with its owner on
        # Windows. Lifecycle remains explicitly managed by the launcher.
        super().__init__(None, Qt.Window | Qt.FramelessWindowHint)
        self.launcher_page = parent
        self._shutdown = False
        if parent is not None:
            parent.destroyed.connect(self.deleteLater)
        self.setWindowTitle('Buggcraft · 一起玩')
        # Match the launcher's original collapsed canvas (926 - 205, 505).
        main_window = getattr(parent, 'parent', None)
        background = getattr(main_window, 'bg_image', None)
        width = background.width() - main_window.menu_width if background else 721
        height = background.height() if background else 505
        self.setFixedSize(width, height)
        resources = Path(getattr(parent, 'resource_path', None) or
                         Path(__file__).resolve().parents[4] / 'resources')
        self.resources = resources
        self.friends_window = None
        self.backend = MultiplayerController(self, storage_path)
        if hasattr(parent, 'friends_btn'):
            self.backend.changed.connect(lambda: parent.friends_btn.setVisible(self.backend.view['socialReady']))
            parent.friends_btn.setVisible(self.backend.view['socialReady'])
        if parent is not None and hasattr(parent, 'instance_changed'):
            parent.instance_changed.connect(self.backend.detect_instance)
        self.service = self.backend.service
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.quick = QQuickWidget(self)
        self.quick.setResizeMode(QQuickWidget.SizeRootObjectToView)
        self.quick.rootContext().setContextProperty('lobby', self.backend)
        self.quick.setSource(QUrl.fromLocalFile(str(resources / 'qml/multiplayer/Lobby.qml')))
        if self.quick.status() == QQuickWidget.Error:
            self.backend.close()
            raise RuntimeError('联机页面加载失败：' + '\n'.join(e.toString() for e in self.quick.errors()))
        layout.addWidget(self.quick)
        self.timer = QTimer(self)
        self.timer.setInterval(15000)
        self.timer.timeout.connect(lambda: self.backend.check_node() if self.isVisible() else None)
        self.timer.start()
        self.backend.detect_instance()
        self.runtime_timer = QTimer(self)
        self.runtime_timer.setInterval(3000)
        self.runtime_timer.timeout.connect(self.backend.detect_runtime)
        self.runtime_timer.start()
        self.backend.detect_runtime()

    def detect_instance(self):
        self.backend.detect_instance()

    def show_friends(self):
        from ui.dialog.FriendsDialog import FriendsDialog
        if self.friends_window is None:
            self.friends_window = FriendsDialog(self, self.resources)
        self.friends_window.showNormal()
        self.friends_window.raise_()
        self.friends_window.activateWindow()

    def shutdown(self):
        if self._shutdown:
            return
        self._shutdown = True
        self.timer.stop()
        self.runtime_timer.stop()
        if self.friends_window:
            self.friends_window.shutdown()
        # Destroy bindings while the QObject context is still alive.
        self.quick.setSource(QUrl())
        self.backend.close()
        self.close()
