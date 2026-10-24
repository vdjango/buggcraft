"""Shared native dialog host with Qt Quick content."""
from pathlib import Path
from PySide6.QtCore import QObject, Property, QTimer, QUrl, Qt, Signal, Slot
from PySide6.QtWidgets import QApplication, QDialog, QVBoxLayout
from ui.pages.qml_host import QmlPage


class DialogController(QObject):
    changed = Signal()
    actionRequested = Signal(str)

    def __init__(self, parent, title, message='', detail='', actions=None):
        super().__init__(parent)
        self.title, self.message, self.detail = title, message, detail
        self.actions = actions or []
        self.code = self.uri = self.log = ''
        self.copied = False
        self.working = False
        self.progress = 0.
        self._copy_timer = QTimer(self)
        self._copy_timer.setSingleShot(True)
        self._copy_timer.timeout.connect(self._reset_copy)

    @Property('QVariantMap', notify=changed)
    def view(self):
        return dict(title=self.title, message=self.message, detail=self.detail,
                    actions=self.actions, code=self.code, uri=self.uri,
                    copied=self.copied, log=self.log, working=self.working, progress=self.progress)

    @Slot(str)
    def action(self, name):
        self.actionRequested.emit(name)

    @Slot()
    def copyCode(self):
        if self.code:
            QApplication.clipboard().setText(self.code)
            self.copied = True
            self.changed.emit()
            self._copy_timer.start(1500)

    def _reset_copy(self):
        self.copied = False
        self.changed.emit()

    @Slot()
    def dragWindow(self):
        handle = self.parent().window().windowHandle()
        if handle:
            handle.startSystemMove()


class QmlDialog(QDialog):
    def __init__(self, parent=None, *, resources=None, title='', message='', detail='',
                 actions=None, width=550, height=320):
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setWindowTitle(title)
        self.resize(width, height)
        self.setMinimumSize(width, height)
        resources = resources or getattr(parent, 'resource_path', None) or Path(__file__).resolve().parents[4] / 'resources'
        self.controller = DialogController(self, title, message, detail, actions)
        self.host = QmlPage(self, resources, 'DialogContent.qml', 'dialogModel', self.controller)
        self.quick = self.host.quick
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.host)

    def set_title(self, value):
        self.controller.title = value
        self.setWindowTitle(value)
        self.controller.changed.emit()

    def set_message(self, value):
        self.controller.message = value
        self.controller.changed.emit()

    def set_message_text(self, value):
        self.controller.detail = value
        self.controller.changed.emit()

    def shutdown(self):
        self.controller._copy_timer.stop()
        self.quick.setSource(QUrl())


class DebugOutputDialog(QmlDialog):
    def __init__(self, parent, lines):
        super().__init__(parent, title='Minecraft · 调试输出', width=760, height=440, actions=['关闭'])
        self._lines = list(lines)[-5000:]
        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.setInterval(100)
        self._flush_timer.timeout.connect(self._flush)
        self.controller.actionRequested.connect(lambda _: self.close())
        self._flush()

    def appendPlainText(self, text):
        self._lines.append(text)
        del self._lines[:-5000]
        if not self._flush_timer.isActive():
            self._flush_timer.start()

    def _flush(self):
        self.controller.log = '\n'.join(self._lines) or '等待游戏输出…'
        self.controller.changed.emit()

    def shutdown(self):
        self._flush_timer.stop()
        super().shutdown()
