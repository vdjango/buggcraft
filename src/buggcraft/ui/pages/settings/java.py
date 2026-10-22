"""Java管理页面
 - Java版本管理
"""
import os
from typing import Any
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout, QScrollArea, QPushButton, QFileDialog, QMessageBox
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QFont, QPixmap, QColor, QPainter, QIcon

from config.settings import get_settings_manager
from ui.widgets.collapse import CollapsePanel
from ui.widgets.radio import QMRadioButton, QMRadioGroup
from ui.widgets.ComboBox import QMComboBox
from ui.widgets.lable import SmartLabel
from config.javafinder import JavaPathFinder
from core.minecraft.version import open_folder

import logging
logger = logging.getLogger(__name__)


class JavaManagementPage(QWidget):
    """Java管理页面"""

    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.disabled = True
        self.cache_path = parent.cache_path
        self.resource_path = parent.resource_path
        self.background_color = QColor(0, 0, 0, 0)   

        self.settings_manager = get_settings_manager()
        """
        {
            "name": "JDK21.0.8",
            "arch": "x86-64",
            "vendor": "Microsoft",
            "path": "C:\\Program Files\\Microsoft\\jdk-21.0.8.9-hotspot\\bin\\java.exe"
        },
        """
        self.java_managers = []
        self.java_versions = self.settings_manager.get_setting('java.installations', []) or []
        for jav in self.java_versions:
            self.java_managers.append({
                "name": self.java_name_format(jav),
                "version": self.java_version_format(jav),
                "vendor": "OpenJDK" if 'openjdk' in str(jav[1]).lower() else "Java",
                "path": jav[0]
            })

        self.init_ui()

    def on_page_activate(self):
        """当页面被激活时调用"""
        self.refresh_list()
     
    def on_page_deactivate(self):
        """当页面被隐藏时调用"""
     
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
        
        # Java管理设置区域
        self.settings_panel = self.create_settings_panel()
        container_layout.addWidget(self.settings_panel)

        main_layout.addWidget(content_container)

    def create_settings_panel(self):
        """创建设置面板"""
        # 容器
        panel = QWidget()

        # 布局
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        # Java版本列表
        self.java_versions_panel = self.create_java_versions_panel()
        layout.addWidget(self.java_versions_panel, 1)
        
        # 添加拉伸空间
        layout.addStretch(1)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setStyleSheet("""
            QScrollArea {
                background-color: transparent;
                border: none;
            }
            
            QScrollArea > QWidget > QWidget {
                background-color: transparent;
            }
                                  
            QScrollBar:vertical {
                border: none;
                background: rgba(0, 0, 0, 0.2);
                width: 8px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: rgba(120, 89, 255, 0.7);
                border-radius: 4px;
                min-height: 30px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(120, 89, 255, 1.0);
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)
        scroll_area.setWidget(panel)
        return scroll_area

    def java_name_format(self, java):
        """
        获取Java 名称
        TODO: 需重构到Java列表获取方法，后期直接读取配置文件
        """
        r = str(java[1]).split(' ')[0]
        if r == 'openjdk':
            return 'OpenJDK'
        return r
    
    def java_version_format(self, java):
        """
        获取Java 版本号
        TODO: 需重构到Java列表获取方法，后期直接读取配置文件
        """
        v = [str(i) for i in java[2]]
        return '.'.join(v)
    
    def create_java_versions_panel(self):
        """创建Java版本列表面板"""
        content = QWidget()
        content.setStyleSheet("background-color: transparent;")
        layout = QVBoxLayout(content)
        self.java_list_layout = layout
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        for java_info in self.java_managers:
            java_item = self.create_java_item(java_info)
            layout.addWidget(java_item)

        # 创建按钮组（刷新、下载、添加）
        button_group = self.create_action_button_group()

        panel = CollapsePanel(
            self,
            'Java版本列表',
            f'已检测到 {len(self.java_managers)} 个Java版本',
            True,
            is_collaspe=False,
            custom_button=button_group,
            margins=[0, 0, 0, 0],
            content_bg_color = "rgba(190, 183, 255, 0.1)"
        )
        panel.set_content(content)
        return panel

    def create_java_item(self, java_info):
        """创建单个Java版本项"""
        item_widget = QWidget()
        item_widget.setStyleSheet("""
            QWidget {
                background-color: rgba(255, 255, 255, 0.1);
                border-radius: 0px;  
                padding: 5px;  
                margin: 0px;  
            }
        """)
        
        layout = QVBoxLayout(item_widget)
        layout.setContentsMargins(25, 5, 25, 5)  
        layout.setSpacing(3)   
        
        # 第一行：版本名称和操作按钮
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        
        # 版本名称
        name_label = QLabel(java_info["name"])
        name_label.setFont(QFont("Source Han Sans CN Normal", 10, QFont.Weight.Bold))
        name_label.setStyleSheet("""
            QLabel {
                color: rgba(255, 255, 255, 0.9);
                background-color: transparent;
            }
        """)
        header_layout.addWidget(name_label)
        
        # 架构和供应商信息
        info_label = QLabel(f"版本: {java_info['version']}    供应商: {java_info['vendor']}")
        info_label.setFont(QFont("Source Han Sans CN Normal", 8, QFont.Weight.Normal))
        info_label.setStyleSheet("""
            QLabel {
                color: rgba(255, 255, 255, 0.7);
                background-color: transparent;
            }
        """)
        header_layout.addWidget(info_label)
        
        header_layout.addStretch()
        
        # 操作按钮
        folder_btn = self.create_icon_button("folder.png")
        folder_btn.clicked.connect(lambda: self.on_open_folder_clicked(java_info["path"]))
        header_layout.addWidget(folder_btn)
        
        # 添加垂直分割线
        separator = QLabel()
        separator.setFixedSize(1, 20)
        separator.setStyleSheet("""
            QLabel {
                background-color: rgba(255, 255, 255, 0.3);
                border: none;
            }
        """)
        header_layout.addWidget(separator)
        
        delete_btn = self.create_icon_button("delete.png")
        delete_btn.setToolTip('从启动器列表移除，不删除磁盘中的 Java')
        delete_btn.clicked.connect(lambda: self.on_delete_clicked(java_info["path"]))
        header_layout.addWidget(delete_btn)
        
        layout.addLayout(header_layout)
        
        # 第二行：路径
        path_label = SmartLabel(java_info["path"])
        info_label.setFont(QFont("Source Han Sans CN Normal", 9, QFont.Weight.Normal))
        path_label.setStyleSheet("""
            QLabel {
                color: rgba(255, 255, 255, 0.6);
                background-color: transparent;
            }
        """)
        layout.addWidget(path_label)
        
        return item_widget

    def create_action_button_group(self):
        """创建操作按钮组（刷新、下载、添加）"""
        button_container = QWidget()
        button_container.setStyleSheet("background-color: transparent;")  # 设置容器背景透明
        button_layout = QHBoxLayout(button_container)
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(8)
        
        # 刷新按钮
        refresh_btn = self.create_action_button("刷新", "refresh.png")
        self.refresh_button = refresh_btn
        refresh_btn.clicked.connect(self.on_refresh_clicked)
        button_layout.addWidget(refresh_btn)
        
        # 下载按钮
        download_btn = self.create_action_button("下载", "download.png")
        download_btn.setToolTip('打开 Java 官方下载页面')
        download_btn.clicked.connect(self.on_download_clicked)
        button_layout.addWidget(download_btn)
        
        # 添加按钮
        add_btn = self.create_action_button("添加", "add.png")
        add_btn.clicked.connect(self.on_add_clicked)
        button_layout.addWidget(add_btn)
        
        return button_container

    def create_action_button(self, text, icon_name):
        """创建操作按钮"""
        button = QPushButton(text)
        button.setFixedSize(60, 30)
        button.setCursor(Qt.PointingHandCursor)
        button.setStyleSheet("""
            QPushButton {
                background-color: #413F6B;
                color: white;
                border: none;
                border-radius: 0px;
                font-size: 11px;
                font-weight: bold;
            }
        """)
        
        # 尝试加载图标，如果不存在则使用文本符号
        icon_path = os.path.join(self.resource_path, 'settings', icon_name)
        if os.path.exists(icon_path):
            icon = QIcon(icon_path)
            button.setIcon(icon)
            button.setIconSize(QSize(16, 16))
        else:
            # 如果图标不存在，使用文本符号作为备选
            if icon_name == "refresh.png":
                button.setText("🔄 " + text)
            elif icon_name == "download.png":
                button.setText("⬇ " + text)
            elif icon_name == "add.png":
                button.setText("+ " + text)
        
        return button

    def create_icon_button(self, icon_name):
        """创建图标按钮"""
        button = QPushButton()
        button.setFixedSize(30, 30)
        button.setCursor(Qt.PointingHandCursor)
        button.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: none;
                border-radius: 0px;
            }
        """)
        
        # 加载图标
        icon_path = os.path.join(self.resource_path, 'images', 'version', icon_name)
        if os.path.exists(icon_path):
            pixmap = QPixmap(icon_path)
            scaled_pixmap = pixmap.scaled(16, 16, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            icon = QIcon(scaled_pixmap)
            button.setIcon(icon)
            button.setIconSize(QSize(16, 16))
        
        return button

    def on_add_clicked(self):
        """处理添加按钮点击事件"""
        path, _ = QFileDialog.getOpenFileName(self, '选择 Java 可执行文件', '',
                                             'Java (java.exe javaw.exe java);;所有文件 (*)')
        if path:
            self.add_java(path)

    def add_java(self, path):
        path = os.path.realpath(path)
        if os.path.basename(path).lower() == 'javaw.exe':
            path = os.path.join(os.path.dirname(path), 'java.exe')
        raw, version = JavaPathFinder()._get_java_version(path)
        if not os.path.isfile(path) or not raw or not version or version == (0, 0, 0):
            QMessageBox.warning(self, '无法添加 Java', '所选文件无法执行或无法读取 Java 版本，请选择 bin 目录中的 java 可执行文件。')
            return False
        entries = self.settings_manager.get_setting('java.installations', []) or []
        entries = [entry for entry in entries if os.path.normcase(entry[0]) != os.path.normcase(path)]
        entries.append([path, raw, list(version)])
        self.settings_manager.set_setting('java.installations', entries)
        self.settings_manager.save_settings()
        self.refresh_list()
        return True

    def on_setting_changed(self, key, value):
        """设置改变事件处理"""
        self.settings_manager.set_setting(key, value)
        print(f"设置已更改: {key} = {value}")

    def on_refresh_clicked(self):
        """刷新按钮点击事件"""
        self.refresh_button.setEnabled(False)
        self.refresh_button.setText('搜索中')
        self.parent.parent.load_java_path(notify_missing=False)

    def on_download_clicked(self):
        """下载按钮点击事件"""
        self.parent.parent.on_java_download_signal()

    def on_open_folder_clicked(self, java_path):
        """打开文件夹按钮点击事件"""
        open_folder(os.path.dirname(java_path))

    def on_delete_clicked(self, java_path):
        """删除按钮点击事件"""
        entries = self.settings_manager.get_setting('java.installations', []) or []
        entries = [entry for entry in entries if os.path.normcase(entry[0]) != os.path.normcase(java_path)]
        self.settings_manager.set_setting('java.installations', entries)
        if self.settings_manager.get_setting('java.path') == java_path:
            self.settings_manager.set_setting('java.path', JavaPathFinder().recommend_best_java(entries))
            self.settings_manager.set_setting('java.name', '使用推荐的 Java 版本|系统将自动选择最适合的 Java 版本')
        self.settings_manager.save_settings()
        self.refresh_list()

    def refresh_list(self):
        self.java_versions = self.settings_manager.get_setting('java.installations', []) or []
        while self.java_list_layout.count():
            item = self.java_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for entry in self.java_versions:
            info = {
                'name': self.java_name_format(entry), 'version': self.java_version_format(entry),
                'vendor': 'OpenJDK' if 'openjdk' in str(entry[1]).lower() else 'Java', 'path': entry[0],
            }
            self.java_list_layout.addWidget(self.create_java_item(info))
        if not self.java_versions:
            empty = QLabel('未检测到 Java，可点击刷新或添加。')
            empty.setStyleSheet('color: #c9c4d6; padding: 12px;')
            self.java_list_layout.addWidget(empty)
        self.java_versions_panel.set_messages(f'已检测到 {len(self.java_versions)} 个 Java 版本')
        self.refresh_button.setEnabled(True)
        self.refresh_button.setText('刷新')

    def paintEvent(self, event):
        """重绘事件"""
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.background_color)

    def setBackgroundColor(self, color):
        """设置背景颜色"""
        self.background_color = color
        self.update()

    def resizeEvent(self, event):
        """窗口大小改变事件"""
        super().resizeEvent(event)

    def moveEvent(self, event):
        """窗口移动事件"""
        super().moveEvent(event)
