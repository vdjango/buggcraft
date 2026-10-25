"""Visible launcher update state shared by startup and the settings page."""
import logging
from pathlib import Path
import platform
import sys

from PySide6.QtCore import QObject, Property, QThread, QTimer, QUrl, Qt, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox, QProgressDialog

from config.settings import get_settings_manager
from core.update_client import apply_update, check_for_update, current_version, download_update

logger = logging.getLogger(__name__)


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
    progress = Signal(int)
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
                                      lambda done, total: self.progress.emit(int(done * 1000 / total)))
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
        self.workers = []
        self.prompted = set()
        self._checking = self._downloading = False
        self._pending_manual = False
        self._status = '等待自动检查更新' if packaged else '源码运行；可检查官网下载版本'
        self.timer = QTimer(self)
        self.timer.setInterval(60 * 60 * 1000)
        self.timer.timeout.connect(self.check)
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
            QTimer.singleShot(7000, self.check)
            self.timer.start()

    @Slot()
    def channel_changed(self):
        # An in-flight response belongs to its original channel, so discard it
        # and check the newly selected channel as soon as it finishes.
        self.check(manual=True)

    @Slot()
    def check(self, manual=False):
        if self._downloading:
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
            pending = self._pending_manual
            self._pending_manual = False
            if channel != self.channel():
                self.check(manual=True)
                return
            if error:
                self._set_status('检查更新失败，请检查网络后重试')
                if manual or pending:
                    QMessageBox.warning(self.launcher, '检查更新失败', error + '\n\n可以重试，或从官网手动下载。')
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
        if self._downloading or (update['version'] in self.prompted and not manual):
            return
        self.prompted.add(update['version'])
        box = QMessageBox(self.launcher)
        box.setWindowTitle('发现启动器更新')
        box.setIcon(QMessageBox.Information)
        box.setTextFormat(Qt.PlainText)
        box.setText(f"Buggcraft {update['version']} 已发布。\n当前版本：{self.version}")
        box.setInformativeText(update.get('notes') or '修复问题并改进启动器体验。')
        install = box.addButton('立即更新' if self.packaged else '打开官网下载', QMessageBox.AcceptRole)
        box.addButton('稍后提醒', QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is not install:
            return
        if not self.packaged:
            self.open_download_page(update)
            return
        started = getattr(self.launcher, 'started_page', None)
        if started and started.launcher.running:
            QMessageBox.information(self.launcher, '请先关闭游戏', '请关闭游戏后，在设置中点击「检查更新」重试。')
            return
        self.download(update)

    def download(self, update):
        self._downloading = True
        self._set_status('正在下载并校验更新…')
        progress = QProgressDialog(self._status, None, 0, 1000, self.launcher)
        progress.setWindowTitle('更新 Buggcraft')
        progress.setWindowModality(Qt.WindowModal)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.setValue(0)
        worker = DownloadWorker(self, update)
        self.workers.append(worker)
        worker.progress.connect(progress.setValue)

        def complete(package, error):
            worker.wait()
            self.workers.remove(worker)
            worker.deleteLater()
            progress.close()
            self._downloading = False
            if error:
                self._set_status('更新下载或校验失败，可以重新检查并重试')
                logger.warning('Launcher update download failed: %s', error)
                QMessageBox.warning(self.launcher, '更新下载失败', error + '\n\n将打开官网对应平台的下载页面。')
                self.open_download_page(update)
                return
            try:
                self._set_status('校验通过，正在安装并重启…')
                logger.info('Launcher update verified; scheduling installation: %s', update['version'])
                apply_update(Path(package))
                self.app.quit()
            except Exception as exc:
                self._set_status('自动安装失败，请从官网手动下载')
                logger.exception('Could not install launcher update')
                QMessageBox.warning(self.launcher, '无法自动安装', str(exc) + '\n\n将打开官网对应平台的下载页面。')
                self.open_download_page(update)

        worker.completed.connect(complete)
        worker.start()
        progress.show()

    @staticmethod
    def open_download_page(update):
        QDesktopServices.openUrl(QUrl(update.get('download_page') or 'https://download.bugg.icu/'))

    @Slot()
    def shutdown(self):
        self.timer.stop()
        for worker in list(self.workers):
            worker.wait()
