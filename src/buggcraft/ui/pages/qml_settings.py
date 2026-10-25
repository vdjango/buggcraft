"""QML settings shared by global and per-instance pages."""
import os

import psutil
from PySide6.QtCore import QObject, Property, Signal, Slot, QTimer
from PySide6.QtWidgets import QFileDialog

from config.javafinder import JavaPathFinder
from config.settings import get_settings_manager, launcher_opacity
from config.settings_scope import GlobalSettingsScope
from core.visibility import VisibilitySettings
from ui.pages.qml_host import QmlPage


class SettingsController(QObject):
    changed = Signal()
    memoryChanged = Signal()

    def __init__(self, parent, scope):
        super().__init__(parent)
        self.scope = scope
        self.manager = get_settings_manager()
        self.settings = GlobalSettingsScope(self.manager) if scope == 'global' else self.manager
        self._fields = []
        self._memory = {}
        self.reload()

    @Property('QVariantList', notify=changed)
    def fields(self):
        return self._fields

    @Property('QVariantList', notify=changed)
    def groups(self):
        """Keep the original settings-page sections instead of one card per field."""
        fields = {field['key']: field for field in self._fields}
        result = []
        for key, field in fields.items():
            if key == 'memory.allocation':
                continue
            group = dict(field, summary=str(field['value']), expanded=True,
                         collapsible=True, inline=False, options=[dict(value=value, title=str(value), description='')
                                                                for value in field['options']])
            if key == 'settings.general.update':
                group.update(kind='radio-horizontal', summary='打开发行页', collapsible=False,
                             options=[dict(value='stable', title='稳定版', description=''),
                                      dict(value='development', title='开发版', description='')])
            elif key == 'cache':
                cache = self.manager.get_setting('settings.general.download.cache', '.buggcraft/')
                group.update(kind='radio', value=cache if cache in ('~/.buggcraft/', '.buggcraft/') else 'custom',
                             summary='当前配置与缓存：' + str(self.manager.config_path),
                             options=[dict(value='~/.buggcraft/', title='默认', description='%APPDATA%/.buggcraft/ 或 ~/.buggcraft/'),
                                      dict(value='.buggcraft/', title='当前路径', description='位于启动器路径下 (.buggcraft/)'),
                                      dict(value='custom', title='自定义', description=str(self.manager.config_path))])
            elif key == 'language':
                group.update(kind='choice', options=[dict(value='简体中文', title='简体中文', description='')])
            elif key == 'minecraft.isolation':
                group.update(kind='radio', description='', summary='各版本独立' if field['value'] else '默认 (.minecraft/)',
                             options=[dict(value=False, title='默认 (.minecraft/)', description='资源存放在 .minecraft/'),
                                      dict(value=True, title='各版本独立', description='存放在 .minecraft/versions/<版本名>/，共享 assets、libraries')])
            elif key == 'java.path':
                options = []
                for option in field['options']:
                    title, _, path = option.partition(' · ')
                    options.append(dict(value=option, title=title,
                                        description=path or ('系统将自动选择最适合的 Java 版本' if not options else '点击选择 Java 可执行文件')))
                group.update(kind='radio', description='', summary=str(field['value']),
                             options=options)
            elif key == 'minecraft.auto_allocate_memory':
                group.update(kind='memory', title='游戏内存分配', collapsible=False,
                             memory=fields['memory.allocation'], summary='')
            elif key in ('launcher.visibility', 'launcher.window_size'):
                group.update(inline=True, collapsible=False, summary='')
                if key == 'launcher.window_size':
                    group['title'] = '游戏窗口分辨率'
            elif key in ('launcher.process_priority', 'launcher.debug'):
                group['kind'] = 'radio'
                if key == 'launcher.process_priority':
                    descriptions = ['为游戏分配更多系统资源，可能影响其他程序运行。',
                                    '系统资源合理分配，推荐大多数情况使用。', '优先保证其他程序运行，可能影响游戏性能。']
                    for option, description in zip(group['options'], descriptions):
                        option['description'] = description
            elif key == 'instance.enable':
                group.update(kind='instance', summary=self.manager.get_setting('minecraft.directory.enable') or '',
                             collapsible=False)
            elif key in ('launcher.allow_multiple', 'translation.enabled'):
                group.update(kind='standalone-toggle', collapsible=False)
            elif key == 'launcher.opacity':
                group.update(kind='opacity', collapsible=False, summary='')
            result.append(group)
        return result

    @Property('QVariantMap', notify=memoryChanged)
    def memoryInfo(self):
        return self._memory

    @Slot()
    def refreshMemory(self):
        info = psutil.virtual_memory()
        self._memory = dict(total=info.total // 1048576, used=info.used // 1048576,
                            available=info.available // 1048576)
        self.memoryChanged.emit()

    @Property(str, constant=True)
    def title(self):
        return {'general': '通用设置', 'global': '全局游戏设置', 'instance': '实例游戏设置'}[self.scope]

    def _field(self, key, title, value, options=None, description='', kind='choice', enabled=True):
        return dict(key=key, title=title, value=value, options=options or [],
                    description=description, kind=kind, enabled=enabled)

    @Slot()
    def reload(self):
        s = self.settings
        if self.scope == 'general':
            self._fields = [
                self._field('settings.general.update', '启动器更新', s.get_setting('settings.general.update', 'stable'),
                            ['stable', 'development'], '启动时自动检查此通道；发布后的版本可从官网下载安装。'),
                self._field('launcher.opacity', '启动器透明度', launcher_opacity(s),
                            options=[35, 100], kind='opacity',
                            description='默认 85%，最低 35%，100% 为完全不透明。'),
                self._field('cache', '文件缓存路径', str(self.manager.config_path),
                            description='缓存目录迁移尚未接入，当前配置保持不变。', kind='text', enabled=False),
                self._field('language', '启动器语言', '简体中文', kind='text', enabled=False,
                            description='目前只支持简体中文。'),
                self._field('settings.general.mirrors', '游戏与加载器下载源',
                            s.get_setting('settings.general.mirrors', '自动（官方优先，失败切换镜像）'),
                            ['自动（官方优先，失败切换镜像）', '官方', 'BMCLAPI'],
                            'Minecraft 本体、assets、libraries 和加载器。BMCLAPI 优先国内镜像，失败回退官方。'),
                self._field('settings.general.content_mirror', '模组与整合包下载源',
                            s.get_setting('settings.general.content_mirror', 'MCIM'), ['MCIM', '官方'],
                            '适用于 Modrinth / CurseForge 查询，以及模组、资源包、光影、整合包文件。默认 MCIM，超时、持续低速或失败时自动切换原站；不影响游戏本体下载源。'),
                self._field('launcher.allow_multiple', '允许多开游戏',
                            bool(s.get_setting('launcher.allow_multiple', False)), kind='toggle',
                            description='首页可按版本和 PID 选择停止目标。'),
                self._field('translation.enabled', '自动翻译资源介绍',
                            bool(s.get_setting('translation.enabled', False)), kind='toggle',
                            description='自动翻译模组、资源包、光影和整合包的列表简介与详情。首次翻译在后台进行，不影响浏览和下载。'),
                self._field('translation.source', '资源翻译源', s.get_setting('translation.source', 'Buggcraft'),
                            ['Buggcraft'], description='默认使用 Buggcraft 共享译文服务，AI 译文仅供参考。',
                            enabled=bool(s.get_setting('translation.enabled', False))),
            ]
        else:
            get = s.get_version_setting
            installed = s.get_setting('java.installations', []) or []
            java_options = ['使用推荐的 Java 版本'] + [f'{item[1]} · {item[0]}' for item in installed
                                                   if isinstance(item, (list, tuple)) and len(item) >= 2]
            java_options.append('选择自定义 Java…')
            current_java = get('java.path') or ''
            if current_java and not any(option.endswith(' · ' + current_java) for option in java_options[1:-1]):
                java_options.insert(-1, '自定义 Java · ' + current_java)
            java_value = next((option for option in java_options[1:-1]
                               if option.endswith(' · ' + current_java)), java_options[0])
            if str(get('java.name') or '').startswith('使用推荐的 Java 版本'):
                java_value = java_options[0]
            memory_max = max(512, int(psutil.virtual_memory().total / 1048576) - 1024)
            fields = []
            if self.scope == 'instance':
                version = s.get_setting('minecraft.version.enable') or '尚未选择'
                fields.append(self._field('instance.enable', f'启用 {version} 的独立设置',
                                          bool(s.get_version_setting_enable()), kind='toggle',
                                          description='关闭时使用全局游戏设置。'))
            editable = self.scope != 'instance' or bool(s.get_version_setting_enable())
            fields.extend([
                self._field('minecraft.isolation', '版本隔离', bool(get('minecraft.isolation', True)),
                            kind='toggle', description='存档、模组等内容存放在当前版本目录。', enabled=editable),
                self._field('java.path', '游戏 Java', java_value, java_options,
                            '自动寻找合适的 Java，也可选择已发现的版本。', enabled=editable),
                self._field('minecraft.auto_allocate_memory', '自动分配内存',
                            bool(get('minecraft.auto_allocate_memory', True)), kind='toggle', enabled=editable),
                self._field('memory.allocation', '游戏内存（MB）', int(get('memory.allocation', 2048)),
                            kind='slider', description=f'512–{memory_max} MB',
                            options=[512, memory_max], enabled=editable and not get('minecraft.auto_allocate_memory', True)),
                self._field('launcher.visibility', '启动器可见性',
                            get('launcher.visibility', VisibilitySettings.KEEP_VISIBLE),
                            [VisibilitySettings.KEEP_VISIBLE, VisibilitySettings.MINIMIZE,
                             VisibilitySettings.HIDE, VisibilitySettings.CLOSE], enabled=editable),
                self._field('launcher.window_size', '游戏窗口尺寸', get('launcher.window_size', '默认'),
                            ['默认', '与启动器一致', '最大化'], enabled=editable),
                self._field('launcher.process_priority', '进程优先级',
                            get('launcher.process_priority', '平衡模式'),
                            ['游戏性能优先', '平衡模式', '系统流畅优先'], enabled=editable),
                self._field('launcher.debug', '游戏调试模式',
                            get('launcher.debug', '否（推荐）'), ['是', '否（推荐）'], enabled=editable),
            ])
            self._fields = fields
        self.refreshMemory()
        self.changed.emit()

    @Slot(str, 'QVariant')
    def setValue(self, key, value):
        field = next((item for item in self._fields if item['key'] == key), None)
        if field is None or not field['enabled']:
            return
        if key == 'java.path':
            if value == '选择自定义 Java…':
                self.chooseJava()
                return
            if value == '使用推荐的 Java 版本':
                value = JavaPathFinder().recommend_best_java(self.settings.get_setting('java.installations', []) or [])
                name = '使用推荐的 Java 版本|系统将自动选择最适合的 Java 版本'
            else:
                value = str(value).split(' · ', 1)[-1]
                name = value
            self.settings.set_version_setting('java.path', value)
            self.settings.set_version_setting('java.name', name)
        elif key == 'instance.enable':
            self.settings.set_version_setting_enable(bool(value))
        elif key == 'memory.allocation':
            self.settings.set_version_setting(key, int(value))
        elif key == 'launcher.opacity' and self.scope == 'general':
            try:
                value = max(35, min(100, int(value)))
            except (TypeError, ValueError, OverflowError):
                return
            self.settings.set_setting(key, value)
            window = self.parent().window()
            if hasattr(window, 'apply_window_opacity'):
                window.apply_window_opacity()
        elif self.scope == 'general':
            self.settings.set_setting(key, value)
        else:
            self.settings.set_version_setting(key, value)
            if key == 'minecraft.auto_allocate_memory' and value:
                from core.memory import AdvancedMemoryRecommender
                memory, _ = AdvancedMemoryRecommender(self.settings).calculate()
                self.settings.set_version_setting('memory.allocation', memory)
        self.settings.save_settings()
        self.reload()

    @Slot()
    def openReleases(self):
        import platform
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        system = platform.system()
        target = 'mac' if system == 'Darwin' else 'linux' if system == 'Linux' else 'windows'
        query = '?platform=' + target
        if target == 'mac':
            query += '&arch=' + ('arm64' if platform.machine().lower() in ('arm64', 'aarch64') else 'x86_64')
        QDesktopServices.openUrl(QUrl('https://bugg.icu/download/' + query))

    @Slot()
    def chooseJava(self):
        path, _ = QFileDialog.getOpenFileName(self.parent(), '选择 Java 可执行文件', '',
                                               'Java (java.exe javaw.exe java);;所有文件 (*)')
        if not path:
            self.reload()
            return
        path = os.path.realpath(path)
        if os.path.basename(path).lower() == 'javaw.exe':
            path = os.path.join(os.path.dirname(path), 'java.exe')
        raw, version = JavaPathFinder()._get_java_version(path)
        if not os.path.isfile(path) or not raw or not version or version == (0, 0, 0):
            from ui.dialog.qml_dialog import QmlDialog
            warning = QmlDialog(self.parent(), title='无法使用 Java',
                                message='所选文件无法读取 Java 版本。', actions=['确定'], height=230)
            warning.controller.actionRequested.connect(lambda _: warning.accept())
            warning.exec()
            warning.shutdown()
            warning.deleteLater()
            self.reload()
            return
        entries = self.settings.get_setting('java.installations', []) or []
        entries = [entry for entry in entries if os.path.normcase(entry[0]) != os.path.normcase(path)]
        self.settings.set_setting('java.installations', entries + [[path, raw, list(version)]])
        self.settings.set_version_setting('java.path', path)
        self.settings.set_version_setting('java.name', '自定义 Java 路径|None')
        self.settings.save_settings()
        self.reload()


class QmlSettingsPage(QmlPage):
    def __init__(self, parent, scope):
        controller = SettingsController(parent, scope)
        super().__init__(parent, parent.resource_path, 'SettingsForm.qml', 'settingsPage', controller)
        self.settings_manager = controller.settings
        self.memory_timer = QTimer(self)
        self.memory_timer.setInterval(10000)
        self.memory_timer.timeout.connect(controller.refreshMemory)

    def showEvent(self, event):
        super().showEvent(event)
        if self.controller.scope != 'general':
            self.memory_timer.start()

    def hideEvent(self, event):
        self.memory_timer.stop()
        super().hideEvent(event)

    def on_page_activate(self):
        self.controller.reload()

    def on_page_deactivate(self):
        pass
