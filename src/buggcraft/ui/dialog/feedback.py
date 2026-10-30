"""One form for an issue report and informed diagnostic upload."""
from PySide6.QtCore import QEvent, Signal, Qt

from ui.dialog.qml_dialog import QmlDialog


def feedback_metadata(content):
    description = str(content).strip()
    if not description:
        raise ValueError('请先描述遇到的问题。')
    if len(description) > 4000:
        raise ValueError('问题描述最多 4000 字，请精简后提交。')
    title = description.splitlines()[0].strip()[:120]
    # The node accepts two fields; the user only needs to write their report.
    import json
    if len(json.dumps({'title': title, 'description': description}, ensure_ascii=False).encode('utf-8')) > 6500:
        raise ValueError('内容较长，请适当精简后提交（最多 6500 UTF-8 字节）。')
    return title, description


class FeedbackDialog(QmlDialog):
    submitted = Signal(str, str)

    def __init__(self, parent, *, content='', node='当前节点'):
        screen = parent.screen()
        height = min(640, screen.availableGeometry().height() - 60) if screen else 640
        super().__init__(parent, resources=parent.resources, title='反馈问题',
                         source='FeedbackDialog.qml', width=640, height=height,
                         data=dict(content=content, node=node, error=''))
        self.setObjectName('feedback-dialog')
        self.setWindowModality(Qt.WindowModal)
        self.controller.actionRequested.connect(self._action)
        self.quick.installEventFilter(self)
        self.quick.quickWindow().installEventFilter(self)

    def eventFilter(self, watched, event):
        # Consume Escape within this form before the lobby's QML shortcut or
        # QDialog parent propagation can close the underlying lobby as well.
        if event.type() in (QEvent.ShortcutOverride, QEvent.KeyPress) and event.key() == Qt.Key_Escape:
            event.accept()
            if event.type() == QEvent.KeyPress:
                self.reject()
            return True
        return super().eventFilter(watched, event)

    def _action(self, action):
        if action == 'cancel':
            self.reject()
        elif action == 'submit':
            try:
                title, description = feedback_metadata(self.controller.data.get('content', ''))
            except ValueError as error:
                self.controller.data['error'] = str(error)
                self.controller.changed.emit()
                return
            self.controller.actions_enabled = False
            self.submitted.emit(title, description)
            self.accept()
