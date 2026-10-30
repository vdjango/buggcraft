"""Shared QML record pages for Java runtimes and application information."""
import os
import threading
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from PySide6.QtCore import QObject, Property, QRunnable, QThreadPool, Signal, Slot, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog

from config.javafinder import JavaPathFinder
from config.settings import get_settings_manager
from ui.pages.qml_host import QmlPage
from core.minecraft.version import open_folder
from core.java_downloads import SOURCES, catalogue, install as install_java, register as register_java
from core.java_runtime import java_policy
from core.update_client import current_version
from utils.path_helper import get_launcher_directory


class _JavaSignals(QObject):
    finished = Signal(object, str)
    progress = Signal(str, int, int)


class _JavaWork(QRunnable):
    def __init__(self, action, complete):
        super().__init__()
        self.action = action
        self.signals = _JavaSignals()
        self.signals.finished.connect(complete)

    @Slot()
    def run(self):
        try:
            value = self.action(lambda message, done, total: self.signals.progress.emit(message, done, total))
            self.signals.finished.emit(value, '')
        except Exception as exc:
            self.signals.finished.emit(None, str(exc))


class RecordController(QObject):
    changed = Signal()

    def __init__(self, parent, resource_path, kind):
        super().__init__(parent)
        self.resource_path = resource_path
        self.kind = kind
        self.manager = get_settings_manager()
        self._records = []
        self._status = ''
        self.busy = False
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)
        saved_source = self.manager.get_setting('java.download_source', SOURCES[0])
        self.java_source = saved_source if saved_source in SOURCES else SOURCES[0]
        self.java_major = 17
        self.java_catalog_open = False
        self.java_packages = []
        self._package_records = []
        self.java_installing = False
        self.cancel = threading.Event()
        self.reload()

    @Property('QVariantMap', notify=changed)
    def view(self):
        return dict(title='Java 管理' if self.kind == 'java' else '关于',
                    launcherVersion=current_version(self.resource_path),
                    records=self._records, status=self._status, busy=self.busy,
                    kind=self.kind,
                    resources=QUrl.fromLocalFile(str(Path(self.resource_path).resolve()) + '/').toString(),
                    sections=[dict(title=title, records=[record for record in self._records if record.get('section') == title])
                              for title in ('关于', '鸣谢', '依赖', '法律声明')],
                    javaCatalogOpen=self.java_catalog_open, javaPackages=self.java_packages,
                    javaSource=self.java_source, javaMajor=self.java_major,
                    javaSources=list(SOURCES), javaMajors=[8, 11, 16, 17, 21, 25],
                    actions=['刷新', '添加'] if self.kind == 'java' else [])

    @Slot()
    def reload(self):
        if self.kind == 'java':
            self.busy = False
            self._records = [dict(id=item[0], title='OpenJDK' if 'openjdk' in str(item[1]).lower() else str(item[1]).split(' ')[0],
                                 version='.'.join(map(str, item[2])) if len(item) >= 3 else str(item[1]),
                                 vendor='OpenJDK' if 'openjdk' in str(item[1]).lower() else 'Java',
                                 description=item[0], actions=['打开目录', '移除'])
                             for item in self.manager.get_setting('java.installations', []) or []
                             if isinstance(item, (list, tuple)) and len(item) >= 2]
        else:
            root = Path(self.resource_path).parent
            dependencies = []
            for package in ('PySide6', 'minecraft-launcher-lib', 'requests', 'psutil'):
                try:
                    dependencies.append(package + ' ' + version(package))
                except PackageNotFoundError:
                    dependencies.append(package)
            self._records = [
                dict(id='', title='Buggcraft', description='Minecraft 启动器 · 邀请码联机', actions=[]),
                dict(id='', title='当前游戏实例', description=self.manager.get_setting('minecraft.version.enable') or '尚未选择', actions=[]),
                dict(id='https://github.com/vdjango/buggcraft', title='开源项目与贡献者', description='感谢参与开发、翻译、测试和问题反馈的每一位玩家。', actions=['查看']),
                dict(id='https://github.com/vdjango/buggcraft/blob/main/requirements.txt', title='运行依赖', description='\n'.join(dependencies), actions=['查看']),
                dict(id='https://github.com/vdjango/buggcraft/blob/main/LICENSE', title='开源许可', description='启动器遵循 AGPL-3.0-or-later 许可，相关依赖保留各自许可。', actions=['查看']),
                dict(id='', title='游戏与资源版权', description='游戏、模组和整合包的版权归原作者所有，请遵守各自的使用与分发条款。', actions=[]),
                dict(id='https://github.com/vdjango/buggcraft/blob/main/COMMUNITY_LICENSE.md', title='社区许可', description='查看社区使用和贡献相关说明。', actions=['查看']),
            ]
            for record, section, icon in zip(self._records,
                    ('关于', '关于', '鸣谢', '依赖', '法律声明', '法律声明', '法律声明'),
                    ('About1.png', 'About2.png', 'About3.png', '', '', '', '')):
                record.update(section=section, icon=icon)
        self.changed.emit()

    @Slot(str, str)
    def action(self, identity, action):
        page = self.parent()
        if action == '查看':
            QDesktopServices.openUrl(QUrl(identity) if identity.startswith('https://') else QUrl.fromLocalFile(identity))
        elif action == '打开目录':
            open_folder(os.path.dirname(identity))
        elif action == '移除':
            entries = self.manager.get_setting('java.installations', []) or []
            entries = [item for item in entries if os.path.normcase(item[0]) != os.path.normcase(identity)]
            self.manager.set_setting('java.installations', entries)
            if self.manager.get_version_setting('java.path') == identity:
                self.manager.set_version_setting('java.path', JavaPathFinder().recommend_best_java(entries))
                self.manager.set_version_setting('java.name', '使用推荐的 Java 版本|系统将自动选择最适合的 Java 版本')
            self.manager.save_settings()
            self.reload()
        elif action == '刷新':
            self.busy = True
            self._status = '正在搜索 Java…'
            self.changed.emit()
            page.parent.parent.load_java_path(notify_missing=False)
        elif action == '下载':
            self.java_catalog_open = not self.java_catalog_open
            self.java_packages = []
            self._status = ''
            if self.java_catalog_open:
                directory = self.manager.get_setting('minecraft.directory.enable') or ''
                game = self.manager.get_setting('minecraft.version.enable') or ''
                if directory and game:
                    try:
                        self.java_major = java_policy(directory, game).recommended
                    except Exception:
                        self.java_major = 17
            self.changed.emit()
            if self.java_catalog_open:
                self.load_java_catalog()
        elif action == '添加':
            path, _ = QFileDialog.getOpenFileName(page, '选择 Java 可执行文件', '', 'Java (java.exe javaw.exe java);;所有文件 (*)')
            if path:
                page.add_java(path)

    @Slot(str, str)
    def close_java_catalog(self, identity='', action=''):
        self.java_catalog_open = False
        self.changed.emit()

    @Slot(int)
    def set_java_major(self, major):
        if major in (8, 11, 16, 17, 21, 25):
            self.java_major = major
            self.java_packages = []
            self._status = ''
            self.changed.emit()

    @Slot(str)
    def set_java_source(self, source):
        if source in SOURCES:
            self.java_source = source
            self.manager.set_setting('java.download_source', source)
            self.manager.save_settings()
            self.java_packages = []
            self._status = ''
            self.changed.emit()

    @Slot()
    def load_java_catalog(self):
        if self.busy:
            return
        self.busy = True
        self._status = f'正在获取 Java {self.java_major} 下载列表…'
        self.java_packages = []
        self.changed.emit()
        major, source = self.java_major, self.java_source
        task = _JavaWork(lambda progress: catalogue(major, source),
                         self._java_catalog_finished)
        task.signals.progress.connect(self._java_progress)
        self.pool.start(task)

    @Slot(object, str)
    def _java_catalog_finished(self, packages, error):
        self.busy = False
        self._package_records = packages or []
        self.java_packages = [package.record() for package in packages] if packages else []
        self._status = error or (f'找到 {len(self.java_packages)} 个可用版本，下载后自动校验并安装。'
                                if packages else '没有找到可用版本。')
        self.changed.emit()

    @Slot(str, int, int)
    def _java_progress(self, message, done, total):
        if not self.java_installing:
            return
        self._status = f'{message}  {min(100, max(0, done * 100 // total))}%' if total > 0 else message
        self.changed.emit()

    @Slot(str)
    def download_java(self, identity):
        if self.busy:
            return
        package = next((item for item in getattr(self, '_package_records', [])
                        if item.checksum == identity), None)
        if package is None:
            self._status = 'Java 下载条目已过期，请刷新列表。'
            self.changed.emit()
            return
        self.busy = True
        self.java_installing = True
        self.cancel.clear()
        self._install_package = package
        self._status = f'正在准备 {package.vendor} Java {package.version}…'
        self.changed.emit()

        from utils.storage_paths import active_storage_root
        task = _JavaWork(lambda progress: install_java(package,
            active_storage_root() / 'java', cancel=self.cancel, report=progress), self._java_install_finished)
        task.signals.progress.connect(self._java_progress)
        self.pool.start(task)

    @Slot(object, str)
    def _java_install_finished(self, entry, error):
        self.java_installing = False
        self.busy = False
        if error:
            self._status = 'Java 安装失败：' + error
        else:
            register_java(self.manager, entry)
            self.reload()
            self._status = f'Java {self._install_package.version} 已安装、校验并添加到 Java 管理。'
        self.changed.emit()

    def shutdown(self):
        self.cancel.set()
        self.pool.clear()
        return self.pool.waitForDone(0)


