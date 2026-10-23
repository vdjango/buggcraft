"""Microsoft device login with a shared QML dialog."""
from PySide6.QtCore import QTimer, Signal
from core.auth.microsoft import MicrosoftAuthenticator
from ui.dialog.qml_dialog import QmlDialog


class LoginWaitDialog(QmlDialog):
    cancel_signal = Signal()
    reopen_signal = Signal()

    def __init__(self, resource_path, cache_path, parent=None):
        super().__init__(parent, resources=resource_path, title='登录到 Minecraft',
                         message='正在为您打开登录页面…', width=650, height=360,
                         detail='在微软官方页面输入下方登录码，选择拥有 Minecraft Java 版的账号。完成验证后，启动器会自动读取正版角色。',
                         actions=['重新登录', '取消'])
        self._login_pending = False
        self._device_code = ''
        self.auth = MicrosoftAuthenticator(skins_cache_path=cache_path)
        self.auth.signals.success.connect(self.login_succeeded)
        self.auth.signals.failure.connect(self.set_messages)
        self.auth.signals.progress.connect(self.set_messages)
        self.auth.signals.device_code.connect(self.show_device_code)
        self.controller.actionRequested.connect(self._action)

    def _action(self, name):
        if name == '重新登录':
            self.reopen_browser()
        else:
            self.reject()

    def set_messages(self, message):
        self.set_message(message)

    def start_login_process(self):
        self._login_pending = True
        self._device_code = ''
        self.controller.code = self.controller.uri = ''
        self.controller.copied = False
        self.set_messages('正在连接微软登录服务…')
        self.reopen_signal.emit()
        QTimer.singleShot(0, lambda: self.auth.start_login() if self._login_pending else None)

    def reopen_browser(self):
        self.auth.cancel_authentication()
        self.start_login_process()

    def show_device_code(self, code, uri):
        self._device_code = code
        self.controller.code, self.controller.uri = code, uri
        self.controller.changed.emit()

    def copy_device_code(self):
        self.controller.copyCode()

    def login_succeeded(self, username, data):
        self._login_pending = False
        self.accept()

    def cancel_reject(self):
        self.reject()

    def close_reject(self):
        self.reject()

    def reject(self):
        self._login_pending = False
        self.auth.cancel_authentication()
        self.cancel_signal.emit()
        super().reject()
