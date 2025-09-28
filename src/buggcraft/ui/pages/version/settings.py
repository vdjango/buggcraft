"""版本管理
 - 版本设置
"""
import os

from PySide6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout
)
from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtGui import QFont, QPixmap, QColor, QPainter

from config.settings import get_settings_manager
from ui.widgets.collapse import CollapsePanel
from ui.pages.version.memory_panel import MemorySettingsPanel
from ui.widgets.radio import QMRadioButton, QMRadioGroup


import logging
logger = logging.getLogger(__name__)


class SettingsPage(QWidget):
    """用户面板 - 可折叠"""

    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.cache_path = parent.cache_path
        self.resource_path = parent.resource_path
        self.background_color = QColor(0, 0, 0, 0)  # 透明背景
        
        self.available_java_versions = [
            {"version": "21.0.7", "path": "C:\\Program Files\\Java\\jdk-21.0.7"},
            {"version": "17.0.10", "path": "C:\\Program Files\\Java\\jdk-17.0.10"},
            {"version": "11.0.22", "path": "C:\\Program Files\\Java\\jdk-11.0.22"},
            {"version": "8.0.402", "path": "C:\\Program Files\\Java\\jdk-8.0.402"}
        ]

        # 初始化设置管理器
        self.settings_manager = get_settings_manager()
        self.init_ui()

    def init_ui(self):
        """初始化用户界面"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 创建主容器
        content_container = QWidget(self)
        content_container.setContentsMargins(0, 0, 0, 0)
        container_layout = QHBoxLayout(content_container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(10)
        
        # 设置区域
        # # 左侧游戏安装路径区域
        self.settings_panel = self.create_settings_panel()
        container_layout.addWidget(self.settings_panel)
        
        main_layout.addWidget(content_container)

    def create_settings_panel(self):
        # 容器
        panel = QWidget()
        
        # 布局
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        ###############
        ##  版本隔离   #
        panel_version_isolation = CollapsePanel(self, '版本隔离', '默认 (".minecraft/")', True)
        # 展开内容区域
        version_isolation = self.create_version_isolation()
        panel_version_isolation.set_content(version_isolation)
        layout.addWidget(panel_version_isolation)

        ###############
        ##  游戏Java  #
        panel_java_settings = CollapsePanel(self, '游戏Java', 'C:\\Program Files\\Java\\jdk-21.0.7')
        # 展开内容区域
        java_content = self.create_java_content()
        panel_java_settings.set_content(java_content)
        layout.addWidget(panel_java_settings)

        ##################
        ##  自动分配内存  #
        minecraft_free = MemorySettingsPanel(self)  # self.create_minecraft_free()
        layout.addWidget(minecraft_free)

        # 添加拉伸空间
        layout.addStretch(1)
        return panel

    def create_version_isolation(self):
        """创建 版本隔离 设置内容"""
        content = QWidget()
        content.setStyleSheet("background-color: transparent;")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # 创建按钮组
        self.button_group = QMRadioGroup()
        self.button_group.button_selected.connect(self.on_isolate_selected)

        # 默认选择选项
        default_button = QMRadioButton(
            self,
            '默认 (".minecraft/")',
            '(资源存放在 ".minecraft/")',
            data_property=False
        )
        layout.addWidget(default_button)
        self.button_group.add_button(default_button)

        # 版本独立选择选项
        isolate_button = QMRadioButton(
            self,
            "个版本独立",
            '(存放在 ".minecraft/versions/<版本名>/"，除 assets、libraries 外)',
            data_property=True,
        )
        layout.addWidget(isolate_button)
        self.button_group.add_button(isolate_button)

        # 设置默认选中
        _isolation = {
            False: default_button,
            True: isolate_button
        }.get(self.settings_manager.get_setting("minecraft.isolation", True))
        self.button_group.set_selected_button(_isolation)
        return content

    def create_java_content(self):
        """创建 Java 设置内容"""
        content = QWidget()
        content.setStyleSheet("background-color: transparent;")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        
        # 创建按钮组
        self.button_group = QMRadioGroup()
        self.button_group.button_selected.connect(self.on_java_selected)
        
        # 自动选择选项
        auto_button = QMRadioButton(
            self,
            "使用推荐的 Java 版本",
            "系统将自动选择最适合的 Java 版本"
        )
        layout.addWidget(auto_button)
        self.button_group.add_button(auto_button)
        
        # 版本选项
        for java in self.available_java_versions:
            version_button = QMRadioButton(
                self,
                java['version'],
                java['path']
            )
            layout.addWidget(version_button)
            self.button_group.add_button(version_button)
        
        # 自定义选项
        custom_button = QMRadioButton(
            self,
            "自定义 Java 路径",
            None,
            slot_desc=self.create_custom_java_button()
        )
        layout.addWidget(custom_button)
        self.button_group.add_button(custom_button)

        # 设置默认选中
        auto_button.set_selected(True)
        return content

    def create_custom_java_button(self):
        """创建自定义 Java 按钮"""
        # 容器
        container = QWidget()
        container.setStyleSheet('background-color: rgba(0, 0, 0, 0.3);')
        container.setFixedHeight(27)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 文件夹选择的路径容器
        text_container = QWidget()
        text_container.setStyleSheet('background-color: rgba(0, 0, 0, 0.3);')
        text_container.setFixedHeight(27)
        text_layout = QHBoxLayout(text_container)
        text_layout.setContentsMargins(5, 0, 5, 0)
        text_layout.setSpacing(5)

        title_label = QLabel('C:\\Program Files\\Java\\jdk-21.0.7')
        title_label.setFont(QFont("Source Han Sans CN", 11))
        title_label.setStyleSheet("color: rgba(255, 255, 255, 0.7); background-color: transparent;")
        title_label.setAlignment(Qt.AlignVCenter)  # 文本在标签内居中
        text_layout.addWidget(title_label)
        layout.addWidget(text_container, 1)
        
        # 文件夹图标
        folder_icon = QLabel()
        folder_icon.setFixedSize(25, 25)
        folder_icon.setAlignment(Qt.AlignCenter)
        folder_icon.setPixmap(QPixmap(
            os.path.join(self.resource_path, 'images', 'version', 'folder.png')
        ).scaled(12, 12, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        folder_icon.setStyleSheet('background-color: rgba(190, 183, 255, 0.19); border: 1px solid rgba(139, 133, 218, 1);')
        folder_icon.setCursor(Qt.PointingHandCursor)
        # folder_icon.mousePressEvent = self.browse_java_path
        layout.addWidget(folder_icon)
        
        return container

    def create_minecraft_free(self):
        """游戏内存"""
        content = QWidget()
        content.setStyleSheet("background-color: transparent;")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # 默认选择选项
        default_button = QMRadioButton(self, '自动分配内存', None)
        layout.addWidget(default_button)

        return content

    def on_isolate_selected(self, proprty):
        """处理自动选择标签点击事件"""
        print('处理自动选择标签点击事件', proprty)
        self.settings_manager.set_setting("minecraft.isolation", proprty)
        self.settings_manager.save_settings()

    def on_java_selected(self, proprty):
        """处理自动选择标签点击事件"""
        # print('处理自动选择标签点击事件', proprty)
        # self.settings_manager.set_setting("minecraft.isolation", proprty)
        # self.settings_manager.save_settings()

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
