"""设置
 - 通用设置
"""
import os
from typing import Any
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout, QScrollArea, QPushButton
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QFont, QPixmap, QColor, QPainter, QIcon

from config.settings import get_settings_manager, set_conf_manager
from ui.widgets.ComboBox import QMComboBox
from ui.widgets.radio import QMRadioButton, QMRadioGroup
from ui.widgets.collapse import CollapsePanel
from ui.pages.settings.version_settings import GlobalVersionSettingsPage


import logging
logger = logging.getLogger(__name__)


class GeneralSettingsPages(QWidget):
    """通用设置"""

    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.disabled = True
        self.cache_path = parent.cache_path
        self.resource_path = parent.resource_path
        self.background_color = QColor(0, 0, 0, 0)  # 透明背景

        self.settings_manager = get_settings_manager()
        self.init_ui()

    def on_page_activate(self):
        """当页面被激活时调用"""
        # 启动器更新
        self.launcher_update_group.set_selected_button(self.setting_launcher_update_proprty.get(
            self.settings_manager.get_setting('settings.general.update', 'stable')
        ))
        # 文件下载缓存
        cache = self.settings_manager.get_setting("settings.general.download.cache", '~/.buggcraft/')
        self.launcher_cache_group.set_selected_button(self.launcher_cache_proprty.get(cache))
        self.launcher_cache.set_messages(f"缓存路径：{cache}")
        # 启动器语言
        language = self.settings_manager.get_setting("settings.general.language", "简体中文")
        index = self.launcher_language_combo.findText(language)
        if index >= 0:
            self.launcher_language_combo.setCurrentIndex(index)
        self.launcher_language.set_messages(language)
        # 下载源
        mirrors = self.settings_manager.get_setting("settings.general.mirrors", "自动选择下载源（自动选择速度快的源）")
        index = self.launcher_download_source_combo.findText(mirrors)
        if index >= 0:
            self.launcher_download_source_combo.setCurrentIndex(index)
        self.language_download_source.set_messages(mirrors)
        
        # 激活全局版本设置页面
        self.global_version_settings.on_page_activate()
        
        print("GeneralSettings 页面被激活")
    
    def on_page_deactivate(self):
        """当页面被隐藏时调用"""
        print("页面被隐藏")
    
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
        
        # 左侧全局设置区域
        self.settings_panel = self.create_settings_panel()
        container_layout.addWidget(self.settings_panel)

        main_layout.addWidget(content_container)

    def create_settings_panel(self):
        # 容器
        panel = QWidget()

        # 布局
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        # 启动器更新
        self.launcher_update = self.create_launcher_update()
        layout.addWidget(self.launcher_update, 1)
        
        # 文件下载缓存
        self.launcher_cache = self.create_launcher_cache()
        layout.addWidget(self.launcher_cache)

        # 启动器语言
        self.launcher_language = self.create_launcher_language()
        layout.addWidget(self.launcher_language)

        # 下载源
        self.language_download_source = self.create_launcher_download_source()
        layout.addWidget(self.language_download_source)

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

    def create_launcher_update(self):
        """创建 启动器更新 设置内容"""
        # version = self.settings_manager.get_setting('minecraft.version.enable')
        content = QWidget()
        content.setStyleSheet("background-color: transparent;")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        update_content = QWidget()
        update_content.setStyleSheet("background-color: transparent;")
        update_layout = QHBoxLayout(update_content)
        update_layout.setContentsMargins(0, 0, 0, 0)
        update_layout.setSpacing(10)
        self.launcher_update_group = QMRadioGroup()
        
        # 默认选择选项
        stable_button = QMRadioButton(
            self,
            f'稳定版',
            None,
            data_property='stable',
            text_max_widht=60,
            messages_max_widht=60
        )
        update_layout.addWidget(stable_button)
        self.launcher_update_group.add_button(stable_button)

        development_button = QMRadioButton(
            self,
            f'开发版',
            None,
            data_property='development',
            text_max_widht=60,
            messages_max_widht=60
        )
        update_layout.addWidget(development_button)
        update_layout.addStretch(1)
        layout.addWidget(update_content)
        self.launcher_update_group.add_button(development_button)
        
        update_label = QLabel("发现更新 最新版本为：3.6.17")
        update_label.setStyleSheet("""
            QLabel {
                color: #FFFFFF;
                font-size: 12px;
                font-weight: bold;
                background-color: transparent;
            }
        """)
        update_layout.addWidget(update_label)

        desc_content = QWidget()
        desc_content.setStyleSheet("background-color: transparent;")
        desc_layout = QHBoxLayout(desc_content)
        desc_layout.setContentsMargins(10, 0, 10, 0)
        desc_layout.setSpacing(10)
        
        desc_label = QLabel("开发版与预览版包含更多的功能以及错误修复，但也可能会包含其他的问题。")
        desc_label.setFont(QFont("Source Han Sans CN Normal", 10, QFont.Weight.Normal))
        desc_label.setStyleSheet("""
            QLabel {
                color: rgba(255, 255, 255, 0.6);
                background-color: transparent;
            }
        """)
        desc_layout.addWidget(desc_label)
        layout.addWidget(desc_content)
        
        # 设置默认选中
        self.setting_launcher_update_proprty = {
            development_button.data_property: development_button,
            stable_button.data_property: stable_button
        }
        
        self.launcher_update_group.set_selected_button(self.setting_launcher_update_proprty.get(
            self.settings_manager.get_setting('settings.general.update', 'stable')
        ))
        self.launcher_update_group.button_selected.connect(lambda prop: self.on_setting_changed("settings.general.update", prop))

        # 创建reload按钮
        reload_btn = self.create_reload_button()
        
        panel = CollapsePanel(self, f'启动器更新', '发现更新 最新版本为：3.6.17', True, is_collaspe=False, custom_button=reload_btn)
        panel.set_content(content)
        return panel
    
    def create_launcher_cache(self):
        """创建 文件缓存 设置内容"""
        content = QWidget()
        content.setStyleSheet("background-color: transparent;")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # 创建按钮组
        self.launcher_cache_group = QMRadioGroup()
        
        # 默认选择选项
        default_button = QMRadioButton(
            self,
            '默认',
            '("%APPDATA%/.buggcraft/" 或 "~/.buggcraft/")',
            data_property='~/.buggcraft/'
        )
        layout.addWidget(default_button)
        self.launcher_cache_group.add_button(default_button)
        # 当前路径
        launcher_button = QMRadioButton(
            self,
            '当前路径',
            '位于启动器路径下 (.buggcraft/")',
            data_property='.buggcraft/'
        )
        layout.addWidget(launcher_button)
        self.launcher_cache_group.add_button(launcher_button)

        # 自定义
        custom_button = QMRadioButton(
            self,
            "自定义",
            '(存放在 ".minecraft/versions/<版本名>/"，除 assets、libraries 外)',
            data_property='custom',
            text_max_widht=70,
            messages_max_widht=70,
            slot_desc=self.create_custom_folder()
        )
        layout.addWidget(custom_button)
        self.launcher_cache_group.add_button(custom_button)

        desc_label = QLabel("注：此操作需要重启(自动关闭)，并且配置文件不保留。当需要多启动器实例可选择")
        desc_label.setContentsMargins(10, 0, 10, 0)
        desc_label.setFont(QFont("Source Han Sans CN Normal", 10, QFont.Weight.Normal))
        desc_label.setStyleSheet("""
            QLabel {
                color: rgba(255, 255, 255, 0.6);
                background-color: transparent;
            }
        """)
        layout.addWidget(desc_label)
        
        # 设置默认选中
        self.launcher_cache_proprty = {
            default_button.data_property: default_button,
            launcher_button.data_property: launcher_button,
            custom_button.data_property: custom_button
        }
        self.launcher_cache_group.set_selected_button(
            self.launcher_cache_proprty.get(self.settings_manager.get_setting("settings.general.download.cache", '~/.buggcraft/'))
        )

        panel = CollapsePanel(
            self, '文件缓存路径',
            '缓存路径：{}'.format(
                self.settings_manager.get_setting("settings.general.download.cache", '~/.buggcraft/')
            ), False
        )
        panel.set_content(content)
        self.launcher_cache_group.button_selected.connect(
            lambda prop: self.on_setting_cache_changed(prop)
        )
        self.launcher_cache_group.button_selected.connect(lambda prop: panel.set_messages(f"缓存路径：{prop}"))
        return panel

    def create_launcher_language(self):
        """创建 启动器语言 设置内容"""
        content = QWidget()
        content.setStyleSheet("background-color: transparent;")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        
        self.launcher_language_combo = QMComboBox(self)
        self.launcher_language_combo.addItems([
            'English',
            '简体中文',
        ])
        layout.addWidget(self.launcher_language_combo)
        
        desc_label = QLabel("当前启动器语言并未实现，预计下个Beta版本实现")
        desc_label.setFont(QFont("Source Han Sans CN Normal", 10, QFont.Weight.Normal))
        desc_label.setStyleSheet("""
            QLabel {
                color: rgba(255, 255, 255, 0.6);
                background-color: transparent;
            }
        """)
        layout.addWidget(desc_label)
        
        # 信号和默认值
        self.launcher_language_combo.currentTextChanged.connect(
            lambda t: self.on_setting_changed("settings.general.language", t)
        )
        index = self.launcher_language_combo.findText(
            self.settings_manager.get_setting("settings.general.language", "简体中文")
        )
        if index >= 0:
            self.launcher_language_combo.setCurrentIndex(index)

        panel = CollapsePanel(
            self,
            f'启动器语言（重启生效）',
            self.settings_manager.get_setting("settings.general.language", "简体中文"),
            True
        )
        panel.set_content(content)
        self.launcher_language_combo.currentTextChanged.connect(
            lambda prop: panel.set_messages(prop)
        )
        return panel
    
    def create_launcher_download_source(self):
        """创建 下载源 设置内容"""
        content = QWidget()
        content.setStyleSheet("background-color: transparent;")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        
        self.launcher_download_source_combo = QMComboBox(self)
        self.launcher_download_source_combo.addItems([
            '自动选择下载源（自动选择速度快的源）',
            '官方',
            'BMCLAPI',
        ])
        layout.addWidget(self.launcher_download_source_combo)
        
        desc_label = QLabel("通过启动器安装新游戏或启动游戏文件缺失下载文件时所使用的下载地址被称之为下载源")
        desc_label.setFont(QFont("Source Han Sans CN Normal", 10, QFont.Weight.Normal))
        desc_label.setStyleSheet("""
            QLabel {
                color: rgba(255, 255, 255, 0.6);
                background-color: transparent;
            }
        """)
        layout.addWidget(desc_label)
        
        # 信号和默认值
        self.launcher_download_source_combo.currentTextChanged.connect(
            lambda t: self.on_setting_changed("settings.general.mirrors", t)
        )
        index = self.launcher_download_source_combo.findText(
            self.settings_manager.get_setting("settings.general.mirrors", "自动选择下载源（自动选择速度快的源）")
        )
        if index >= 0:
            self.launcher_download_source_combo.setCurrentIndex(index)

        panel = CollapsePanel(
            self,
            f'下载源',
            self.settings_manager.get_setting("settings.general.mirrors", "自动选择下载源（自动选择速度快的源）"),
            True
        )
        panel.set_content(content)
        self.launcher_download_source_combo.currentTextChanged.connect(
            lambda prop: panel.set_messages(prop)
        )
        return panel

    def create_custom_folder(self):
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
        title_label.setFont(QFont("Source Han Sans CN Normal", 11, QFont.Weight.Normal))
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

    def set_disabled(self, disabled):
        """设置页面禁用状态，设置后无法操作其他设置项"""
        self.disabled = disabled
        self.launcher_update.set_disabled(self.disabled)
        self.launcher_cache.set_disabled(self.disabled)
        self.launcher_language.set_disabled(self.disabled)
        self.language_download_source.set_disabled(self.disabled)
    
    def on_setting_cache_changed(self, value: str):
        """文件缓存设置"""
        if value == 'custom':
            logger.warning('此功能未实现')
            return
        import sys
        self.on_setting_changed("settings.general.download.cache", value)
        set_conf_manager(value)
        sys.exit(0)
    
    def on_setting_changed(self, key: str, value: Any):
        """处理设置改变，更新配置管理器并保存"""
        # 更新配置管理器
        self.settings_manager.set_setting(key, value)
        self.settings_manager.save_settings()

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

    def create_reload_button(self):
        """创建reload按钮"""
        reload_btn = QPushButton()
        reload_btn.setFixedSize(QSize(20, 20))
        
        # 加载reload图标
        reload_icon_path = os.path.join(self.resource_path, "settings", "reload.png")
        if os.path.exists(reload_icon_path):
            pixmap = QPixmap(reload_icon_path)
            # 缩放到20x20像素
            scaled_pixmap = pixmap.scaled(20, 20, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            reload_btn.setIcon(QIcon(scaled_pixmap))
            reload_btn.setIconSize(QSize(20, 20))
        
        # 设置按钮样式 - 透明背景，悬停时半透明灰色
        reload_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: none;
                border-radius: 10px;
            }
            QPushButton:hover {
                background-color: rgba(128, 128, 128, 0.3);
            }
        """)
        
        # 连接点击事件（可以在这里添加刷新逻辑）
        reload_btn.clicked.connect(self.on_reload_clicked)
        
        return reload_btn
    
    def on_reload_clicked(self):
        """reload按钮点击事件处理"""
        logger.info("Reload button clicked - 启动器更新刷新")
        # 这里可以添加具体的刷新逻辑

    def moveEvent(self, event):
        """重写 moveEvent 以跟踪位置变化"""
        super().moveEvent(event)
