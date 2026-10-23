from PySide6.QtCore import Signal
from PySide6.QtWidgets import QDialog
from ui.dialog.qml_dialog import QmlDialog


class VersionNotFuilDialog(QmlDialog):
    import_signal = Signal()
    download_signal = Signal()

    def __init__(self, parent=None):
        super().__init__(parent, title='选择一个游戏实例',
                         message='还没有安装 Minecraft 游戏版本。',
                         detail='可以下载游戏、导入整合包，或在实例页添加已有的 .minecraft 文件夹。',
                         actions=['下载游戏', '添加游戏目录', '取消'])
        self.controller.actionRequested.connect(self._action)

    def _action(self, name):
        if name == '下载游戏':
            self.on_download()
        elif name == '添加游戏目录':
            self.on_import()
        else:
            self.reject()

    def on_download(self):
        self.download_signal.emit()
        self.accept()

    def on_import(self):
        self.import_signal.emit()
        self.accept()
