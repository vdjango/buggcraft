from PySide6.QtCore import Signal
from ui.dialog.qml_dialog import QmlDialog


class JavaRuntimeNotFuilDialog(QmlDialog):
    import_signal = Signal()
    download_signal = Signal()

    def __init__(self, parent=None, width=550, heiht=350):
        super().__init__(parent, title='准备 Java 环境', width=width, height=heiht,
                         message='当前游戏需要可用的 Java 运行环境。',
                         detail='下载并安装适合游戏版本的 Java，随后在设置中的 Java 管理页添加或刷新。',
                         actions=['下载 Java', '取消'])
        self.controller.actionRequested.connect(self._action)

    def _action(self, name):
        if name == '下载 Java':
            self.on_download()
        else:
            self.reject()

    def on_download(self):
        self.download_signal.emit()
        self.accept()

    def on_import(self):
        self.import_signal.emit()
        self.accept()
