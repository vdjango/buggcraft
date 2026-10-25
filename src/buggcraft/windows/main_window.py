# 主窗口

import os
import logging

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QStackedWidget, QVBoxLayout
)
from PySide6.QtCore import Qt, QSize, QPoint, QTimer, QRect, QEvent, QObject
from PySide6.QtGui import QPixmap, QPainter, QMouseEvent, QPen, QColor, QIcon

from utils.helpers import scale_component
from config.javafinder import JavaPathFinder
from config.settings import get_settings_manager, launcher_opacity
from core.visibility import LauncherVisibilityManager
from core.auth.microsoft import MicrosoftAuthenticator
from core.launcher import MinecraftLibLauncher
from ui.widgets.titlebar import TitleBar
from ui.pages import StartGamePage, SettingsPage, VersionsPages, DownloadPages
from ui.dialog.NotFuilMinecraftVersionDialog import VersionNotFuilDialog, QDialog
from ui.dialog.NotFuilJavaDialog import JavaRuntimeNotFuilDialog
from ui.dialog.qml_dialog import DebugOutputDialog, QmlDialog

import logging
logger = logging.getLogger(__name__)


def get_app_icon(RESOURCE_DIR) -> QIcon:
    """获取应用程序图标"""

    # 尝试从系统图标主题加载
    icon = QIcon.fromTheme("app")
    if icon.isNull():
        # 如果主题中没有，则从绝对路径加载
        icon = QIcon()
        icon_path = os.path.abspath(os.path.join(RESOURCE_DIR, 'icons', 'app.ico'))
        if os.path.exists(icon_path):
            icon = QIcon(icon_path)

    return icon


class _ModpackDropFilter(QObject):
    """Observe launcher drops without overriding QMainWindow's own event filter."""

    def eventFilter(self, watched, event):
        window = self.parent()
        if event.type() in (QEvent.DragEnter, QEvent.DragMove, QEvent.Drop) and isinstance(watched, QWidget) \
                and (watched is window or window.isAncestorOf(watched)):
            mime = event.mimeData()
            urls = mime.urls() if mime.hasUrls() else []
            if len(urls) == 1 and urls[0].isLocalFile():
                from pathlib import Path
                path = Path(urls[0].toLocalFile())
                if path.suffix.lower() in ('.zip', '.mrpack') and path.is_file():
                    event.setDropAction(Qt.CopyAction)
                    event.accept()
                    if event.type() == QEvent.Drop:
                        QTimer.singleShot(0, window, lambda archive=str(path): window._open_dropped_pack(archive))
                    return True
        return False


