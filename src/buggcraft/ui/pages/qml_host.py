"""Qt Quick host shared by launcher pages."""
import logging
from pathlib import Path

from PySide6.QtCore import QUrl, Qt
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QVBoxLayout, QWidget
import shiboken6

logger = logging.getLogger(__name__)
QQuickStyle.setStyle('Basic')


class QmlPage(QWidget):
    def __init__(self, parent, resource_path, source, context_name, controller, *, own_controller=True):
        super().__init__(parent)
        self.controller = controller
        if own_controller:
            controller.setParent(self)
        self._quick = None
        self._context_name = context_name
        self._source = QUrl.fromLocalFile(str(Path(resource_path) / 'qml' / 'launcher' / source))
        self._loaded = False
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)

    @property
    def quick(self):
        # Hidden pages retain their controllers without creating unused engines.
        if self._quick is None:
            self._quick = QQuickWidget(self)
            self._quick.setResizeMode(QQuickWidget.SizeRootObjectToView)
            self._quick.setClearColor(Qt.transparent)
            self._quick.statusChanged.connect(self._on_status)
            self._layout.addWidget(self._quick)
            window = self.window()
            drop_filter = getattr(window, '_modpack_drop_filter', None)
            if drop_filter is not None:
                self._quick.setAcceptDrops(True)
                self._quick.installEventFilter(drop_filter)
            quick = self._quick
            self.destroyed.connect(lambda: quick.setSource(QUrl()) if shiboken6.isValid(quick) else None)
        return self._quick

    def ensure_loaded(self):
        if not self._loaded:
            self._loaded = True
            self.quick.rootContext().setContextProperty(self._context_name, self.controller)
            tutorial = getattr(self.window(), 'tutorial_controller', None)
            if tutorial is not None:
                self.quick.rootContext().setContextProperty('tutorial', tutorial)
            self.quick.setSource(self._source)

    def showEvent(self, event):
        self.ensure_loaded()
        super().showEvent(event)

    def unload(self):
        if self._loaded:
            self.quick.setSource(QUrl())
            self._loaded = False

    def _on_status(self, status):
        if status == QQuickWidget.Error:
            for error in self.quick.errors():
                logger.error('QML %s: %s', self.quick.source().toString(), error.toString())
