# 设置页面

import os
from typing import Any

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QFrame, QPushButton, QStackedWidget, QLineEdit, QComboBox, QSlider,
    QRadioButton, QButtonGroup, QScrollArea, QFormLayout, QSpacerItem, QSizePolicy
)
from PySide6.QtGui import QFont, QPixmap, QPainter, QIcon
from PySide6.QtCore import Qt, Signal, QSize
from .base_page import BasePage
from utils.helpers import MemorySliderManager
from config.settings import get_settings_manager
from config.javafinder import JavaPathFinder
from core.visibility import VisibilitySettings
from ui.widgets.collapse import CollapsePanel
from ui.pages.settings import GeneralSettingsPages


import logging
logger = logging.getLogger(__name__)


class SettingsPage(BasePage):
    """设置页面 - 继承BasePage"""
    
    # 定义信号
    settings_changed = Signal(str, object)  # 设置改变信号，参数为设置键和值
    
    def __init__(self, parent=None, config_path=None, resource_path=None, scale_ratio=1.0, ):
        super().__init__(parent, config_path, resource_path, scale_ratio)
        self.cache_path = parent.cache_path
        self.resource_path = parent.resource_path
        self.settings_manager = get_settings_manager()  # 获取配置管理器
        
        # 通用设置
        self.general_page = GeneralSettingsPages(self)
        self.init_ui()

    def on_page_activate(self):
        """当页面被激活时调用"""
        print("设置页面被激活")
    
    def on_page_deactivate(self):
        """当页面被隐藏时调用"""
        print("设置页面被隐藏")

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
        self.settings_stack = QStackedWidget()
        self.settings_stack.setFixedWidth(926 - 178 - 62)
        self.settings_stack.setContentsMargins(0, 0, 0, 0)
        # self.settings_stack.setStyleSheet("background-color: #552299;")

        tab_container_layout.addWidget(self.tab_buttons_widget)
        tab_container_layout.addSpacing(22)
        tab_container_layout.addWidget(self.settings_stack)
        
        # 通用设置/全局设置/Java管理/关于
        self.settings_stack.addWidget(self.general_page)
        # self.settings_stack.addWidget(self.settings_page)

        main_layout.addWidget(self.tab_container)

    def create_tab_buttons(self):
        """创建选项卡按钮区域  """
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
        tab_buttons_layout.addSpacing(10)
        
        # 通用设置按钮
        self.general_tab_btn = self.create_tab_button(
            "通用设置",
            self.general_tab_btn_clicked,
            size=(155, 44), font_size=10
        )
        tab_buttons_layout.addWidget(self.general_tab_btn, 0, Qt.AlignCenter)
        
        # Java管理按钮
        self.java_tab_btn = self.create_tab_button(
            "Java管理",
            self.java_tab_btn_clicked,
            size=(155, 44), font_size=10
        )
        tab_buttons_layout.addWidget(self.java_tab_btn, 0, Qt.AlignCenter)
        
        # 下载按钮
        self.download_tab_btn = self.create_tab_button(
            "下载",
            self.download_tab_btn_clicked,
            size=(155, 44), font_size=10
        )
        tab_buttons_layout.addWidget(self.download_tab_btn, 0, Qt.AlignCenter)
        
        # 关于按钮
        self.about_tab_btn = self.create_tab_button(
            "关于",
            self.about_tab_btn_clicked,
            size=(155, 44), font_size=10
        )
        tab_buttons_layout.addWidget(self.about_tab_btn, 0, Qt.AlignCenter)
        tab_buttons_layout.addStretch()
        
        # 设置初始状态：通用设置默认选中
        self.update_tab_button_style("通用设置", True)
        return tab_buttons_widget

    def create_tab_button(self, text, click_handler, size=(155, 44), font_size=12):
        """创建选项卡按钮 """
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

    def update_tab_button_style(self, tab_name, is_active):
        """更新选项卡按钮样式 """
        if tab_name == "通用设置":
            btn = self.general_tab_btn
        elif tab_name == "Java管理":
            btn = self.java_tab_btn
        elif tab_name == "下载":
            btn = self.download_tab_btn
        elif tab_name == "关于":
            btn = self.about_tab_btn
        else:
            return
            
        active_image = os.path.join(self.resource_path, 'images', 'user', 'external_tab_btn_active.png')
        
        if is_active and os.path.exists(active_image):
            btn.setPixmap(QPixmap(active_image).scaled(155, 44, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
        else:
            btn.clear()
            btn.setStyleSheet("background-color: transparent;")

    def general_tab_btn_clicked(self):
        """通用设置按钮点击事件"""
        self.settings_stack.setCurrentIndex(0)
        self.update_tab_button_style("通用设置", True)
        self.update_tab_button_style("Java管理", False)
        self.update_tab_button_style("下载", False)
        self.update_tab_button_style("关于", False)

    def java_tab_btn_clicked(self):
        """Java管理按钮点击事件"""
        self.settings_stack.setCurrentIndex(1)
        self.update_tab_button_style("通用设置", False)
        self.update_tab_button_style("Java管理", True)
        self.update_tab_button_style("下载", False)
        self.update_tab_button_style("关于", False)

    def download_tab_btn_clicked(self):
        """下载按钮点击事件"""
        self.settings_stack.setCurrentIndex(2)
        self.update_tab_button_style("通用设置", False)
        self.update_tab_button_style("Java管理", False)
        self.update_tab_button_style("下载", True)
        self.update_tab_button_style("关于", False)

    def about_tab_btn_clicked(self):
        """关于按钮点击事件"""
        self.settings_stack.setCurrentIndex(3)
        self.update_tab_button_style("通用设置", False)
        self.update_tab_button_style("Java管理", False)
        self.update_tab_button_style("下载", False)
        self.update_tab_button_style("关于", True)

    def paintEvent(self, event):
        """重绘事件 - 绘制背景图片与主窗口渲染方式一致"""
        if self.bg_image:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)
            
            widget_width = self.width()
            widget_height = self.height()
            
            scale_x = widget_width / self.bg_image.width()
            scale_y = widget_height / self.bg_image.height()
            scale = min(scale_x, scale_y)   
            
            scaled_width = int(self.bg_image.width() * scale)
            scaled_height = int(self.bg_image.height() * scale)
            
            x = (widget_width - scaled_width) // 2
            y = (widget_height - scaled_height) // 2
            
            scaled_pixmap = self.bg_image.scaled(
                scaled_width, scaled_height,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            painter.drawPixmap(x, y, scaled_pixmap)
        super().paintEvent(event)
