"""Instance operations with a fixed two-column QML layout."""
import json
import os
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Property, QRunnable, QThreadPool, Qt, QTimer, Signal, Slot
from PySide6.QtWidgets import QFileDialog

from config.settings import get_settings_manager
from core.minecraft.version import delete_minecraft_directory, delete_minecraft_version, open_folder
from core.modpacks import export_pack
from core.downloads import DownloadCancelled
from ui.dialog.qml_dialog import QmlDialog
from ui.pages.qml_host import QmlPage
from utils.instances import installed_instance_ids
from utils.path_helper import filesystem_path


class MinecraftSettingSignals(QObject):
    versions = Signal(str)
    directory = Signal(str)


class _DeleteSignals(QObject):
    finished = Signal(str)


class _ExportSignals(QObject):
    progress = Signal(str, object, object)
    finished = Signal(object, str)


class _ExportWorker(QRunnable):
    def __init__(self, directory, identity, destination, mode, game_directory):
        super().__init__()
        self.arguments = directory, identity, destination
        self.mode, self.game_directory = mode, game_directory
        self.cancel = threading.Event()
        self.signals = _ExportSignals()

    def run(self):
        try:
            result = export_pack(*self.arguments, mode=self.mode, game_directory=self.game_directory,
                                 progress=self.signals.progress.emit, cancel=self.cancel)
        except DownloadCancelled:
            self.signals.finished.emit(None, '导出已取消')
        except Exception as exc:
            self.signals.finished.emit(None, str(exc) or type(exc).__name__)
        else:
            self.signals.finished.emit(result, '')


class _DeleteWorker(QRunnable):
    def __init__(self, parent, pending):
        super().__init__()
        self.pending = dict(pending)
        self.signals = _DeleteSignals(parent)

    def run(self):
        identity = self.pending['identity']
        directory = self.pending['directory']
        try:
            if self.pending['action'] == 'deleteDirectory':
                deleted = delete_minecraft_directory(identity, raise_errors=True)
            else:
                for version in installed_instance_ids(directory):
                    metadata = json.loads(filesystem_path(Path(directory) / 'versions' / version / (version + '.json')).read_text(encoding='utf-8'))
                    if not isinstance(metadata, dict):
                        raise ValueError(f'{version} 的版本信息格式无效，无法安全检查依赖。')
                    room = metadata.get('buggcraftRoom')
                    if (metadata.get('inheritsFrom') == identity or metadata.get('jar') == identity
                            or isinstance(room, dict) and room.get('parent') == identity):
                        raise ValueError(f'{version} 仍依赖此实例，请先处理依赖。')
                deleted = delete_minecraft_version(directory, identity, raise_errors=True)
            if not deleted:
                raise OSError('删除失败，请检查文件占用与权限。')
        except Exception as exc:
            self.signals.finished.emit(str(exc) or type(exc).__name__)
        else:
            self.signals.finished.emit('')


