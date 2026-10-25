"""Instance operations with a fixed two-column QML layout."""
import json
import os
from pathlib import Path

from PySide6.QtCore import QObject, Property, QRunnable, QThreadPool, Qt, Signal, Slot
from PySide6.QtWidgets import QFileDialog

from config.settings import get_settings_manager
from core.minecraft.version import delete_minecraft_directory, delete_minecraft_version, open_folder
from ui.dialog.qml_dialog import QmlDialog
from ui.pages.qml_host import QmlPage
from utils.instances import installed_instance_ids


class MinecraftSettingSignals(QObject):
    versions = Signal(str)
    directory = Signal(str)


class _DeleteSignals(QObject):
    finished = Signal(str)


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
                    metadata = json.loads((Path(directory) / 'versions' / version / (version + '.json')).read_text(encoding='utf-8'))
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
                metadata = json.loads((Path(directory) / 'versions' / identity / (identity + '.json')).read_text(encoding='utf-8'))
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
