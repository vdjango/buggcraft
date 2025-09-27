"""版本管理
 - 版本列表
 - 版本设置
"""

# StartGamePage 类
import os

from PySide6.QtWidgets import (
    QWidget, QLabel, QLineEdit, QVBoxLayout, QHBoxLayout, QFrame
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QFont, QPixmap, QColor, QPainter

from core.auth.microsoft import Authenticator, MinecraftSignals
from ui.widgets.buttons import QMStartButton
from ui.dialog.LoginDialog import LoginWaitDialog
from config.settings import get_settings_manager
from core.launcher import MinecraftLibLauncher
from utils.helpers import get_physical_resolution

import logging
logger = logging.getLogger(__name__)


class VersionControlPage(QWidget):
    """版本管理"""

    def __init__(self, parent, resource_path, cache_path):
        super().__init__(parent)
        self.parent = parent
        self.cache_path = cache_path
        self.resource_path = resource_path
        self.login_index = 0  # 第几次登录
        self.current_login_mode = "正版登录"  # 当前登录模式：正版登录/离线登录
        self.background_color = QColor(0, 0, 0, 0)  # 透明背景
        
        # 初始化设置管理器
        self.settings_manager = get_settings_manager()

        # 初始化UI
        self.init_ui()


    @property
    def auth(self):
        return self.login_dialog.auth
    
    def init_ui(self):
        """初始化用户界面"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 创建选项卡容器
        self.tab_container = QWidget()
        tab_container_layout = QHBoxLayout(self.tab_container)
        tab_container_layout.setContentsMargins(15, 0, 15, 0)
        
        # 创建选项卡按钮区域
        self.tab_buttons_widget = self.create_tab_buttons()
        self.tab_buttons_widget.setStyleSheet("background-color: #225500;")
        
        # 创建选项卡内容区域
        self.tab_content = QWidget()
        self.tab_content.setFixedWidth(926 - 178 - 62)
        self.tab_content.setContentsMargins(25, 0, 25, 0)
        self.tab_content.setStyleSheet("background-color: #552299;")

        tab_content_layout = QVBoxLayout(self.tab_content)
        tab_content_layout.setContentsMargins(0, 0, 0, 0)
        tab_content_layout.addStretch()

        # tab_content_layout.addSpacing(20)
        # tab_content_layout.addWidget(minecraft_logo, 0, Qt.AlignCenter)
        # tab_content_layout.addSpacing(20)  # MINECRAFT图片与头像间距

        tab_container_layout.addWidget(self.tab_buttons_widget)
        tab_container_layout.addSpacing(23)
        tab_container_layout.addWidget(self.tab_content)

        main_layout.addWidget(self.tab_container)
    
    def create_tab_buttons(self):
        """创建选项卡按钮区域"""
        tab_buttons_widget = QWidget()
        tab_buttons_widget.setFixedWidth(178)
        tab_buttons_widget.setContentsMargins(0, 0, 0, 0)   
        tab_buttons_layout = QVBoxLayout(tab_buttons_widget)
        tab_buttons_layout.setContentsMargins(0, 0, 0, 0)
        tab_buttons_layout.addSpacing(20)   

        # 创建紫色分隔线
        shared_separator = QFrame()
        shared_separator.setFrameShape(QFrame.HLine)
        shared_separator.setStyleSheet("background-color: rgba(139, 133, 218, 1);")
        shared_separator.setFixedWidth(155)
        shared_separator.setFixedHeight(2)
        tab_buttons_layout.addWidget(shared_separator, 0, Qt.AlignCenter)

        # 离线选项卡按钮
        self.offline_tab_btn = self.create_tab_button(
            "离线登录",
            self.offline_tab_btn_clicked,
            size=(155, 44), font_size=10
        )
        tab_buttons_layout.addWidget(self.offline_tab_btn, 0, Qt.AlignCenter)
        
        # 正版选项卡按钮
        self.external_tab_btn = self.create_tab_button(
            "正版登录",
            self.external_tab_btn_clicked,
            size=(155, 44), font_size=10
        )
        tab_buttons_layout.addWidget(self.external_tab_btn, 0, Qt.AlignCenter)
        tab_buttons_layout.addStretch()
        
        # 设置初始状态：正版登录默认选中
        self.update_tab_button_style("正版登录", True)
        self.update_tab_button_style("离线登录", False)
        
        return tab_buttons_widget

    def create_tab_button(self, text, click_handler, size=(155, 44), font_size=12):
        """创建选项卡按钮"""
        button = QLabel()
        button.mousePressEvent = lambda event: click_handler()
        button.setFixedSize(*size)
        button.setStyleSheet("background-color: transparent;")
        
        # 添加文本
        text_label = QLabel(text, button)
        text_label.setFont(QFont("Source Han Sans CN Heavy", font_size))
        text_label.setAlignment(Qt.AlignCenter)  
        text_label.setStyleSheet("color: white; background-color: transparent;")
        text_label.setGeometry(0, 0, *size)   
        
        return button

    def external_tab_btn_clicked(self):
        """正版登录按钮点击事件"""
        # self.external_content.show()
        # self.offline_content.hide()
        # self.auth_manager.current_mode = 'online'
        self.update_tab_button_style("正版登录", True)
        self.update_tab_button_style("离线登录", False)
        self.current_login_mode = "正版登录"
        # self.update_ui_state()
        # self.restore_login_state()

    def offline_tab_btn_clicked(self):
        """离线登录按钮点击事件"""
        # self.external_content.hide()
        # self.offline_content.show()
        # self.auth_manager.current_mode = 'offline'
        self.update_tab_button_style("正版登录", False)
        self.update_tab_button_style("离线登录", True)
        self.current_login_mode = "离线登录"
        # self.update_ui_state()
        # self.restore_login_state()

    def update_tab_button_style(self, tab_name, is_active):
        """更新选项卡按钮样式"""
        if tab_name == "正版登录":
            btn = self.external_tab_btn
            active_image = os.path.join(self.resource_path, 'images', 'user', 'external_tab_btn_active.png')
        else:
            btn = self.offline_tab_btn
            active_image = os.path.join(self.resource_path, 'images', 'user', 'external_tab_btn_active.png')
        
        if is_active and os.path.exists(active_image):
            btn.setPixmap(QPixmap(active_image).scaled(155, 44, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
        else:
            btn.clear()
            btn.setStyleSheet("background-color: transparent;")


    def paintEvent(self, event):
        """重绘事件 - 透明背景"""
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.background_color)    
        super().paintEvent(event)

    def setBackgroundColor(self, color):
        """设置新的背景颜色并更新界面"""
        if isinstance(color, str):
            self.backgroundColor = QColor(color)
        else:
            self.backgroundColor = color
        self.update()

    
    def resizeEvent(self, event):
        """窗口大小变化事件 - 确保布局自适应"""
        super().resizeEvent(event)

    def moveEvent(self, event):
        """重写 moveEvent 以跟踪位置变化"""
        super().moveEvent(event)
