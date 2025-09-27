# 主窗口

import os
import logging
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QStackedWidget, QVBoxLayout
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QPixmap, QPainter

from utils.helpers import scale_component
from config.settings import get_settings_manager
from core.visibility import LauncherVisibilityManager
from core.auth.microsoft import MicrosoftAuthenticator
from ui.widgets.titlebar import TitleBar
from ui.pages import StartGamePage, SettingsPage, VersionControlPage

import logging
logger = logging.getLogger(__name__)


class MinecraftLauncher(QMainWindow):
    """主启动器界面"""

    def __init__(self, cache_path, config_path, resource_path):
        super().__init__()
        self.cache_path = cache_path
        self.config_path = config_path
        self.resource_path = resource_path

        self.scale_ratio = scale_component(QSize(1280, 832), QSize(1280-1280/3, 832-832/3))
        self.settings_manager = get_settings_manager(self.config_path)  # 获取配置管理器
        self.visibility_manager = LauncherVisibilityManager(self)  # 初始化可见性管理器

        # ["StartedGame", "Settings", "VersionControl"]
        self.tab_names = {
            '开始': 'StartedGame',
            '设置': 'Settings',
            # '版本选择': 'VersionList',
            '版本管理': 'VersionControl'
        }
        self.current_tab = "StartedGame"
        
        # 设置背景图片
        self.bg_image = None
        self.load_background_image()

        self.setWindowFlag(Qt.FramelessWindowHint)  # 移除默认标题栏
        self.set_window_size_from_background()  # 根据背景图片尺寸设置窗口大小
        self.init_ui()

    def init_ui(self):
        # 主布局
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
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
    
    @property
    def user(self) -> MicrosoftAuthenticator:
        # 用户角色信息
        return self.started_page.auth
    
    def create_pages(self):
        """创建所有页面"""
        # 开始页面
        self.started_page = StartGamePage(self, resource_path=self.resource_path, cache_path=self.cache_path)
        self.started_page.login_success.connect(self.handle_login_success)
        self.started_page.started_changed.connect(self.started_page.started_game)  # 启动游戏，必须在主UI中进行
        self.content_stack.addWidget(self.started_page)

        # 设置页面
        self.settings_page = SettingsPage(
            self,
            config_path=self.config_path,
            resource_path=self.resource_path,
            scale_ratio=self.scale_ratio
        )
        self.content_stack.addWidget(self.settings_page)

        # 版本管理
        self.version_control_page = VersionControlPage(
            self,
            cache_path=self.cache_path,
            resource_path=self.resource_path
        )
        self.content_stack.addWidget(self.version_control_page)

        # 游戏日志信息回显
        self.launcher = self.started_page.launcher
        self.launcher.signals.output.connect(self.minecraft_handle_output)
        self.launcher.signals.started.connect(self.minecraft_handle_started)
        self.launcher.signals.stopped.connect(self.minecraft_handle_stopped)
        self.launcher.signals.error.connect(self.minecraft_handle_error)
        self.launcher.signals.progress.connect(self.minecraft_handle_progress)
        
    def switch_pages(self, name):
        """切换标签页"""
        def remove_duplicates_preserve_order(sequence):
            """移除重复项并保持顺序"""
            seen = set()
            return [x for x in sequence if not (x in seen or seen.add(x))]

        tab_names = remove_duplicates_preserve_order(self.tab_names.values())
        self.current_tab = self.tab_names[name]
        index =  tab_names.index(self.current_tab)
        print('switch_pages', tab_names, index, self.current_tab)
        self.content_stack.setCurrentIndex(index)
    
    def load_background_image(self):
        """加载背景图片"""
        bg_path = os.path.abspath(os.path.join(self.resource_path, 'images', 'minecraft_bg.png'))
        if os.path.exists(bg_path):
            self.bg_image = QPixmap(bg_path)
            logger.info(f"主窗口背景图片加载成功: {bg_path}")
            logger.info(f"背景图片尺寸: {self.bg_image.width()}x{self.bg_image.height()}")
        else:
            logger.error(f"主窗口背景图片不存在: {bg_path}")

    def set_window_size_from_background(self):
        """根据背景图片尺寸设置窗口大小"""
        if self.bg_image and not self.bg_image.isNull():
            # 使用背景图片的实际尺寸
            bg_width = self.bg_image.width()
            bg_height = self.bg_image.height()
            self.setFixedWidth(bg_width)
            self.setFixedHeight(bg_height)
            logger.info(f"窗口大小已调整为背景图片尺寸: {bg_width}x{bg_height}")
        else:
            # 如果背景图片加载失败，使用默认尺寸
            default_width = int(1280 * self.scale_ratio)
            default_height = int(832 * self.scale_ratio)
            self.setFixedWidth(default_width)
            self.setFixedHeight(default_height)
            logger.warning(f"背景图片未加载，使用默认窗口尺寸: {default_width}x{default_height}")

    def minecraft_handle_output(self, message):
        """处理输出"""
        logger.info(f'minecraft_handle_output {message}')
    
    def minecraft_handle_started(self):
        """游戏启动处理"""
        logger.info('minecraft_handle_started 游戏已启动')
        # 应用可见性设置
        self.visibility_manager.apply_setting(self.settings_manager.get_setting('launcher.visibility', "游戏启动后保持不变"))
    
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

    def paintEvent(self, event):
        """重绘事件 - 绘制背景图片"""
        if self.bg_image:
            painter = QPainter(self)
            # 直接绘制原始尺寸的背景图片，不进行缩放
            painter.drawPixmap(0, 0, self.bg_image)
        super().paintEvent(event)
    
    def resizeEvent(self, event):
        """窗口大小改变事件处理"""
        super().resizeEvent(event)

    def closeEvent(self, event):
        self.settings_page.save_all_settings()  # 假设 settings_page 是 SettingsPage 实例
        super().closeEvent(event)
