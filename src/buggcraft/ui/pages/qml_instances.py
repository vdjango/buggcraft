"""Instance operations with a fixed two-column QML layout."""
import json
import os
from pathlib import Path

from PySide6.QtCore import QObject, Property, Signal, Slot
from PySide6.QtWidgets import QFileDialog, QDialog

from config.settings import get_settings_manager
from core.minecraft.version import delete_minecraft_directory, delete_minecraft_version, open_folder
from ui.dialog.qml_dialog import QmlDialog
from ui.pages.qml_host import QmlPage
from utils.instances import installed_instance_ids


class MinecraftSettingSignals(QObject):
    versions = Signal(str)
    directory = Signal(str)


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
                               actions=['取消', '删除'], width=550, height=270)
            self._delete_dialog = dialog
            dialog.controller.actionRequested.connect(
                lambda label: dialog.accept() if label == '删除' else dialog.reject())
            dialog.finished.connect(self._finish_delete_dialog)
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
        self.confirmDelete(result == QDialog.Accepted)

    @Slot(bool)
    def confirmDelete(self, confirmed):
        pending, self._pending = self._pending, {}
        if not confirmed or not pending:
            self.changed.emit()
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
                if not delete_minecraft_directory(identity):
                    raise OSError('目录删除失败，请检查文件占用与权限。')
                directories = [item['path'] for item in self._directories if item['path'] != identity]
                self.settings.set_setting('minecraft.directory.installed', directories)
                if directory == identity:
                    self.settings.set_setting('minecraft.directory.enable', directories[0] if directories else None)
                    self.page.signals.directory.emit(directories[0] if directories else '')
            else:
                if not any(item['version'] == identity for item in self._versions):
                    raise ValueError('实例不在当前列表中。')
                if any(instance[0] and Path(instance[0]).resolve() == Path(directory).resolve()
                       and instance[1] == identity for instance in self._running()):
                    raise ValueError('请先退出此实例中运行的游戏。')
                for version in installed_instance_ids(directory):
                    metadata = json.loads((Path(directory) / 'versions' / version / (version + '.json')).read_text(encoding='utf-8'))
                    if metadata.get('inheritsFrom') == identity or metadata.get('buggcraftRoom', {}).get('parent') == identity:
                        raise ValueError(f'{version} 仍依赖此实例，请先处理依赖。')
                if not delete_minecraft_version(directory, identity):
                    raise OSError('实例删除失败，请检查文件占用与权限。')
            self.settings.save_settings()
            self._status = ''
            self.reload()
        except (OSError, ValueError, TypeError) as exc:
            self._status = str(exc)
            self.changed.emit()


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