class InstancesController(QObject):
    changed = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.page = parent
        self.settings = get_settings_manager()
        self._directories = []
        self._versions = []
        self._status = ''
        self._pending = {}
        self._delete_dialog = None
        self._delete_worker = None
        self._export_dialog = None
        self._export_worker = None

    @Property('QVariantMap', notify=changed)
    def view(self):
        return dict(directories=self._directories, versions=self._versions,
                    directory=self.settings.get_setting('minecraft.directory.enable') or '',
                    selected=self.settings.get_setting('minecraft.version.enable') or '',
                    status=self._status, confirmation=self._pending)

    @Slot()
    def reload(self):
        directory = self.settings.get_setting('minecraft.directory.enable') or ''
        directories = self.settings.get_setting('minecraft.directory.installed', []) or []
        if directory and directory not in directories:
            directories = [directory] + directories
        self._directories = [dict(path=item, title=Path(item).name or item) for item in directories]
        identities = installed_instance_ids(directory)
        selected = self.settings.get_setting('minecraft.version.enable')
        if selected not in identities:
            selected = identities[0] if identities else None
            self.settings.set_setting('minecraft.version.enable', selected)
        self.settings.set_setting('minecraft.version.installed', identities)
        self.settings.save_settings()
        self._versions = []
        for identity in identities:
            try:
                metadata = json.loads(filesystem_path(Path(directory) / 'versions' / identity / (identity + '.json')).read_text(encoding='utf-8'))
                description = str(metadata.get('type', 'release')) + ' · ' + str(metadata.get('releaseTime', '未知日期'))[:10]
            except (OSError, ValueError, TypeError):
                description = '无法读取版本信息'
            self._versions.append(dict(version=identity, description=description))
        self.page.signals.versions.emit(selected or '')
        self.changed.emit()

    @Slot(str)
    def selectDirectory(self, path):
        if not any(item['path'] == path for item in self._directories):
            return
        self.settings.set_setting('minecraft.directory.enable', path)
        self.settings.save_settings()
        self.page.signals.directory.emit(path)
        self.reload()

    @Slot()
    def addDirectory(self):
        directory = QFileDialog.getExistingDirectory(self.page, '选择游戏目录 (.minecraft/)', '')
        if not directory:
            return
        directories = self.settings.get_setting('minecraft.directory.installed', []) or []
        if directory not in directories:
            self.settings.set_setting('minecraft.directory.installed', directories + [directory])
        self.settings.set_setting('minecraft.directory.enable', directory)
        self.settings.save_settings()
        self.page.signals.directory.emit(directory)
        self.reload()

    @Slot(str)
    def selectVersion(self, version):
        if not any(item['version'] == version for item in self._versions):
            return
        self.settings.set_setting('minecraft.version.enable', version)
        self.settings.save_settings()
        self.page.signals.versions.emit(version)
        self.changed.emit()

    @Slot(str, str)
    def action(self, identity, action):
        if action == 'settings':
            self.selectVersion(identity)
            self.page.parent.on_settings_clicked()
        elif action == 'folder':
            directory = self.settings.get_setting('minecraft.directory.enable') or ''
            if not open_folder(str(Path(directory) / 'versions' / identity)):
                self._status = '无法打开版本文件夹。'
                self.changed.emit()
        elif action == 'export':
            directory = self.settings.get_setting('minecraft.directory.enable') or ''
            if not directory or not any(item['version'] == identity for item in self._versions):
                self._status = '实例不在当前目录中，无法导出。'
                self.changed.emit()
                return
            if self._export_dialog is not None:
                self._export_dialog.raise_()
                self._export_dialog.activateWindow()
                return
            dialog = QmlDialog(
                self.page, title='导出整合包', message='选择导出方式',
                detail=identity, actions=['精简导出', '常规导出', '取消'], width=620, height=420,
                primary_action='精简导出', source='ModpackExportDialog.qml',
                data=dict(phase='choose', instance=identity))
            self._export_dialog = dialog
            dialog.controller.actionRequested.connect(
                lambda label: self._export_action(identity, label))
            dialog.finished.connect(self._finish_export_dialog, Qt.QueuedConnection)
            dialog.open()

        elif action in ('exportCompact', 'exportStandard'):
            # Kept for automation and keyboard-driven callers. The visible UI
            # uses the mode dialog above.
            self._choose_export(identity, 'compact' if action == 'exportCompact' else 'standard')

        elif action == 'exportFile':
            return
        elif action in ('deleteVersion', 'deleteDirectory'):
            if self._delete_dialog is not None:
                self._delete_dialog.raise_()
                self._delete_dialog.activateWindow()
                return
            is_directory = action == 'deleteDirectory'
            self._pending = dict(identity=identity, action=action,
                                 directory=self.settings.get_setting('minecraft.directory.enable') or '',
                                 title='删除整个游戏目录？' if action == 'deleteDirectory' else '删除游戏实例？',
                                 message=identity + '\n' + ('此操作会永久删除该游戏目录中的所有实例与文件，无法撤销。'
                                                           if is_directory else '此操作会永久删除该实例目录中的存档、模组与资源，无法撤销。'))
            self.changed.emit()
            dialog = QmlDialog(self.page, title=self._pending['title'],
                               message=identity, detail=self._pending['message'].split('\n', 1)[1],
                               actions=['取消', '删除'], width=510, height=205,
                               primary_action='删除')
            self._delete_dialog = dialog
            dialog.controller.actionRequested.connect(self._delete_action)
            dialog.finished.connect(self._finish_delete_dialog, Qt.QueuedConnection)
            dialog.open()
        elif action == 'download':
            self.page.parent.parent.download_page.on_download_clicked()
            self.page.parent.parent.switch_pages('下载')

    def _running(self):
        launcher = self.page.parent.parent.launcher
        if hasattr(launcher, 'sessions'):
            return [record['instance'] for record in launcher.sessions]
        return [launcher.running_instance] if launcher.running_instance else []

    @Slot(int)
    def _finish_delete_dialog(self, result):
        dialog, self._delete_dialog = self._delete_dialog, None
        if dialog is not None:
            dialog.shutdown()
            dialog.deleteLater()
        self._pending = {}
        self.changed.emit()

    @Slot(int)
    def _finish_export_dialog(self, result):
        dialog, self._export_dialog = self._export_dialog, None
        if dialog is not None:
            dialog.shutdown()
            dialog.deleteLater()

    def _export_action(self, identity, label):
        if label == '取消导出' and self._export_worker:
            self._export_worker.cancel.set()
            model = self._export_dialog.controller
            model.message = '正在取消…'
            model.actions_enabled = False
            model.changed.emit()
            return
        if label in ('取消', '关闭'):
            if self._export_dialog is not None:
                self._export_dialog.reject()
            return
        mode = {'精简导出': 'compact', '常规导出': 'standard'}.get(label)
        if not mode or self._export_dialog is None:
            return
        self._choose_export(identity, mode)

    def _choose_export(self, identity, mode):
        if self._export_worker:
            return
        directory = self.settings.get_setting('minecraft.directory.enable') or ''
        default = identity + ('-compact' if mode == 'compact' else '-standard') + '.buggpack'
        destination, _ = QFileDialog.getSaveFileName(
            self.page, '导出整合包', default,
            'Buggcraft 整合包 (*.buggpack);;ZIP 文件 (*.zip)')
        if not destination:
            return
        if self._export_dialog is None:
            self.action(identity, 'export')
        dialog = self._export_dialog
        model = dialog.controller
        model.message, model.detail = '正在导出整合包', '正在整理实例文件…'
        model.working, model.progress, model.dismissible = True, -1., False
        model.actions = ['取消导出']
        model.primary_action = ''
        model.data = dict(phase='exporting', instance=identity, mode=mode, path=destination)
        model.changed.emit()
        game_directory = self.settings.get_minecraft_isolation_directory(directory=directory, version=identity)
        worker = self._export_worker = _ExportWorker(directory, identity, destination, mode, game_directory)
        worker.signals.progress.connect(self._export_progress, Qt.QueuedConnection)
        worker.signals.finished.connect(self._export_finished, Qt.QueuedConnection)
        QThreadPool.globalInstance().start(worker)

    @Slot(str, object, object)
    def _export_progress(self, text, done, total):
        if self._export_dialog is None or self._export_worker is None:
            return
        model = self._export_dialog.controller
        model.progress = min(1., done / total) if total else -1.
        model.detail = text
        model.changed.emit()

    @Slot(object, str)
    def _export_finished(self, result, error):
        self._export_worker = None
        if self._export_dialog is None:
            return
        model = self._export_dialog.controller
        model.working, model.dismissible, model.actions_enabled = False, True, True
        model.actions, model.primary_action = ['关闭'], '关闭'
        model.data = dict(model.data, phase='error' if error else 'complete')
        model.message = ('导出已取消' if error == '导出已取消' else '导出失败') if error else '整合包已导出'
        model.detail = error if error else result['path']
        model.progress = 0. if error else 1.
        if result:
            label = '精简' if result['mode'] == 'compact' else '常规'
            self._status = f"{label}整合包已导出：{Path(result['path']).name}"
            model.data.update(size=Path(result['path']).stat().st_size, files=result['files'] + result['external_files'])
        else:
            self._status = model.message + ('：' + error if error != model.message else '')
        model.changed.emit()
        self.changed.emit()

    @Slot(str)
    def _delete_action(self, label):
        if self._delete_worker is not None:
            return
        if label in ('删除', '重试删除'):
            self.confirmDelete(True)
        elif self._delete_dialog:
            self._delete_dialog.reject()

    @Slot(bool)
    def confirmDelete(self, confirmed):
        pending = self._pending
        if not confirmed or not pending:
            if self._delete_dialog:
                self._delete_dialog.reject()
            self.changed.emit()
            return
        if self._delete_worker is not None:
            return
        identity, action = pending['identity'], pending['action']
        directory = self.settings.get_setting('minecraft.directory.enable') or ''
        try:
            if directory != pending['directory']:
                raise ValueError('游戏目录已切换，请重新确认删除目标。')
            if action == 'deleteDirectory':
                if not any(item['path'] == identity for item in self._directories):
                    raise ValueError('目录不在当前列表中。')
                if any(instance[0] and Path(instance[0]).resolve().is_relative_to(Path(identity).resolve())
                       for instance in self._running()):
                    raise ValueError('请先退出此目录中运行的游戏。')
            else:
                if not any(item['version'] == identity for item in self._versions):
                    raise ValueError('实例不在当前列表中。')
                if any(instance[0] and Path(instance[0]).resolve() == Path(directory).resolve()
                       and instance[1] == identity for instance in self._running()):
                    raise ValueError('请先退出此实例中运行的游戏。')
        except (OSError, ValueError, TypeError) as exc:
            self._delete_finished(str(exc))
            return
        if self._delete_dialog:
            model = self._delete_dialog.controller
            model.title = '正在删除…'
            model.detail = '正在检查依赖并删除文件，请稍候。'
            model.working, model.progress = True, -1.
            model.dismissible = model.actions_enabled = False
            model.actions = ['删除中…']
            model.changed.emit()
        self._delete_worker = _DeleteWorker(self, pending)
        self._delete_worker.signals.finished.connect(self._delete_finished, Qt.QueuedConnection)
        QThreadPool.globalInstance().start(self._delete_worker)

    @Slot(str)
    def _delete_finished(self, error):
        if self._delete_worker is not None:
            self._delete_worker.signals.deleteLater()
        self._delete_worker = None
        dialog = self._delete_dialog
        if dialog:
            model = dialog.controller
            model.working = False
            model.dismissible = model.actions_enabled = True
        if error:
            self._status = error
            if dialog:
                dialog.setMinimumHeight(170)
                dialog.resize(dialog.width(), 205)
                model.title = '删除失败'
                model.detail = error
                model.actions = ['关闭', '重试删除']
                model.primary_action = '重试删除'
                model.changed.emit()
            self.changed.emit()
            return
        pending = self._pending
        if pending['action'] == 'deleteDirectory':
            directories = [path for path in self.settings.get_setting('minecraft.directory.installed', []) or []
                           if path != pending['identity']]
            self.settings.set_setting('minecraft.directory.installed', directories)
            if self.settings.get_setting('minecraft.directory.enable') == pending['identity']:
                self.settings.set_setting('minecraft.directory.enable', directories[0] if directories else None)
                self.page.signals.directory.emit(directories[0] if directories else '')
        self.settings.save_settings()
        self._status = ''
        self.reload()
        if dialog:
            dialog.accept()


class VersionsPage(QmlPage):
    def __init__(self, parent):
        self.parent = parent
        self.resource_path = parent.resource_path
        self.signals = MinecraftSettingSignals()
        controller = InstancesController(parent)
        super().__init__(parent, parent.resource_path, 'Instances.qml', 'instancesPage', controller)
        controller.page = self
        controller.setParent(self)
        self.settings_manager = controller.settings
        controller.reload()

    def refresh_version_list(self, directory_path):
        self.controller.reload()

    def on_add_directory(self, event=None):
        self.controller.addDirectory()

    def on_page_activate(self):
        self.controller.reload()

    def on_page_deactivate(self):
        pass
