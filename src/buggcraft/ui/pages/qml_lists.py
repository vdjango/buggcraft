"""Shared QML record pages for Java runtimes and application information."""
import os
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from PySide6.QtCore import QObject, Property, Signal, Slot, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog

from config.javafinder import JavaPathFinder
from config.settings import get_settings_manager
from ui.pages.qml_host import QmlPage
from core.minecraft.version import open_folder


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
        self.reload()

    @Property('QVariantMap', notify=changed)
    def view(self):
        return dict(title='Java 管理' if self.kind == 'java' else '关于',
                    records=self._records, status=self._status, busy=self.busy,
                    kind=self.kind,
                    resources=QUrl.fromLocalFile(str(Path(self.resource_path).resolve()) + '/').toString(),
                    sections=[dict(title=title, records=[record for record in self._records if record.get('section') == title])
                              for title in ('关于', '鸣谢', '依赖', '法律声明')],
                    actions=['刷新', '下载', '添加'] if self.kind == 'java' else [])

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
                dict(id=str(root / 'README.md'), title='开源项目与贡献者', description='项目说明、贡献方式与相关资料。', actions=['查看']),
                dict(id=str(root / 'requirements.txt'), title='运行依赖', description='\n'.join(dependencies), actions=['查看']),
                dict(id=str(root / 'LICENSE'), title='版权', description='项目许可与版权声明见随附 LICENSE 文件。', actions=['查看']),
                dict(id='', title='用户协议', description='尚未提供独立的付费服务条款。', actions=[]),
                dict(id=str(root / 'COMMUNITY_LICENSE.md'), title='开源', description='查看项目许可和社区许可文件。', actions=['查看']),
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
            QDesktopServices.openUrl(QUrl.fromLocalFile(identity))
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
            page.parent.parent.on_java_download_signal()
        elif action == '添加':
            path, _ = QFileDialog.getOpenFileName(page, '选择 Java 可执行文件', '', 'Java (java.exe javaw.exe java);;所有文件 (*)')
            if path:
                page.add_java(path)


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
        entries = self.settings_manager.get_setting('java.installations', []) or []
        entries = [item for item in entries if os.path.normcase(item[0]) != os.path.normcase(path)]
        self.settings_manager.set_setting('java.installations', entries + [[path, raw, list(found)]])
        self.settings_manager.save_settings()
        self.refresh_list()
        return True

    def refresh_list(self):
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
