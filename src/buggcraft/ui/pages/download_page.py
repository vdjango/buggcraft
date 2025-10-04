"""下载
"""

# StartGamePage 类
import os
import logging

from PySide6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout, QFrame, QStackedWidget
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QPixmap, QColor, QPainter
from core.launcher import MinecraftLibLauncher
from config.settings import get_settings_manager
from ui.pages.download import GamesPage, TasksPage


logger = logging.getLogger(__name__)


class DownloadPages(QWidget):
    """下载"""

    def __init__(self, parent, resource_path, cache_path):
        super().__init__(parent)
        self.parent = parent
        self.cache_path = cache_path
        self.resource_path = resource_path
        self.background_color = QColor(0, 0, 0, 0)  # 透明背景
        self.launcher: MinecraftLibLauncher = parent.launcher
        self.tab_names = ['游戏下载', '进行中']

        self.games_page = GamesPage(self)
        self.tasks_page = TasksPage(self)

        # 初始化设置管理器
        self.settings_manager = get_settings_manager()
        self.init_ui()

    def on_page_activate(self):
        """事件：页面被激活时"""
        print("页面被激活")
    
    def on_page_deactivate(self):
        """事件：页面被隐藏时"""
        print("页面被隐藏")
    
    def toggle_menu(self, menu_collapsed=False):
        """事件：左侧菜单折叠"""
        if menu_collapsed:
            self.tab_buttons_widget.hide()
        else:
            self.tab_buttons_widget.show()
        pass
    
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
        # self.tab_buttons_widget.setStyleSheet("background-color: #225500;")

        # 右侧堆叠内容
        self.version_stack = QStackedWidget()
        self.version_stack.setFixedWidth(926 - 178 - 62)
        self.version_stack.setContentsMargins(0, 0, 0, 0)
        # self.version_stack.setStyleSheet("background-color: #552299;")

        tab_container_layout.addWidget(self.tab_buttons_widget)
        tab_container_layout.addWidget(self.version_stack)
        
        self.version_stack.addWidget(self.games_page)
        self.version_stack.addWidget(self.tasks_page)

        main_layout.addWidget(self.tab_container)
    
    @property
    def signals(self):
        return self.games_page.signals

    def create_tab_buttons(self):
        """创建选项卡按钮区域"""
        tab_buttons_widget = QWidget()
        tab_buttons_widget.setFixedWidth(178 + 21)
        tab_buttons_widget.setContentsMargins(0, 0, 0, 0)   
        tab_buttons_layout = QVBoxLayout(tab_buttons_widget)
        tab_buttons_layout.setContentsMargins(0, 0, 21, 0)
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
            "游戏下载",
            self.on_download_clicked,
            size=(155, 44), font_size=10
        )
        tab_buttons_layout.addWidget(self.offline_tab_btn, 0, Qt.AlignCenter)
        
        # 正版选项卡按钮
        self.external_tab_btn = self.create_tab_button(
            "进行中",
            self.on_progress_clicked,
            size=(155, 44), font_size=10
        )
        tab_buttons_layout.addWidget(self.external_tab_btn, 0, Qt.AlignCenter)
        tab_buttons_layout.addStretch()
        
        # 设置初始状态：游戏下载默认选中
        self.update_button_style("游戏下载", False)
        self.update_button_style("进行中", True)
        
        return tab_buttons_widget

    def create_tab_button(self, text, click_handler, size=(155, 44), font_size=12):
        """创建选项卡按钮"""
        button = QLabel()
        button.mousePressEvent = lambda event: click_handler()
        button.setFixedSize(*size)
        button.setStyleSheet("background-color: transparent;")
        
        # 添加文本
        text_label = QLabel(text, button)
        text_label.setFont(QFont("Source Han Sans CN Normal", font_size, QFont.Weight.Bold))
        text_label.setAlignment(Qt.AlignCenter)  
        text_label.setStyleSheet("color: white; background-color: transparent;")
        text_label.setGeometry(0, 0, *size)   
        
        return button

    def on_progress_clicked(self):
        """进行中按钮点击事件"""
        self.update_button_style("游戏下载", True)
        self.update_button_style("进行中", False)
        self.switch_pages("进行中")

    def on_download_clicked(self):
        """游戏下载按钮点击事件"""
        self.update_button_style("游戏下载", False)
        self.update_button_style("进行中", True)
        self.switch_pages("游戏下载")

    def update_button_style(self, tab_name, is_active):
        """更新选项卡按钮样式"""
        if tab_name == "游戏下载":
            btn = self.external_tab_btn
        else:
            btn = self.offline_tab_btn
        
        active_image = os.path.join(self.resource_path, 'images', 'user', 'external_tab_btn_active.png')
        if is_active and os.path.exists(active_image):
            btn.setPixmap(QPixmap(active_image).scaled(155, 44, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
        else:
            btn.clear()
            btn.setStyleSheet("background-color: transparent;")

    def switch_pages(self, name):
        """切换标签页"""
        # 获取当前活动页面的索引
        current_index = self.version_stack.currentIndex()
        
        # 如果当前有活动页面，调用其失活方法
        if current_index >= 0:
            current_widget = self.version_stack.widget(current_index)
            if hasattr(current_widget, 'on_page_deactivate'):
                current_widget.on_page_deactivate()
        
        # 切换到新页面
        index = self.tab_names.index(name)
        self.version_stack.setCurrentIndex(index)
        
        # 调用新页面的激活方法
        new_widget = self.version_stack.widget(index)
        if hasattr(new_widget, 'on_page_activate'):
            new_widget.on_page_activate()

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