class JavaManagementPage(QmlPage):
    def __init__(self, parent):
        self.parent = parent
        controller = RecordController(parent, parent.resource_path, 'java')
        super().__init__(parent, parent.resource_path, 'RecordList.qml', 'recordPage', controller)
        controller.setParent(self)
        self.settings_manager = controller.manager

    def add_java(self, path):
        path = os.path.realpath(path)
        if os.path.basename(path).lower() == 'javaw.exe':
            path = os.path.join(os.path.dirname(path), 'java.exe')
        raw, found = JavaPathFinder()._get_java_version(path)
        if not os.path.isfile(path) or not raw or not found or found == (0, 0, 0):
            self.set_status('无法添加 Java：所选文件无法执行或无法读取 Java 版本。')
            return False
        register_java(self.settings_manager, (path, raw, list(found)))
        self.refresh_list()
        return True

    def refresh_list(self):
        if self.controller.busy:
            return
        self.controller._status = ''
        self.controller.reload()

    def set_status(self, value):
        self.controller._status = value
        self.controller.busy = False
        self.controller.changed.emit()

    def on_page_activate(self):
        self.refresh_list()

    def on_page_deactivate(self):
        pass


class AboutPage(QmlPage):
    def __init__(self, parent):
        controller = RecordController(parent, parent.resource_path, 'about')
        super().__init__(parent, parent.resource_path, 'RecordList.qml', 'recordPage', controller)

    def on_page_activate(self):
        self.controller.reload()

    def on_page_deactivate(self):
        pass
