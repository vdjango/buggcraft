"""版本管理
 - 版本列表
 - 版本设置
"""

# StartGamePage 类
import os
import logging

from PySide6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout, QFrame, QStackedWidget
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPixmap, QColor, QPainter

from config.settings import get_settings_manager
from ui.pages.version import VersionsPage, SettingsPage


logger = logging.getLogger(__name__)


class VersionsListPages(QWidget):
    """用户面板 - 可折叠"""

    def __init__(self, parent, resource_path, cache_path):
        super().__init__(parent)
        self.parent = parent
        self.cache_path = cache_path
        self.resource_path = resource_path
        self.background_color = QColor(0, 0, 0, 0)  # 透明背景
        
        self.tab_names = {
            '版本列表': 'Versions',
            '版本设置': 'Settings'
        }

        # 版本列表
        self.versions_page = VersionsPage(self.resource_path)

        # 初始化设置管理器
        self.settings_manager = get_settings_manager()
        self.init_ui()

    def init_ui(self):
        """初始化用户界面"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 创建选项卡容器
        self.tab_container = QWidget()
        tab_container_layout = QHBoxLayout(self.tab_container)
        tab_container_layout.setContentsMargins(15, 0, 15, 25)
        
        # 创建选项卡按钮区域
        self.tab_buttons_widget = self.create_tab_buttons()
        # self.tab_buttons_widget.setStyleSheet("background-color: #225500;")

        # 右侧堆叠内容
        self.version_stack = QStackedWidget()
        self.version_stack.setFixedWidth(926 - 178 - 62)
        self.version_stack.setContentsMargins(10, 10, 10, 10)
        # self.version_stack.setStyleSheet("background-color: #552299;")

        tab_container_layout.addWidget(self.tab_buttons_widget)
        tab_container_layout.addSpacing(22)
        tab_container_layout.addWidget(self.version_stack)
        
        # 版本列表/版本设置
        self.version_stack.addWidget(self.versions_page)

        main_layout.addWidget(self.tab_container)
    
    @property
    def signals(self):
        return self.versions_page.signals

    def create_tab_buttons(self):
        """创建选项卡按钮区域"""
        tab_buttons_widget = QWidget()
        tab_buttons_widget.setFixedWidth(178)
        tab_buttons_widget.setContentsMargins(0, 0, 0, 0)
        tab_buttons_layout = QVBoxLayout(tab_buttons_widget)
        tab_buttons_layout.setContentsMargins(0, 0, 0, 0)
        tab_buttons_layout.addSpacing(20)
        
        # 添加下划线（水平分隔线）
        shared_separator = QFrame()
        shared_separator.setFrameShape(QFrame.HLine)
        shared_separator.setStyleSheet("background-color: rgba(139, 133, 218, 1);")
        shared_separator.setFixedWidth(155)
        shared_separator.setFixedHeight(2)
        tab_buttons_layout.addWidget(shared_separator, 0, Qt.AlignCenter)
        tab_buttons_layout.addSpacing(10)

        # 离线选项卡按钮
        self.offline_tab_btn = self.create_tab_button(
            "版本列表",
            lambda: print('版本列表'),
            size=(155, 44), font_size=10
        )
        self.offline_tab_btn.setPixmap(QPixmap(os.path.join(self.resource_path, 'images', 'user', 'external_tab_btn_active.png')).scaled(155, 44, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
        tab_buttons_layout.addWidget(self.offline_tab_btn, 0, Qt.AlignCenter)
        
        tab_buttons_layout.addStretch()
        return tab_buttons_widget

    def create_tab_button(self, text, click_handler, size=(155, 44), font_size=12):
        """创建选项卡按钮"""
        button = QLabel()
        button.mousePressEvent = lambda event: click_handler()
        button.setFixedSize(*size)
        button.setStyleSheet("background-color: transparent;")
        
        # 添加文本
        text_label = QLabel(text, button)
        text_label.setFont(QFont("Source Han Sans CN Normal", font_size))
        text_label.setAlignment(Qt.AlignCenter)  
        text_label.setStyleSheet("color: white; background-color: transparent;")
        text_label.setGeometry(0, 0, *size)   
        
        return button

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
