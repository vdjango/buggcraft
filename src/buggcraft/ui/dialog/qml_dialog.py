"""Shared native dialog host with Qt Quick content."""
from pathlib import Path
from PySide6.QtCore import QObject, Property, QTimer, Qt, Signal, Slot
from PySide6.QtWidgets import QDialog, QVBoxLayout
from ui.pages.qml_host import QmlPage
from utils.clipboard import copy_text


class DialogController(QObject):
    changed = Signal()
    actionRequested = Signal(str)

    def __init__(self, parent, title, message='', detail='', actions=None,
                 primary_action=None, danger_action=''):
        super().__init__(parent)
        self.title, self.message, self.detail = title, message, detail
        self.actions = actions or []
        self.primary_action = (self.actions[0] if self.actions else '') if primary_action is None else primary_action
        self.danger_action = danger_action
        self.code = self.uri = self.log = ''
        self.copied = False
        self.working = False
        self.progress = 0.
        self.dismissible = True
        self.actions_enabled = True
        self.data = {}
        self._copy_timer = QTimer(self)
        self._copy_timer.setSingleShot(True)
        self._copy_timer.timeout.connect(self._reset_copy)

    @Property('QVariantMap', notify=changed)
    def view(self):
        return dict(title=self.title, message=self.message, detail=self.detail,
                    actions=self.actions, code=self.code, uri=self.uri,
                    copied=self.copied, log=self.log, working=self.working, progress=self.progress,
                    primaryAction=self.primary_action, dangerAction=self.danger_action,
                    actionsEnabled=self.actions_enabled, data=self.data)

    @Slot(str)
    def action(self, name):
        self.actionRequested.emit(name)

    @Slot(str, str)
    def setDataValue(self, key, value):
        self.data[key] = value
        self.changed.emit()

    @Slot()
    def copyCode(self):
        if self.code:
            copy_text(self, self.code, self._copied, self._reset_copy)

    def _copied(self):
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
                 actions=None, width=550, height=320, primary_action=None, danger_action='',
                 source='DialogContent.qml', data=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setWindowTitle(title)
        self.resize(width, height)
        self.setMinimumSize(width, height)
        resources = resources or getattr(parent, 'resource_path', None) or Path(__file__).resolve().parents[4] / 'resources'
        self.controller = DialogController(self, title, message, detail, actions, primary_action, danger_action)
        self.controller.data = data or {}
        self._shutdown_scheduled = False
        self.host = QmlPage(self, resources, source, 'dialogModel', self.controller)
        self.quick = self.host.quick
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.host)

    def set_title(self, value):
        self.controller.title = value
        self.setWindowTitle(value)
        self.controller.changed.emit()

    def reject(self):
        if self.controller.dismissible:
            super().reject()

    def closeEvent(self, event):
        if not self.controller.dismissible:
            event.ignore()
            return
        super().closeEvent(event)

    def set_message(self, value):
        self.controller.message = value
        self.controller.changed.emit()

    def set_message_text(self, value):
        self.controller.detail = value
        self.controller.changed.emit()

    def shutdown(self):
        self.controller._copy_timer.stop()
        # A QML button may still be on the stack when finished/actionRequested
        # fires. Never destroy its engine content until that callback returns.
        if not self._shutdown_scheduled:
            self._shutdown_scheduled = True
            QTimer.singleShot(0, self.host, self.host.unload)


class DebugOutputDialog(QmlDialog):
    def __init__(self, parent, lines):
        super().__init__(parent, title='Minecraft · 游戏日志', width=960, height=580, actions=['关闭'],
                         source='DebugConsole.qml')
        from .game_log import GameLogModel
        self.logs = GameLogModel(self)
        self.host.quick.rootContext().setContextProperty('debugLogs', self.logs)
        self._lines = list(lines)[-5000:]
        self.logs.append(self._lines)
        self._pending_lines = []
        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.setInterval(100)
        self._flush_timer.timeout.connect(self._flush)
        self.controller.actionRequested.connect(lambda _: self.close())
        self._flush()

    def appendPlainText(self, text):
        self._lines.append(text)
        self._pending_lines.append(text)
        del self._lines[:-5000]
        if not self._flush_timer.isActive():
            self._flush_timer.start()

    def _flush(self):
        if self._pending_lines:
            self.logs.append(self._pending_lines)
            self._pending_lines.clear()
        self.controller.log = '\n'.join(self._lines) or '等待游戏输出…'
        self.controller.changed.emit()

    def shutdown(self):
        self._flush_timer.stop()
        super().shutdown()