class MinecraftLauncher(QMainWindow):
    """主启动器界面"""

    def __init__(self, base_path, cache_path, config_path, resource_path):
        super().__init__()
        self.base_path = base_path
        self.cache_path = cache_path
        self.config_path = config_path
        self.resource_path = resource_path
        self._closing = False
        self._close_after_game = False
        self._debug_output = []
        self._debug_dialog = None
        self._launch_error_dialog = None
        self._launch_error_reported = False
        self._java_install_dialog = None
        self.setWindowIcon(get_app_icon(self.resource_path))

        # 窗口拖动
        self.dragging = False
        self.drag_position = QPoint()

        self.scale_ratio = scale_component(QSize(1280, 832), QSize(1280-1280/3, 832-832/3))
        self.settings_manager = get_settings_manager()  # 获取配置管理器
        self.visibility_manager = LauncherVisibilityManager(self)  # 初始化可见性管理器

        # 配置文件校验
        java_path = self.settings_manager.get_version_setting('java.path', None)
        if not (java_path and os.path.isfile(java_path)):
            self.settings_manager.set_version_setting('java.path', None)
            self.settings_manager.save_settings()
        
        installations = self.settings_manager.get_setting('java.installations', []) or []
        valid_installations = [entry for entry in installations
                               if isinstance(entry, (list, tuple)) and len(entry) == 3
                               and isinstance(entry[0], str)]
        if installations != valid_installations:
            self.settings_manager.set_setting('java.installations', valid_installations)
        
        # 同步 TitleBar 菜单顺序，同时主页面添加堆叠页面顺序也需要同步
        self.tab_names = [
            '开始', "下载", '设置', '实例'
        ]
        self.current_tab = 0
        
        # 设置背景图片
        self.menu_width = 178 + 27  # 左侧菜单宽度
        self.menu_collapsed = False  # 折叠状态
        
        # 加载背景图片
        self.original_bg_image = QPixmap(
            os.path.abspath(os.path.join(self.resource_path, 'images', 'minecraft_bg.png'))
        )
        self.bg_image = self.original_bg_image.scaled(
            self.original_bg_image.width(),
            self.original_bg_image.height()-55,
            Qt.IgnoreAspectRatio,
            Qt.SmoothTransformation
        )
        
        # 预缓存
        self.cache_expanded = QPixmap()
        # 启用双缓冲
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground, False)
        self.setWindowFlag(Qt.FramelessWindowHint)  # 移除默认标题栏
        self.initialize_caches()
        self.set_window_size()  # 根据背景图片尺寸设置窗口大小
        
        self.init_ui()
        self.setAcceptDrops(True)
        # Receive drops above embedded QML controls as well as the window frame.
        self._modpack_drop_filter = _ModpackDropFilter(self)
        for widget in [self, *self.findChildren(QWidget)]:
            widget.setAcceptDrops(True)
            widget.installEventFilter(self._modpack_drop_filter)
        self.apply_window_opacity()

        if not self.settings_manager.get_setting('onboarding.completed', False):
            QTimer.singleShot(1400, self.show_first_run_onboarding)
        
        self.java_runtime_full = JavaRuntimeNotFuilDialog(self)
        self.gamed_version_full = VersionNotFuilDialog(self)
        self.java_runtime_full.download_signal.connect(self.on_java_download_signal)
        self.gamed_version_full.download_signal.connect(self.on_gamed_download_signal)
        self.gamed_version_full.import_signal.connect(self.on_gamed_import_signal)

        QTimer.singleShot(500, self.minecraft_not_java_runtime)

    def apply_window_opacity(self):
        self.setWindowOpacity(launcher_opacity(self.settings_manager) / 100)

    def show_first_run_onboarding(self):
        if self._closing or self.settings_manager.get_setting('onboarding.completed', False):
            return
        from ui.dialog.OnboardingDialog import OnboardingDialog
        self._onboarding_dialog = OnboardingDialog(self, self.resource_path)
        self._onboarding_dialog.show()
        self._onboarding_dialog.raise_()
        self._onboarding_dialog.activateWindow()

    def _open_dropped_pack(self, archive):
        if self._closing:
            return
        self.download_page.open_content('modpack', 'import')
        controller = self.download_page.content_page.controller
        controller.import_directory = ''
        controller.inspectPack(archive)

    def init_ui(self):
        # 主布局
        main_widget = QWidget()
        main_widget.setContentsMargins(0, 0, 0, 0)
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(0, 0, 0, 23)
        main_layout.setSpacing(0)
        
        # 自定义标题栏
        self.title_bar = TitleBar(self, resource_path=self.resource_path)

        # 连接标签页点击信号
        self.title_bar.tab_switch_clicked.connect(self.switch_pages)
        
        main_layout.addWidget(self.title_bar)
        
        # 主内容区域
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        
        # 堆叠内容区域
        self.content_stack = QStackedWidget()
        content_layout.addWidget(self.content_stack)
        
        # 添加页面
        self.create_pages()
        main_layout.addWidget(content_widget)
        
        # 折叠测试
        self.title_bar.menu_toggle_signal.connect(self.toggle_menu)
    
    @property
    def user(self) -> MicrosoftAuthenticator:
        """用户角色信息"""
        return self.started_page.auth
    
    @property
    def launcher(self) -> MinecraftLibLauncher:
        """启动器核心"""
        return self.started_page.launcher
    
    def create_pages(self):
        """创建所有页面"""
        # 开始页面
        self.started_page = StartGamePage(self, resource_path=self.resource_path, cache_path=self.cache_path)
        self.started_page.login_success.connect(self.handle_login_success)
        self.started_page.started_changed.connect(self.started_page.started_game)  # 启动游戏，必须在主UI中进行
        self.title_bar.version_changed.connect(self.started_page.set_minecraft_version)
        self.content_stack.addWidget(self.started_page)

        # 下载页面 TODO
        self.download_page = DownloadPages(
            self,
            resource_path=self.resource_path,
            cache_path=self.cache_path
        )
        self.content_stack.addWidget(self.download_page)

        # 设置页面
        self.settings_page = SettingsPage(
            self,
            config_path=self.config_path,
            resource_path=self.resource_path,
            scale_ratio=self.scale_ratio
        )
        self.content_stack.addWidget(self.settings_page)

        # 版本管理
        self.version_page = VersionsPages(
            self,
            cache_path=self.cache_path,
            resource_path=self.resource_path
        )
        self.content_stack.addWidget(self.version_page)

        # 注册信号
        def on_directory_signal(minecraft_directory):
            self.started_page.launcher.minecraft_directory = minecraft_directory
            self.started_page.instance_changed.emit()

        def on_version_signal(version):
            self.title_bar.refresh_versions()
            selected = self.settings_manager.get_setting('minecraft.version.enable')
            self.title_bar.version_popup.set_selected(selected)
            self.started_page.set_minecraft_version(selected)

        self.version_page.signals.directory.connect(on_directory_signal)
        self.version_page.signals.versions.connect(on_version_signal)

        # 游戏日志信息回显
        # self.launcher = self.started_page.launcher
        self.launcher.signals.output.connect(self.minecraft_handle_output)
        self.launcher.signals.started.connect(self.minecraft_handle_started)
        self.launcher.signals.stopped.connect(self.minecraft_handle_stopped)
        self.launcher.signals.error.connect(self.minecraft_handle_error)
        self.launcher.signals.java_required.connect(self.minecraft_java_required)
        self.launcher.signals.java_install_progress.connect(self.minecraft_java_install_progress)
        self.launcher.signals.java_installed.connect(self.minecraft_java_installed)
        self.launcher.signals.progress.connect(self.minecraft_handle_progress)
    
    def minecraft_not_java_runtime(self):
        """打开启动器检查Java环境"""
        if self._closing:
            return
        if self.settings_manager.get_version_setting('java.path', None) is None \
                and not self.settings_manager.get_setting('java.installations', []):
            # 尝试本地搜索
            self.load_java_path(notify_missing=False)
            logger.warning('尝试本地搜索Java')
            return

        # Keep startup quiet; selecting Play prepares the correct Java automatically.

        # 对于未安装Java环境时,只提示Java环境安装,
        self.minecraft_not_gamed_runtime()

    def minecraft_not_gamed_runtime(self):
        """打开启动器检查游戏版本"""
        if self.settings_manager.get_setting('minecraft.version.enable') is None:
            logger.warning('未安装游戏版本，请安装游戏版本')
            self.started_page.set_minecraft_version(None)

    def load_java_path(self, notify_missing=True):
        """自动加载系统中Java路径"""

        # 在后台线程中执行搜索（避免阻塞UI）
        from PySide6.QtCore import QThread, Signal, QObject
        previous = getattr(self, 'search_thread', None)
        if previous is not None and previous.isRunning():
            return
        self._java_notify_missing = notify_missing
        configured = list(self.settings_manager.get_setting('java.installations', []) or [])
        
        class JavaSearchWorker(QObject):
            finished = Signal(list)
            error = Signal(str)
            
            def run(self):
                try:
                    finder = JavaPathFinder(cancelled=QThread.currentThread().isInterruptionRequested)
                    java_installations = finder.find_all_java_installations()
                    known = {os.path.normcase(os.path.abspath(item[0])) for item in java_installations}
                    for entry in configured:
                        if QThread.currentThread().isInterruptionRequested():
                            break
                        if not isinstance(entry, (list, tuple)) or not entry or not isinstance(entry[0], str):
                            continue
                        identity = os.path.normcase(os.path.abspath(entry[0]))
                        if identity in known or not os.path.isfile(entry[0]):
                            continue
                        raw, parsed = finder._get_java_version(entry[0])
                        if parsed:
                            java_installations.append((entry[0], raw, parsed))
                            known.add(identity)
                    self.finished.emit(java_installations)
                except Exception as e:
                    self.error.emit(str(e))
        
        # 创建和工作线程
        if previous is not None:
            previous.deleteLater()
        self.search_thread = QThread(self)
        self.worker = JavaSearchWorker()
        self.worker.moveToThread(self.search_thread)
        
        # 连接信号和槽
        self.search_thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.on_java_search_finished)
        self.worker.finished.connect(self.search_thread.quit, Qt.DirectConnection)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.error.connect(self.on_java_search_error)
        self.worker.error.connect(self.search_thread.quit, Qt.DirectConnection)
        self.worker.error.connect(self.worker.deleteLater)
        
        # 启动线程
        self.search_thread.start()

    def minecraft_not_java_version_runtime(self):
        from core.java_runtime import select_java, JavaRuntimeUnavailable
        try:
            select_java(self.settings_manager,
                        self.settings_manager.get_setting('minecraft.directory.enable') or '',
                        self.settings_manager.get_setting('minecraft.version.enable') or '')
        except JavaRuntimeUnavailable as exc:
            self._required_java_download = exc.required
            self.java_runtime_full.set_title('需要安装 Java')
            self.java_runtime_full.set_message(str(exc))
            return True
        return False

    def on_java_search_finished(self, java_installations):
        """Java搜索完成处理"""
        if self._closing:
            return
        print('java_installations', java_installations)
        if java_installations:
            # 自动选择推荐的Java
            finder = JavaPathFinder()
            best_java = finder.recommend_best_java(java_installations)

            current = self.settings_manager.get_version_setting('java.path')
            if not current or not os.path.isfile(current):
                self.settings_manager.set_version_setting('java.name', '使用推荐的 Java 版本|系统将自动选择最适合的 Java 版本')
                self.settings_manager.set_version_setting('java.path', best_java)
            self.settings_manager.set_setting('java.installations', java_installations)
            self.settings_manager.save_settings()
            self.settings_page.java_page.refresh_list()

            if getattr(self, '_java_notify_missing', True) and self.minecraft_not_java_version_runtime():
                self.java_runtime_full.exec()
                return
        else:
            self.settings_manager.set_setting('java.installations', [])
            self.settings_manager.save_settings()
            self.settings_page.java_page.refresh_list()
            logger.warning('未安装Java环境，请下载安装Java')
            if getattr(self, '_java_notify_missing', True):
                self.java_runtime_full.exec()
            return
        
    def on_java_search_error(self, error_message):
        """Java搜索错误处理"""
        print("搜索出错", f"错误信息: {error_message}")
        self.settings_page.java_page.refresh_list()
        self.settings_page.java_page.set_status('搜索失败，请重试')

    def on_gamed_import_signal(self):
        """用户选择了导入游戏向导"""
        logger.info("用户选择了导入游戏向导")
        self.switch_pages('实例')
        self.title_bar.set_active_tab('实例')
        QTimer.singleShot(100, lambda: self.version_page.versions_page.on_add_directory(None))
        pass

    def on_gamed_download_signal(self):
        """用户选择了下载游戏向导"""
        logger.info("用户选择了下载游戏向导")
        self.switch_pages("下载")
        pass

    def on_java_download_signal(self):
        """用户选择了下载Java向导"""
        self.switch_pages('设置')
        self.settings_page.java_tab_btn_clicked()
        if not self.settings_page.java_page.controller.java_catalog_open:
            self.settings_page.java_page.controller.action('', '下载')

    def switch_pages(self, name):
        """切换标签页"""
        if name in self.tab_names and self.content_stack.currentIndex() == self.tab_names.index(name):
            return
        # 获取当前活动页面的索引
        current_index = self.content_stack.currentIndex()
        
        # 如果当前有活动页面，调用其失活方法
        if current_index >= 0:
            current_widget = self.content_stack.widget(current_index)
            if hasattr(current_widget, 'on_page_deactivate'):
                current_widget.on_page_deactivate()
        
        # 切换到新页面
        self.current_tab = self.tab_names.index(name)
        self.content_stack.setCurrentIndex(self.current_tab)
        self.title_bar.set_active_tab(name)
        
        # 调用新页面的激活方法
        new_widget = self.content_stack.widget(self.current_tab)
        if hasattr(new_widget, 'on_page_activate'):
            new_widget.on_page_activate()
        
        logger.debug('Launcher page selected: %s', name)

    def set_window_size(self):
        """根据背景图片尺寸设置窗口大小"""
        bg_width = self.bg_image.width()
        bg_height = self.bg_image.height()
        self.setFixedSize(bg_width, bg_height)
        
    def minecraft_handle_output(self, message):
        """处理输出"""
        logger.info(f'minecraft_handle_output {message}')
        self._debug_output.append(str(message))
        self._debug_output = self._debug_output[-5000:]
        if self._debug_dialog is not None:
            self._debug_dialog.appendPlainText(str(message))

    def _show_debug_output(self):
        if self._debug_dialog is None:
            self._debug_dialog = DebugOutputDialog(self, self._debug_output)
        self._debug_dialog.show()
        self._debug_dialog.raise_()
        self._debug_dialog.activateWindow()
    
    def minecraft_handle_started(self):
        """游戏启动处理"""
        logger.info('minecraft_handle_started 游戏已启动')
        self._close_java_progress()
        if self.settings_manager.get_version_setting('launcher.debug', '否（推荐）') == '是':
            self._show_debug_output()
        # 应用可见性设置
        self.visibility_manager.apply_setting(self.settings_manager.get_version_setting('launcher.visibility', "游戏启动后保持不变"))
    
    def minecraft_handle_stopped(self, exit_code):
        """游戏停止处理"""
        logger.info(f"minecraft_handle_stopped 游戏已退出，代码: {exit_code}")
        self._close_java_progress()
        if self._close_after_game:
            QTimer.singleShot(100, self.close)
        else:
            self.visibility_manager.restore_if_needed()
            if exit_code and not self._launch_error_reported:
                self.show_launch_error('游戏异常退出',
                    f'Minecraft 已退出，退出代码：{exit_code}。',
                    '请查看游戏日志中的异常、模组冲突或崩溃报告；导出诊断日志时会一并收集。')

    def show_launch_error(self, title, message, detail='', required=0):
        if self._closing or self._close_after_game:
            return
        self._launch_error_reported = True
        if self._launch_error_dialog is None:
            self._launch_error_dialog = QmlDialog(self, width=620, height=390)
            self._launch_error_dialog.controller.actionRequested.connect(self._launch_error_action)
        dialog = self._launch_error_dialog
        self._required_java_download = required
        dialog.set_title(title)
        dialog.set_message(message)
        dialog.set_message_text(detail)
        dialog.controller.actions = ['下载 Java', 'Java 设置', '关闭'] if required else ['查看日志', '关闭']
        dialog.controller.changed.emit()
        self.showNormal()
        dialog.open()
        dialog.raise_()

    def _launch_error_action(self, action):
        self._launch_error_dialog.accept()
        if action == '下载 Java':
            self.on_java_download_signal()
        elif action == 'Java 设置':
            self.switch_pages('设置')
            self.settings_page.java_tab_btn_clicked()
        elif action == '查看日志':
            self._show_debug_output()

    def minecraft_java_required(self, version, required, detail):
        self._close_java_progress()
        self.minecraft_handle_output(f'[Java 检查] {detail}')
        self.show_launch_error('缺少适合的 Java',
            f'Minecraft {version} 缺少兼容的 Java {required} 运行环境。' if required else '没有可用的 Java 运行环境。',
            detail, required=required or 25)

    def minecraft_java_install_progress(self, message, done, total):
        page = self.settings_page.java_page
        page.controller._status = message + (f' · {min(100, max(0, done * 100 // total))}%' if total > 0 else '')
        page.controller.changed.emit()
        if self._closing:
            return
        if self._java_install_dialog is None:
            self._java_install_dialog = QmlDialog(self, width=620, height=350,
                title='正在准备 Java', actions=['取消安装'])
            self._java_install_dialog.controller.actionRequested.connect(self._cancel_java_install)
            self._java_install_dialog.rejected.connect(lambda:
                self.launcher.cancel_preparation() if self._java_install_dialog.controller.working else None)
        dialog = self._java_install_dialog
        dialog.controller.message = '此游戏缺少兼容的 Java，启动器正在自动安装。'
        dialog.controller.detail = message + (f'\n{done / 1024 ** 2:.1f} / {total / 1024 ** 2:.1f} MiB'
            if total > 1 else '')
        dialog.controller.working = True
        dialog.controller.progress = min(1., done / total) if total else -1.
        dialog.controller.changed.emit()
        if not dialog.isVisible():
            dialog.open()

    def _close_java_progress(self):
        if self._java_install_dialog is not None:
            self._java_install_dialog.controller.working = False
            self._java_install_dialog.close()

    def _cancel_java_install(self, action):
        self.launcher.cancel_preparation()
        self._close_java_progress()

    def minecraft_java_installed(self, entry):
        from core.java_downloads import register
        register(self.settings_manager, entry)
        self.settings_page.java_page.refresh_list()
        self._close_java_progress()
    
    def minecraft_handle_error(self, message):
        """错误处理"""
        logger.info(f'minecraft_handle_error {message}')
        self._close_java_progress()
        self.minecraft_handle_output(f'[错误] {message}')
        if self.settings_manager.get_version_setting('launcher.debug', '否（推荐）') == '是':
            self._show_debug_output()
        if self._close_after_game:
            QTimer.singleShot(100, self.close)
        else:
            self.visibility_manager.restore_if_needed()
            self.show_launch_error('游戏启动失败', str(message),
                                  '游戏启动未完成。可查看日志获取完整输出，或导出诊断日志进一步排查。')
    
    def minecraft_handle_progress(self, progress):
        """处理进度更新"""
        logger.info(f'minecraft_handle_progress {progress}')
    
    def handle_login_success(self, data, login_type):
        """处理登录成功事件"""
        pass
    
    def initialize_caches(self):
        """初始化预缓存 - 修正了QSize运算错误"""
        logger.info("开始初始化预缓存...")
        
        # 生成菜单展开状态的缓存
        expanded_size = self.bg_image.size()
        self.cache_expanded = QPixmap(expanded_size)
        self.cache_expanded.fill(Qt.transparent)
        
        painter = QPainter(self.cache_expanded)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.drawPixmap(0, 0, self.bg_image)
        painter.setPen(QPen(QColor("#565656"), 1))
        painter.drawRect(self.cache_expanded.rect().adjusted(0, 0, -1, -1))
        painter.end()

        logger.info("预缓存初始化完成。")
        self.cache_collapsed = self.cache_expanded.copy(
            self.menu_width, 0, self.cache_expanded.width() - self.menu_width,
            self.cache_expanded.height())

    def toggle_menu(self):
        """Crop the original background and commit one layout/paint update."""
        right = self.x() + self.width()
        self.setUpdatesEnabled(False)
        try:
            self.menu_collapsed = not self.menu_collapsed
            for index in range(self.content_stack.count()):
                page = self.content_stack.widget(index)
                if hasattr(page, 'toggle_menu'):
                    page.toggle_menu(self.menu_collapsed)
                if page.layout():
                    page.layout().activate()
            size = self.cache_collapsed.size() if self.menu_collapsed else self.cache_expanded.size()
            self.setFixedSize(size)
            self.move(right - size.width(), self.y())
            self.title_bar.controller.collapsed = self.menu_collapsed
            self.title_bar.controller.changed.emit()
            self.centralWidget().layout().activate()
        finally:
            self.setUpdatesEnabled(True)
        self.update()
    
    def paintEvent(self, event):
        """绘制事件 - 使用预缓存"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        target_pixmap = self.cache_collapsed if self.menu_collapsed else self.cache_expanded
        
        if not target_pixmap.isNull():
            painter.drawPixmap(0, 0, target_pixmap)
        
        super().paintEvent(event)

    def resizeEvent(self, event):
        """窗口大小改变事件处理"""
        super().resizeEvent(event)

    def closeEvent(self, event):
        # A user close must leave rooms even while the Java output worker is
        # kept alive until the independently running game exits.
        lobby = getattr(self.started_page, '_multiplayer_dialog', None)
        if lobby is not None:
            lobby.shutdown()
        thread = getattr(self.launcher, 'start_thread', None)
        if thread is not None and thread.isRunning():
            self.launcher.cancel_preparation()
            self._close_after_game = True
            self.hide()
            lobby = getattr(self.started_page, '_multiplayer_dialog', None)
            if lobby is not None:
                lobby.hide()
            if self._debug_dialog is not None:
                self._debug_dialog.hide()
            event.ignore()
            if not self.launcher.running:
                QTimer.singleShot(100, self.close)
            return
        self._closing = True
        if not self.settings_page.java_page.controller.shutdown():
            event.ignore()
            QTimer.singleShot(100, self.close)
            return
        if not self.download_page.shutdown():
            event.ignore()
            QTimer.singleShot(100, self.close)
            return
        search = getattr(self, 'search_thread', None)
        if search is not None and search.isRunning():
            search.requestInterruption()
            search.quit()
            if not search.wait(100):
                event.ignore()
                QTimer.singleShot(100, self.close)
                return
        if self._debug_dialog is not None:
            self._debug_dialog.shutdown()
            self._debug_dialog.close()
        self.started_page.auth_refresh_timer.stop()
        self.started_page.auth_manager.cancel_refresh()
        self.started_page.login_dialog.auth.cancel_authentication()
        # Closing can originate in a QML button. Unload only after that handler
        # returns, otherwise its visual object is deleted while onClicked runs.
        QTimer.singleShot(0, self, self._release_qml)
        super().closeEvent(event)

    def _release_qml(self):
        from PySide6.QtQuickWidgets import QQuickWidget
        from PySide6.QtCore import QUrl
        for quick in self.findChildren(QQuickWidget):
            quick.setSource(QUrl())

    # 窗口拖动功能
    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self.dragging = True
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
    
    def mouseMoveEvent(self, event: QMouseEvent):
        if self.dragging and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()
    
    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self.dragging = False
            event.accept()
