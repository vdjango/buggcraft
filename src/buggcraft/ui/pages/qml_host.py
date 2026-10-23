"""Qt Quick host shared by launcher pages."""
import logging
from pathlib import Path

from PySide6.QtCore import QUrl, Qt
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QVBoxLayout, QWidget

logger = logging.getLogger(__name__)
QQuickStyle.setStyle('Basic')


class QmlPage(QWidget):
    def __init__(self, parent, resource_path, source, context_name, controller, *, own_controller=True):
        super().__init__(parent)
        self.controller = controller
        if own_controller:
            controller.setParent(self)
        self.quick = QQuickWidget(self)
        self.quick.setResizeMode(QQuickWidget.SizeRootObjectToView)
        self.quick.setClearColor(Qt.transparent)
        self._context_name = context_name
        self._source = QUrl.fromLocalFile(str(Path(resource_path) / 'qml' / 'launcher' / source))
        self._loaded = False
        self.quick.statusChanged.connect(self._on_status)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.quick)
        quick = self.quick
        self.destroyed.connect(lambda: quick.setSource(QUrl()))

    def ensure_loaded(self):
        if not self._loaded:
            self._loaded = True
            self.quick.rootContext().setContextProperty(self._context_name, self.controller)
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
