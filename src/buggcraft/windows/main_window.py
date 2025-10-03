# 主窗口

import os
import logging
import webbrowser

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QStackedWidget, QVBoxLayout, QPushButton
)
from PySide6.QtCore import Qt, QSize, QPoint, QTimer, QRect
from PySide6.QtGui import QPixmap, QPainter, QMouseEvent, QPen, QColor

from utils.helpers import scale_component
from config.javafinder import JavaPathFinder
from config.settings import get_settings_manager
from core.visibility import LauncherVisibilityManager
from core.auth.microsoft import MicrosoftAuthenticator
from core.launcher import MinecraftLibLauncher
from ui.widgets.titlebar import TitleBar
from ui.pages import StartGamePage, SettingsPage, VersionsPages, VersionsListPages
from ui.dialog.NotFuilMinecraftVersionDialog import VersionNotFuilDialog, QDialog
from ui.dialog.NotFuilJavaDialog import JavaRuntimeNotFuilDialog

import logging
logger = logging.getLogger(__name__)


class MinecraftLauncher(QMainWindow):
    """主启动器界面"""

    def __init__(self, base_path, cache_path, config_path, resource_path):
        super().__init__()
        self.base_path = base_path
        self.cache_path = cache_path
        self.config_path = config_path
        self.resource_path = resource_path

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
            self.settings_manager.set_setting('java.installations', [])
            self.settings_manager.save_settings()
        
        for i in self.settings_manager.get_setting('java.installations', []):
            """校验格式"""
            if len(i) != 3:
                self.settings_manager.set_setting('java.installations', [])
                self.settings_manager.save_settings()
        
        # 同步 TitleBar 菜单顺序，同时主页面添加堆叠页面顺序也需要同步
        self.tab_names = [
            '开始', "下载", '设置', '实例'
        ]
        self.current_tab = 0
        
        # 设置背景图片
        self.menu_width = 178 + 27  # 左侧菜单宽度
        self.menu_collapsed = False  # 折叠状态
        self.is_animating = False
        
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
        self.cache_collapsed = QPixmap()
        # 启用双缓冲
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground, False)
        self.setWindowFlag(Qt.FramelessWindowHint)  # 移除默认标题栏
        
        self.set_window_size_from_background()  # 根据背景图片尺寸设置窗口大小
        self.init_ui()
        # QTimer.singleShot(500, self.initialize_caches)
        self.initialize_caches()

        self.version_not_number = 0
        self.java_runtime_full = JavaRuntimeNotFuilDialog()
        self.gamed_runtime_full = VersionNotFuilDialog()
        self.java_runtime_full.download_signal.connect(self.on_java_download_signal)
        self.gamed_runtime_full.download_signal.connect(self.on_gamed_download_signal)
        self.gamed_runtime_full.import_signal.connect(self.on_gamed_import_signal)

        QTimer.singleShot(500, self.minecraft_not_java_runtime)

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
        self.started_page.multiplayer_lobby_btn.mousePressEvent = lambda t: self.toggle_menu()
    
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
        self.content_stack.addWidget(self.started_page)

        # 下载页面 TODO
        self.started_page1 = StartGamePage(self, resource_path=self.resource_path, cache_path=self.cache_path)
        self.started_page1.login_success.connect(self.handle_login_success)
        self.started_page1.started_changed.connect(self.started_page1.started_game)  # 启动游戏，必须在主UI中进行
        self.content_stack.addWidget(self.started_page1)

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

        def on_version_signal(version):
            self.started_page.launcher.minecraft_version = version
            self.started_page.set_minecraft_version(version)

        self.version_page.signals.directory.connect(on_directory_signal)
        self.version_page.signals.versions.connect(on_version_signal)

        # 游戏日志信息回显
        # self.launcher = self.started_page.launcher
        self.launcher.signals.output.connect(self.minecraft_handle_output)
        self.launcher.signals.started.connect(self.minecraft_handle_started)
        self.launcher.signals.stopped.connect(self.minecraft_handle_stopped)
        self.launcher.signals.error.connect(self.minecraft_handle_error)
        self.launcher.signals.progress.connect(self.minecraft_handle_progress)
    
    def minecraft_not_java_runtime(self):
        """打开启动器检查Java环境"""
        if self.settings_manager.get_version_setting('java.path', None) is None:
            # https://download.oracle.com/java/21/latest/jdk-21_windows-x64_bin.msi
            # 尝试本地搜索
            self.load_java_path()
            logger.warning('尝试本地搜索Java')
            return

        if self.minecraft_not_java_version_runtime():
            self.java_runtime_full.exec()
            return

        # 对于未安装Java环境时,只提示Java环境安装,
        self.minecraft_not_gamed_runtime()

    def minecraft_not_gamed_runtime(self):
        """打开启动器检查游戏版本"""
        if self.settings_manager.get_setting('minecraft.version.enable') is None:
            logger.warning('未安装游戏版本，请安装游戏版本')
            self.gamed_runtime_full.exec()

    def load_java_path(self):
        """自动加载系统中Java路径"""

        # 在后台线程中执行搜索（避免阻塞UI）
        from PySide6.QtCore import QThread, Signal, QObject
        
        class JavaSearchWorker(QObject):
            finished = Signal(list)
            error = Signal(str)
            
            def run(self):
                try:
                    finder = JavaPathFinder()
                    java_installations = finder.find_all_java_installations()
                    self.finished.emit(java_installations)
                except Exception as e:
                    self.error.emit(str(e))
        
        # 创建和工作线程
        self.search_thread = QThread()
        self.worker = JavaSearchWorker()
        self.worker.moveToThread(self.search_thread)
        
        # 连接信号和槽
        self.search_thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.on_java_search_finished)
        self.worker.finished.connect(self.search_thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.error.connect(self.on_java_search_error)
        self.search_thread.finished.connect(self.search_thread.deleteLater)
        
        # 启动线程
        self.search_thread.start()

    def minecraft_not_java_version_runtime(self):
        finder = JavaPathFinder()
        
        best_java = self.settings_manager.get_version_setting('java.path')
        current_version = finder._get_java_version(best_java)[1][:2]
        current_version = '.'.join(list(str(i) for i in current_version))
        if finder.is_java_version_low(best_java):
            """版本过低"""
            logger.warning(f'版本过低 {best_java}')
            self.java_runtime_full.set_title(f'Java版本过低')
            self.java_runtime_full.set_message(f'当前Java版本 {current_version}，可能无法运行最新版Minecraft。')
            return True

        return False

    def on_java_search_finished(self, java_installations):
        """Java搜索完成处理"""
        print('java_installations', java_installations)
        if java_installations:
            # 自动选择推荐的Java
            finder = JavaPathFinder()
            best_java = finder.recommend_best_java(java_installations)

            self.settings_manager.set_version_setting('java.name', '使用推荐的 Java 版本|系统将自动选择最适合的 Java 版本')
            self.settings_manager.set_version_setting('java.path', best_java)
            self.settings_manager.set_setting('java.installations', java_installations)
            self.settings_manager.save_settings()

            if self.minecraft_not_java_version_runtime():
                self.java_runtime_full.exec()
                return
        else:
            logger.warning('未安装Java环境，请下载安装Java')
            self.java_runtime_full.exec()
            return
        
    def on_java_search_error(self, error_message):
        """Java搜索错误处理"""
        print("搜索出错", f"错误信息: {error_message}")

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
        pass

    def on_java_download_signal(self):
        """用户选择了下载Java向导"""
        import sys
        # https://download.oracle.com/java/21/latest/jdk-21_windows-x64_bin.msi
        logger.info("用户选择了下载Java向导")
        webbrowser.open('https://download.oracle.com/java/21/latest/jdk-21_windows-x64_bin.msi')
        QTimer.singleShot(1000, sys.exit)
        pass

    def switch_pages(self, name):
        """切换标签页"""
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
        
        # 调用新页面的激活方法
        new_widget = self.content_stack.widget(self.current_tab)
        if hasattr(new_widget, 'on_page_activate'):
            new_widget.on_page_activate()
        
        print('switch_pages', self.tab_names, name)

    def set_window_size_from_background(self):
        """根据背景图片尺寸设置窗口大小"""
        bg_width = self.bg_image.width()
        bg_height = self.bg_image.height()
        self.resize(bg_width, bg_height)
        self.setMinimumSize(bg_width - self.menu_width, bg_height)
        self.setMaximumSize(bg_width, bg_height)
        
    def minecraft_handle_output(self, message):
        """处理输出"""
        logger.info(f'minecraft_handle_output {message}')
    
    def minecraft_handle_started(self):
        """游戏启动处理"""
        logger.info('minecraft_handle_started 游戏已启动')
        # 应用可见性设置
        self.visibility_manager.apply_setting(self.settings_manager.get_version_setting('launcher.visibility', "游戏启动后保持不变"))
    
    def minecraft_handle_stopped(self, exit_code):
        """游戏停止处理"""
        logger.info(f"minecraft_handle_stopped 游戏已退出，代码: {exit_code}")
        self.visibility_manager.restore_if_needed()  # 恢复启动器
    
    def minecraft_handle_error(self, message):
        """错误处理"""
        logger.info(f'minecraft_handle_error {message}')
        self.visibility_manager.restore_if_needed()  # 恢复启动器
    
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

        original_size = self.cache_expanded.size()
        collapsed_width = original_size.width() - self.menu_width
        collapsed_height = original_size.height()
        collapsed_size = QSize(collapsed_width, collapsed_height)
        
        self.cache_collapsed = QPixmap(collapsed_size)
        self.cache_collapsed.fill(Qt.transparent)
        
        painter = QPainter(self.cache_collapsed)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 只绘制右侧内容部分
        content_rect = QRect(0, 0, collapsed_width, collapsed_height)
        source_rect = QRect(self.menu_width, 0, collapsed_width, collapsed_height)
        painter.drawPixmap(content_rect, self.bg_image, source_rect)
        painter.setPen(QPen(QColor("#565656"), 1))
        painter.drawRect(self.cache_collapsed.rect().adjusted(0, 0, -1, -1))
        painter.end()
        
        logger.info("预缓存初始化完成。")

    def toggle_menu(self):
        """切换菜单状态"""
        if self.is_animating:
            return
            
        self.is_animating = True
        self.started_page.tab_buttons_widget.setEnabled(False)
        
        current_geometry = self.frameGeometry()
        current_pos = current_geometry.topLeft()
        current_width = current_geometry.width()
        current_height = current_geometry.height()
        
        if self.menu_collapsed:
            new_width = current_width + self.menu_width
            new_pos = QPoint(current_pos.x() - self.menu_width, current_pos.y())
        else:
            new_width = current_width - self.menu_width
            new_pos = QPoint(current_pos.x() + self.menu_width, current_pos.y())
        
        self.setGeometry(new_pos.x(), new_pos.y(), new_width, current_height)
        self.menu_collapsed = not self.menu_collapsed
        
        self.title_bar.toggle_menu(self.menu_collapsed)
        self.started_page.toggle_menu(self.menu_collapsed)
        self.settings_page.toggle_menu(self.menu_collapsed)
        self.version_page.toggle_menu(self.menu_collapsed)
        
        # 更新状态和触发重绘
        self.update() # 触发paintEvent
        # 延迟后重新启用交互
        from PySide6.QtCore import QTimer
        QTimer.singleShot(100, self.enable_interaction)
    
    def enable_interaction(self):
        self.is_animating = False
        self.started_page.tab_buttons_widget.setEnabled(True)
    
    def paintEvent(self, event):
        """绘制事件 - 使用预缓存"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        if self.menu_collapsed:
            target_pixmap = self.cache_collapsed
        else:
            target_pixmap = self.cache_expanded
        
        if not target_pixmap.isNull():
            painter.drawPixmap(0, 0, target_pixmap)
        
        super().paintEvent(event)

    def resizeEvent(self, event):
        """窗口大小改变事件处理"""
        super().resizeEvent(event)

    def closeEvent(self, event):
        super().closeEvent(event)

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
