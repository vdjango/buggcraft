"""Visible launcher update state shared by startup and the settings page."""
import logging
from pathlib import Path
import platform
import sys
import time

from PySide6.QtCore import QObject, Property, QThread, QTimer, QUrl, Qt, Signal, Slot
from PySide6.QtGui import QDesktopServices

from config.settings import get_settings_manager
from core.update_client import apply_update, check_for_update, current_version, download_update

logger = logging.getLogger(__name__)
STARTUP_DELAY_MS = 10_000
CHECK_INTERVAL_MS = 4 * 60 * 60 * 1000
REMINDER_SECONDS = 24 * 60 * 60


class CheckWorker(QThread):
    result = Signal(object, str)

    def __init__(self, parent, version, channel):
        super().__init__(parent)
        self.version, self.channel = version, channel

    def run(self):
        try:
            self.result.emit(check_for_update(self.version, self.channel), '')
        except Exception as exc:
            logger.warning('Launcher update check failed: %s', exc)
            self.result.emit(None, str(exc))


class DownloadWorker(QThread):
    progress = Signal(object, object)
    completed = Signal(object, str)

    def __init__(self, parent, update):
        super().__init__(parent)
        self.update = update

    def run(self):
        try:
            executable = Path(sys.argv[0]).resolve()
            directory = executable.parent
            if platform.system() == 'Darwin':
                directory = next(parent for parent in executable.parents if parent.suffix == '.app').parent
            package = download_update(self.update, directory,
                                      lambda done, total: self.progress.emit(done, total))
            self.completed.emit(package, '')
        except Exception as exc:
            self.completed.emit(None, str(exc))


