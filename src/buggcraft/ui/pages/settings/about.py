"""关于页面
 - 应用信息、鸣谢、依赖和法律声明
"""
import os
from typing import Any
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout, QScrollArea, QPushButton, QFrame
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QFont, QPixmap, QColor, QPainter, QIcon

from config.settings import get_settings_manager, set_conf_manager
from ui.widgets.collapse import CollapsePanel
from ui.widgets.radio import QMRadioButton, QMRadioGroup
from ui.widgets.ComboBox import QMComboBox


import logging
logger = logging.getLogger(__name__)


class AboutPage(QWidget):
    """关于页面"""

    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.disabled = True
        self.cache_path = parent.cache_path
        self.resource_path = parent.resource_path
        self.background_color = QColor(0, 0, 0, 0)  
        self.settings_manager = get_settings_manager()
        self.init_ui()

    def on_page_activate(self):
        """当页面被激活时调用"""
        print("About 页面被激活")
    
    def on_page_deactivate(self):
        """当页面被隐藏时调用"""
        print("About 页面被隐藏")
    
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
        
        # 左侧关于内容区域
        self.about_panel = self.create_about_panel()
        container_layout.addWidget(self.about_panel)

        main_layout.addWidget(content_container)

    def create_about_panel(self):
        """创建关于页面面板"""
        # 容器
        panel = QWidget()

        # 布局
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(20)

        # 第1组：关于
        about_section = self.create_about_section()
        layout.addWidget(about_section)
        
        # 第2组：鸣谢
        acknowledgements_section = self.create_acknowledgements_section()
        layout.addWidget(acknowledgements_section)

        # 第3组：依赖
        dependencies_section = self.create_dependencies_section()
        layout.addWidget(dependencies_section)

        # 第4组：法律声明
        legal_section = self.create_legal_section()
        layout.addWidget(legal_section)
        
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

    def create_section_title(self, title):
        """创建分组标题"""
        title_label = QLabel(title)
        title_label.setStyleSheet("""
            QLabel {
                color: #B0B0CC;
                font-size: 14px;
                font-weight: bold;
                padding: 10px 0px 5px 0px;
            }
        """)
        return title_label

    def create_list_item(self, icon_path=None, title="", subtitle="", has_external_link=True, has_divider=False):
        """创建列表项"""
        item_widget = QWidget()
        item_layout = QHBoxLayout(item_widget)
        item_layout.setContentsMargins(15, 12, 15, 12)
        item_layout.setSpacing(12)
        
        # 左侧图标 
        if icon_path:
            icon_label = QLabel()
            icon_label.setFixedSize(40, 40)
            
            # 加载图片
            full_icon_path = os.path.join(self.resource_path, "settings", icon_path)
            if os.path.exists(full_icon_path):
                pixmap = QPixmap(full_icon_path)
                scaled_pixmap = pixmap.scaled(40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                icon_label.setPixmap(scaled_pixmap)
            else:
                icon_label.setStyleSheet("""
                    QLabel {
                        background-color: #4A4A5A;
                        border-radius: 0px;
                    }
                """)
            item_layout.addWidget(icon_label)
        
        # 中间文本内容
        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)
        
        # 主标题
        title_label = QLabel(title)
        title_label.setStyleSheet("""
            QLabel {
                color: #E0E0E5;
                font-size: 14px;
                font-weight: 500;
            }
        """)
        text_layout.addWidget(title_label)
        
        # 副标题
        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setStyleSheet("""
                QLabel {
                    color: #A0A0B5;
                    font-size: 12px;
                }
            """)
            subtitle_label.setWordWrap(True)
            text_layout.addWidget(subtitle_label)
        
        item_layout.addLayout(text_layout)
        
        # 右侧外部链接图标
        if has_external_link:
            link_icon = QLabel()
            link_icon.setFixedSize(20, 20)
            link_icon.setAlignment(Qt.AlignCenter)
            
            # 加载分享图标
            share_icon_path = os.path.join(self.resource_path, "settings", "share.png")
            if os.path.exists(share_icon_path):
                pixmap = QPixmap(share_icon_path)
                scaled_pixmap = pixmap.scaled(20, 20, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                link_icon.setPixmap(scaled_pixmap)
            else:
                link_icon.setText("↗")
                link_icon.setStyleSheet("""
                    QLabel {
                        color: #E0E0E5;
                        font-size: 16px;
                        font-weight: bold;
                    }
                """)
            item_layout.addWidget(link_icon)
        
        # 设置整体样式
        item_widget.setStyleSheet("""
            QWidget {
                background-color: #313146;
                border-radius: 0px;
                border: none;
            }
            QWidget * {
                border-radius: 0px;
            }
        """)
        
        # 分割线
        if has_divider:
            container = QWidget()
            container_layout = QVBoxLayout(container)
            container_layout.setContentsMargins(0, 0, 0, 0)
            container_layout.setSpacing(8)
            
            container_layout.addWidget(item_widget)
            
            # 添加虚线分割线
            divider = QFrame()
            divider.setFrameShape(QFrame.HLine)
            divider.setStyleSheet("""
                QFrame {
                    color: #404050;
                    border: none;
                    border-top: 1px dashed #404050;
                    margin: 0px 15px;
                }
            """)
            container_layout.addWidget(divider)
            
            return container
        
        return item_widget

    def create_about_section(self):
        """创建关于分组"""
        section_widget = QWidget()
        section_layout = QVBoxLayout(section_widget)
        section_layout.setContentsMargins(0, 0, 0, 0)
        section_layout.setSpacing(8)
        
        # 分组标题
        title = self.create_section_title("关于")
        section_layout.addWidget(title)
        
        # 版本信息
        version_item = self.create_list_item(
            icon_path="About1.png",
            title="1.21.8",
            subtitle="最新正式版本，发布于2025/07/17 20:12",
            has_external_link=True
        )
        section_layout.addWidget(version_item)
        
        # 开发者信息
        developer_item = self.create_list_item(
            icon_path="About2.png",
            title="huanghongxun",
            subtitle="12isahdlaosd@ashjdhad",
            has_external_link=True
        )
        section_layout.addWidget(developer_item)
        
        return section_widget

    def create_acknowledgements_section(self):
        """创建鸣谢分组"""
        section_widget = QWidget()
        section_layout = QVBoxLayout(section_widget)
        section_layout.setContentsMargins(0, 0, 0, 0)
        section_layout.setSpacing(8)
        
        # 分组标题
        title = self.create_section_title("鸣谢")
        section_layout.addWidget(title)
        
        # 鸣谢项目
        acknowledgement_item = self.create_list_item(
            icon_path="About3.png",
            title="yushijinhun",
            subtitle="提供 authlib-injector 相关支持",
            has_external_link=True
        )
        section_layout.addWidget(acknowledgement_item)
        
        return section_widget

    def create_dependencies_section(self):
        """创建依赖分组"""
        section_widget = QWidget()
        section_layout = QVBoxLayout(section_widget)
        section_layout.setContentsMargins(0, 0, 0, 0)
        section_layout.setSpacing(8)
        
        # 分组标题
        title = self.create_section_title("依赖")
        section_layout.addWidget(title)
        
        # OpenJFX依赖
        openjfx_item = self.create_list_item(
            icon_path=None,  # 没有左侧图标
            title="OpenJFX",
            subtitle="Copyright © 2013, 2024, Oracle and/or its affiliates.\nLicensed under the GPL 2 with Classpath Exception.",
            has_external_link=True
        )
        section_layout.addWidget(openjfx_item)
        
        return section_widget

    def create_legal_section(self):
        """创建法律声明分组"""
        section_widget = QWidget()
        section_layout = QVBoxLayout(section_widget)
        section_layout.setContentsMargins(0, 0, 0, 0)
        section_layout.setSpacing(8)
        
        # 分组标题
        title = self.create_section_title("法律声明")
        section_layout.addWidget(title)
        
        # 版权声明
        copyright_item = self.create_list_item(
            icon_path=None,
            title="版权",
            subtitle="版权所有 2025asdasdasdasd",
            has_external_link=True,
            has_divider=True
        )
        section_layout.addWidget(copyright_item)
        
        # 用户协议
        agreement_item = self.create_list_item(
            icon_path=None,
            title="用户协议",
            subtitle="xxxxxxxxxxxxxxxxxxxx",
            has_external_link=True,
            has_divider=True
        )
        section_layout.addWidget(agreement_item)
        
        # 开源声明
        opensource_item = self.create_list_item(
            icon_path=None,
            title="开源",
            subtitle="xxxxxxxxxxxxxxxxxxxx",
            has_external_link=True
        )
        section_layout.addWidget(opensource_item)
        
        return section_widget

    def on_setting_changed(self, key, value):
        """设置变更回调函数"""
        logger.info(f"设置变更: {key} = {value}")
        self.settings_manager.set_setting(key, value)
