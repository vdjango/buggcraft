# 主窗口

import os
import logging
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QStackedWidget, QVBoxLayout, QHBoxLayout
)
from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QPixmap, QPainter

logger = logging.getLogger(__name__)

from utils.helpers import scale_component
from config.settings import get_settings_manager
# from core.launcher import MinecraftLibLauncher
from core.visibility import LauncherVisibilityManager
from core.auth.microsoft import MicrosoftAuthenticator
from ui.widgets.titlebar import TitleBar
# from ui.widgets.buttons import QMStartButton
# from ui.widgets.cards import QMCard
from ui.widgets.panels import UserPanel
from ui.pages.singleplayer_page import SinglePlayerPage
# from ui.pages.multiplayer_page import MultiplayerPage
# from ui.pages.download_page import DownloadPage
from ui.pages.settings_page import SettingsPage
# from ui.pages.more_page import MorePage

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
        self.current_tab = "singleplayer"
        
        # 设置背景图片
        self.bg_image = None
        self.load_background_image()

        # 移除默认标题栏
        self.setWindowFlag(Qt.FramelessWindowHint)
        # 根据背景图片尺寸设置窗口大小
        self.set_window_size_from_background()

        self.init_ui()

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

    def paintEvent(self, event):
        """重绘事件 - 绘制背景图片"""
        if self.bg_image:
            painter = QPainter(self)
            # 直接绘制原始尺寸的背景图片，不进行缩放
            painter.drawPixmap(0, 0, self.bg_image)
        super().paintEvent(event)

    def integrate_start_game_button(self):
        """将启动游戏按钮集成到登录信息组件中"""
        if hasattr(self, 'startedplayer_page') and hasattr(self.startedplayer_page, 'launch_btn'):
            # 获取启动按钮的引用
            start_btn = self.startedplayer_page.launch_btn
            
            if start_btn.parent():
                start_btn.setParent(None)
            
            # 将按钮添加到登录信息组件的布局中
            self.user_panel.start_game_btn = start_btn
            login_info_layout = self.user_panel.login_info_widget.layout()
            
            multiplayer_btn_index = -1
            for i in range(login_info_layout.count()):
                item = login_info_layout.itemAt(i)
                if item and item.widget() == self.user_panel.multiplayer_lobby_btn:
                    multiplayer_btn_index = i
                    break
            
            if multiplayer_btn_index >= 0:
                # 在进入联机大厅按钮之前插入启动游戏按钮
                login_info_layout.insertWidget(multiplayer_btn_index, start_btn, 0, Qt.AlignCenter)
            else:
                # 如果找不到进入联机大厅按钮，就添加到最后
                login_info_layout.addWidget(start_btn, 0, Qt.AlignCenter)
            
            # 连接启动信号到单人游戏页面的启动方法
            start_btn.clicked.disconnect()  # 断开原有连接
            start_btn.clicked.connect(self.startedplayer_page.started_game)
            
            logger.info("启动游戏按钮已集成到登录信息组件中")
    
    def position_login_info(self):
        """将登录信息组件定位 水平中央"""
        if hasattr(self.user_panel, 'login_info_widget'):
            # 获取主窗口尺寸
            window_width = self.width()
            window_height = self.height()
            
            # 获取登录信息组件尺寸
            widget_width = self.user_panel.login_info_widget.width()
            widget_height = self.user_panel.login_info_widget.height()
            
            window_width = self.width()
            x = (window_width - widget_width) // 2 + 100
            y = (window_height - widget_height) // 2 
            
            # 设置父组件为主窗口的中央组件
            self.user_panel.login_info_widget.setParent(self.centralWidget())
            self.user_panel.login_info_widget.move(x, y)
            self.user_panel.login_info_widget.show()
            

    def resizeEvent(self, event):
        """窗口大小改变事件处理"""
        super().resizeEvent(event)
        # 定位登录信息组件
        if hasattr(self, 'user_panel'):
            self.position_login_info()

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
        # def handle_status(code):
        #     if code == 0:
        #         self.user_panel.login_status.setText("<font color='#4CAF50'>游戏已正常退出</font>")
            
        #     # 5秒后恢复状态
        #     from PySide6.QtCore import QTimer
        #     QTimer.singleShot(1000, lambda: {
        #         self.user_panel.login_status.setText("<font color='#4CAF50'>准备就绪</font>")
        #     })

        logger.info(f"minecraft_handle_stopped 游戏已退出，代码: {exit_code}")
        # QTimer.singleShot(5000, lambda: handle_status(exit_code))
        # 恢复启动器
        self.visibility_manager.restore_if_needed()
    
    def minecraft_handle_error(self, message):
        """错误处理"""
        logger.info(f'minecraft_handle_error {message}')
        self.visibility_manager.restore_if_needed()
    
    def minecraft_handle_progress(self, progress):
        """处理进度更新"""
        logger.info(f'minecraft_handle_progress {progress}')
    
    def handle_login_success(self, data, login_type):
        """处理登录成功事件"""
        pass
    
    # ==========================

    def init_ui(self):
        # 主布局
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 自定义标题栏
        self.title_bar = TitleBar(self, resource_path=self.resource_path)
        main_layout.addWidget(self.title_bar)
        
        # 主内容区域
        content_widget = QWidget()
        content_layout = QHBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        
        # 左侧用户面板
        self.user_panel = UserPanel(self, resource_path=self.resource_path, cache_path=self.cache_path)
        self.user_panel.login_success.connect(self.handle_login_success)
        self.user_panel.panel_hide.connect(self.user_panel.hide)
        self.user_panel.panel_show.connect(self.user_panel.show)
        self.user_panel.authorized_online_auto()
        content_layout.addWidget(self.user_panel)
        
        # 右侧内容区域
        self.content_stack = QStackedWidget()
        content_layout.addWidget(self.content_stack)
        
        # 添加页面
        self.create_pages()
        main_layout.addWidget(content_widget)
        
        # 将启动游戏按钮集成到登录信息组件中
        self.integrate_start_game_button()
        
        # 将登录信息组件移动到右侧水平中央
        QTimer.singleShot(100, self.position_login_info)
    
    @property
    def user(self) -> MicrosoftAuthenticator:
        # 用户角色信息
        return self.user_panel.auth
    
    def create_pages(self):
        """创建所有页面"""
        # 单机页面
        self.startedplayer_page = SinglePlayerPage(
            self,
            config_path=self.config_path,
            resource_path=self.resource_path,
            scale_ratio=self.scale_ratio
        )
        self.startedplayer_page.started_changed.connect(self.startedplayer_page.started_game)  # 启动游戏，必须在主UI中进行

        # 游戏日志信息回显
        self.launcher = self.startedplayer_page.launcher
        self.launcher.signals.output.connect(self.minecraft_handle_output)
        self.launcher.signals.started.connect(self.minecraft_handle_started)
        self.launcher.signals.stopped.connect(self.minecraft_handle_stopped)
        self.launcher.signals.error.connect(self.minecraft_handle_error)
        self.launcher.signals.progress.connect(self.minecraft_handle_progress)
        self.content_stack.addWidget(self.startedplayer_page)
        
        # 多人游戏页面
        # self.multiplayer_page = MultiplayerPage(self.resource_path, self.scale_ratio)
        # self.content_stack.addWidget(self.multiplayer_page)
        
        # 下载页面
        # self.download_page = DownloadPage(self.resource_path, self.scale_ratio)
        # self.content_stack.addWidget(self.download_page)
        
        # 设置页面
        self.settings_page = SettingsPage(
            self,
            config_path=self.config_path,
            resource_path=self.resource_path,
            scale_ratio=self.scale_ratio
        )
        self.content_stack.addWidget(self.settings_page)
        
        # 更多页面
        # self.more_page = MorePage(self.resource_path, self.scale_ratio)
        # self.content_stack.addWidget(self.more_page)

    def switch_pages(self, index):
        """切换标签页"""
        tab_names = ["singleplayer", "multiplayer", "download", "settings", "more"]
        self.current_tab = tab_names[index]
        self.content_stack.setCurrentIndex(index)
        if index == 0:
            self.user_panel.on_show_animation_finished()
        else:
            self.user_panel.on_hide_animation_finished()
    
    def closeEvent(self, event):
        self.settings_page.save_all_settings()  # 假设 settings_page 是 SettingsPage 实例
        super().closeEvent(event)

    def show_launch_settings(self):
        """显示启动参数设置"""
        self.settings_stack.setCurrentIndex(0)
    
    def show_personalization(self):
        """显示个性化设置"""
        self.settings_stack.setCurrentIndex(1)
    
    def show_other_settings(self):
        """显示其他设置"""
        self.settings_stack.setCurrentIndex(2)
    
    def show_about(self):
        """显示关于页面"""
        self.more_stack.setCurrentIndex(0)
    
    def show_feedback(self):
        """显示反馈页面"""
        self.more_stack.setCurrentIndex(1)
    
    def submit_feedback(self):
        """提交反馈"""
        # QDesktopServices.openUrl(QUrl("https://github.com/minecraft-launcher/issues"))
        # QMessageBox.information(self, "提交成功", "您的反馈已提交，感谢您的支持！")
        pass