class LauncherUpdateController(QObject):
    changed = Signal()

    def __init__(self, launcher, app, resource_path, packaged=True):
        super().__init__(launcher)
        self.launcher, self.app = launcher, app
        self.version = current_version(resource_path)
        self.packaged = packaged
        self.resource_path = resource_path
        self.workers = []
        self.dialog = None
        self._checking = self._downloading = False
        self._pending_manual = False
        self._stopping = False
        self._status = '等待自动检查更新' if packaged else '源码运行；可检查官网下载版本'
        self.timer = QTimer(self)
        self.timer.setInterval(CHECK_INTERVAL_MS)
        self.timer.timeout.connect(self.check)
        self.startup_timer = QTimer(self)
        self.startup_timer.setSingleShot(True)
        self.startup_timer.setInterval(STARTUP_DELAY_MS)
        self.startup_timer.timeout.connect(self.check)
        self.app.aboutToQuit.connect(self.shutdown)

    @Property(str, constant=True)
    def currentVersion(self):
        return self.version

    @Property(str, notify=changed)
    def status(self):
        return self._status

    @Property(bool, notify=changed)
    def busy(self):
        return self._checking or self._downloading

    def channel(self):
        setting = get_settings_manager().get_setting('settings.general.update', 'stable')
        return 'beta' if setting == 'development' else 'stable'

    def _set_status(self, text):
        self._status = text
        self.changed.emit()

    def start(self):
        if self.packaged:
            self.startup_timer.start()
            self.timer.start()

    @Slot()
    def channel_changed(self):
        # An in-flight response belongs to its original channel, so discard it
        # and check the newly selected channel as soon as it finishes.
        self.check(manual=True)

    @Slot()
    def check(self, manual=False):
        if self._stopping:
            return
        if self._downloading:
            if manual and self.dialog:
                self.dialog.show()
                self.dialog.raise_()
            return
        if self._checking:
            self._pending_manual |= manual
            return
        channel = self.channel()
        channel_name = '开发版' if channel == 'beta' else '稳定版'
        self._checking = True
        self._set_status(f'正在检查{channel_name}更新…')
        logger.info('Checking launcher updates: current=%s channel=%s', self.version, channel)
        worker = CheckWorker(self, self.version, channel)
        self.workers.append(worker)

        def completed(update, error):
            worker.wait()
            self.workers.remove(worker)
            worker.deleteLater()
            self._checking = False
            if self._stopping:
                return
            pending = self._pending_manual
            self._pending_manual = False
            if channel != self.channel():
                self.check(manual=True)
                return
            if error:
                self._set_status('检查更新失败，请检查网络后重试')
                if manual or pending:
                    self._show_error('暂时无法检查更新', '请检查网络连接后重试。当前版本可以继续使用。', error,
                                     lambda: self.check(manual=True))
            elif update:
                self._set_status(f"发现新版本 {update['version']}")
                logger.info('Launcher update available: %s', update['version'])
                self.offer(update, manual or pending)
            else:
                self._set_status(f'当前已是{channel_name}通道最新可用版本（{self.version}）')
                logger.info('Launcher update check complete: no newer %s release', channel)
            if pending:
                self.changed.emit()

        worker.result.connect(completed)
        worker.start()

    def offer(self, update, manual=False):
        if self._downloading:
            return
        settings = get_settings_manager()
        reminder = settings.get_setting('settings.general.update_reminder', {})
        if not manual and isinstance(reminder, dict) and reminder.get('version') == update['version']:
            try:
                if float(reminder.get('until', 0)) > time.time():
                    return
            except (ValueError, TypeError, OverflowError):
                pass
        if self.dialog and self.dialog.isVisible() and self.dialog.controller.data.get('phase') == 'offer':
            if self.dialog.controller.data.get('version') == update['version']:
                self.dialog.raise_()
                return
        install = '立即更新' if self.packaged else '打开官网下载'
        dialog = self._show_dialog('发现新版本', '新的启动器版本已准备就绪。',
                                  update.get('notes') or '修复问题并改进启动器体验。',
                                  ['稍后提醒', install], install, update, 'offer')
        dialog.controller.data['footer'] = ('启动 10 秒后首次检查，此后每 4 小时检查一次。更新完成后自动重启。'
                                            if self.packaged else '源码运行时从官网下载打包版本。') + \
                                           '稍后提醒将在 24 小时后再次提示。'
        dialog.controller.changed.emit()
        def action(name):
            if name == install:
                dialog.accept()
                self._install_requested(update)
            else:
                dialog.reject()
        dialog.controller.actionRequested.connect(action)
        def remind_later():
            settings.set_setting('settings.general.update_reminder',
                                 {'version': update['version'], 'until': time.time() + REMINDER_SECONDS})
            settings.save_settings()
        dialog.rejected.connect(remind_later)

    def _install_requested(self, update):
        if not self.packaged:
            self.open_download_page(update)
            return
        started = getattr(self.launcher, 'started_page', None)
        if started and started.launcher.running:
            self._show_error('请先关闭游戏', '游戏正在运行，暂时无法替换启动器。',
                             '关闭游戏后点击重试，即可开始下载更新。', lambda: self._install_requested(update), update)
            return
        self.download(update)

    @staticmethod
    def _file_size(size):
        return f'{size / 1024 / 1024:.1f} MB'

    def _show_dialog(self, title, message, detail, actions, primary, update=None, phase='error'):
        from ui.dialog.qml_dialog import QmlDialog

        self._close_dialog()
        update = update or {}
        size = update.get('asset', {}).get('size', 0)
        dialog = QmlDialog(self.launcher, resources=self.resource_path, title=title, message=message,
                           detail=detail, actions=actions, primary_action=primary, width=600, height=530,
                           source='LauncherUpdate.qml', data={
                               'phase': phase, 'version': update.get('version', ''), 'currentVersion': self.version,
                               'channelName': '开发版' if self.channel() == 'beta' else '稳定版',
                               'packageSize': self._file_size(size) if size else '',
                           })
        self.dialog = dialog
        def finished(_):
            if self.dialog is dialog:
                self.dialog = None
            dialog.shutdown()
            dialog.deleteLater()
        dialog.finished.connect(finished, Qt.QueuedConnection)
        dialog.open()
        return dialog

    def _close_dialog(self):
        if self.dialog:
            dialog, self.dialog = self.dialog, None
            dialog.accept()

    def _show_error(self, title, message, detail, retry, update=None):
        dialog = self._show_dialog(title, message, detail, ['关闭', '官网下载', '重试'], '重试', update)
        def action(name):
            dialog.accept()
            if name == '重试':
                retry()
            elif name == '官网下载':
                self.open_download_page(update or {})
        dialog.controller.actionRequested.connect(action)

    def download(self, update):
        if self._downloading:
            return
        self._downloading = True
        self._set_status('正在下载并校验更新…')
        dialog = self._show_dialog('正在更新启动器', '下载完成并通过校验后，启动器将自动重启。',
                                  update.get('notes') or '修复问题并改进启动器体验。',
                                  ['后台下载'], '', update, 'download')
        dialog.controller.working = True
        dialog.controller.dismissible = False
        dialog.controller.data['footer'] = '安装包将核对大小与 SHA-256。校验失败时保留当前版本。'
        dialog.controller.changed.emit()
        dialog.controller.actionRequested.connect(lambda _: dialog.hide())
        worker = DownloadWorker(self, update)
        self.workers.append(worker)
        def progress(done, total):
            model = dialog.controller
            model.progress = min(1., done / total) if total else 0.
            model.data['progressText'] = ('正在校验安装包…' if done == total else
                                          self._file_size(done) + ' / ' + self._file_size(total))
            model.changed.emit()
        worker.progress.connect(progress)

        def complete(package, error):
            worker.wait()
            self.workers.remove(worker)
            worker.deleteLater()
            self._close_dialog()
            self._downloading = False
            if self._stopping:
                return
            if error:
                self._set_status('更新下载或校验失败，可以重新检查并重试')
                logger.warning('Launcher update download failed: %s', error)
                self._show_error('更新未完成', '当前版本已保留，可以重试或从官网下载。', error,
                                 lambda: self.download(update), update)
                return
            try:
                self._set_status('校验通过，正在安装并重启…')
                logger.info('Launcher update verified; scheduling installation: %s', update['version'])
                apply_update(Path(package))
                self.app.quit()
            except Exception as exc:
                self._set_status('自动安装失败，请从官网手动下载')
                logger.exception('Could not install launcher update')
                self._show_error('暂时无法安装更新', '当前版本已保留，请重试或从官网下载。', str(exc),
                                 lambda: self._install_requested(update), update)

        worker.completed.connect(complete)
        worker.start()

    @staticmethod
    def open_download_page(update):
        QDesktopServices.openUrl(QUrl(update.get('download_page') or 'https://download.bugg.icu/'))

    @Slot()
    def shutdown(self):
        self._stopping = True
        self.timer.stop()
        self.startup_timer.stop()
        for worker in list(self.workers):
            worker.wait()
        self._close_dialog()
