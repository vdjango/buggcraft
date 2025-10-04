"""版本管理
 - 版本列表
"""

import os
import logging

from PySide6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout, QScrollArea
)
from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtGui import QFont, QPixmap

from config.settings import get_settings_manager
from ui.dialog.VersionDeleteDialog import VersionDeleteDialog
from ui.widgets.collapse import CollapsePanel
from ui.widgets.ComboBox import QMComboBox


logger = logging.getLogger(__name__)


class MinecraftDownloadSignals(QObject):
    """游戏完成时传递信号"""
    download = Signal(str)   # 下载时的信号
    complete = Signal(str)   # 下载完成时的信号


class TasksPage(QWidget):
    """游戏下载进行中"""

    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.resource_path = parent.resource_path
        
        self.signals = MinecraftDownloadSignals()
        self.version_delete_dialog = VersionDeleteDialog()

        self.menu_panel = [
            {
                'title': '游戏',
                'is_selected': True,
            },
            {
                'title': '模组',
                'is_selected': False,
            },
            {
                'title': '资源包',
                'is_selected': False,
            },
            {
                'title': '光影包',
                'is_selected': False,
            },
            
        ]
        # 初始化设置管理器
        self.settings_manager = get_settings_manager()
        self.init_ui()

    def on_page_activate(self):
        """当页面被激活时调用"""
        print("页面被激活")
    
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
        container_layout = QVBoxLayout(content_container)
        container_layout.setContentsMargins(15, 10, 15, 0)  # setContentsMargins(15, 10, 15, 10)
        container_layout.setSpacing(0)
        
        # 游戏header 菜单区域
        self.header_panel = self.create_header_panel()
        container_layout.addWidget(self.header_panel)
        container_layout.addSpacing(3)
        
        # 游戏区域
        used = QWidget()
        used.setContentsMargins(0, 0, 0, 0)
        used.setStyleSheet("background-color: transparent;")
        used_layout = QVBoxLayout(used)
        used_layout.setContentsMargins(0, 0, 0, 0)
        used_layout.setSpacing(2)
        
        # 功能面板
        header_used = self.create_header_used()  # 功能面板
        self.header_used_panel = CollapsePanel(
            self,
            None, None,
            margins=[0, 0, 0, 0],
            expanded=True,
            is_collaspe=False,
            content_bg_color = "rgba(190, 183, 255, 0.1)",
        )
        self.header_used_panel.set_header(header_used)
        self.header_used_panel.set_content(used)
        container_layout.addWidget(self.header_used_panel)
        
        # 游戏列表
        self.version_list_panel = self.create_games_list()
        
        used_layout.addWidget(self.version_list_panel)
        main_layout.addWidget(content_container)

    def create_header_panel(self):
        """创建顶部Tab"""
        # 容器
        panel = QWidget()
        panel.setContentsMargins(0, 0, 0, 0)
        panel.setStyleSheet("background-color: transparent;")
        
        # 布局
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 菜单Tabs
        tabs = QWidget()
        tabs.setContentsMargins(0, 0, 0, 0)
        tabs.setStyleSheet("background-color: transparent;")
        tabs_layout = QHBoxLayout(tabs)
        tabs_layout.setContentsMargins(0, 0, 0, 0)
        tabs_layout.setSpacing(0)
        
        self.header_items = []
        for data in self.menu_panel:
            item = self.create_menu_item(
                data["is_selected"],
                data["title"]
            )
            self.header_items.append(item)
            tabs_layout.addWidget(item)
        
        tabs_layout.addStretch(1)
        layout.addWidget(tabs)
        # layout.setSpacing(3)
        
        return panel

    def create_header_used(self):
        """创建Header功能面板"""
        # 容器
        panel = QWidget()
        panel.setContentsMargins(0, 0, 0, 0)
        panel.setStyleSheet("background-color: transparent;")
        
        # 布局
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(0)
        
        custom_search = self.create_custom_search()
        layout.addWidget(custom_search)
        layout.addSpacing(50)
        
        # 版本
        lable = QLabel('版本：')
        lable.setFont(QFont("Source Han Sans CN Normal", 10, QFont.Weight.Bold))
        lable.setAlignment(Qt.AlignCenter)
        lable.setStyleSheet("color: rgba(255, 255, 255, 0.8);")
        layout.addWidget(lable)
        
        self.gamed_version_combo = QMComboBox(self, height=25)
        self.gamed_version_combo.setFixedHeight(35)
        self.gamed_version_combo.setFixedWidth(200)
        self.gamed_version_combo.addItems([
            '正式版',
            '快照',
            '旧版'
        ])
        # self.gamed_version_combo.currentTextChanged.connect(
        #     lambda t: self.on_setting_changed("launcher.visibility", t)
        # )
        self.gamed_version_combo.setCurrentIndex(0)
        layout.addWidget(self.gamed_version_combo)
    
        return panel
    
    def create_custom_search(self):
        """创建自定义 Input"""
        # 容器
        container = QWidget()
        container.setStyleSheet('background-color: rgba(0, 0, 0, 0.3);')
        container.setFixedHeight(35)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 搜索图标
        search_icon = QLabel()
        # search_icon.setFixedSize(25, 25)
        search_icon.setAlignment(Qt.AlignCenter)
        search_icon.setContentsMargins(10, 0, 8, 0)
        search_icon.setPixmap(QPixmap(
            os.path.join(self.resource_path, 'images', 'search.png')
        ).scaled(12, 12, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        search_icon.setStyleSheet("background-color: transparent;")
        layout.addWidget(search_icon)
        
        # 搜索提示信息
        title_label = QLabel('请输入名称或关键词')
        title_label.setFont(QFont("Source Han Sans CN Normal", 10, QFont.Weight.Normal))
        title_label.setStyleSheet("color: rgba(255, 255, 255, 0.7); background-color: transparent;")
        title_label.setAlignment(Qt.AlignVCenter)  # 文本在标签内居中
        layout.addWidget(title_label, 1)
        
        # 搜索按钮
        search = QLabel('搜索')
        search.setFont(QFont("Source Han Sans CN Normal", 10, QFont.Weight.Bold))
        search.setFixedSize(80, 35)
        search.setAlignment(Qt.AlignCenter)
        search.setStyleSheet("color: rgba(255, 255, 255, 0.8); background-color: rgba(120, 89, 255, 0.8);")
        search.setCursor(Qt.PointingHandCursor)
        layout.addWidget(search)
        return container
    
    def create_menu_item(self, is_selected, title):
        """创建Tab项"""
        # 容器
        item = QWidget()
        item.setContentsMargins(0, 0, 0, 0)
        item.setStyleSheet("background-color: transparent;")
        item.setFixedSize(60, 40)
        
        layout = QVBoxLayout(item)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(0)
        # 存储数据
        item.setProperty("is_selected", is_selected)
        item.setProperty("title", title)

        title_label = QLabel(title)
        title_label.setFont(QFont("Source Han Sans CN Normal", 10, QFont.Weight.Bold))
        title_label.setStyleSheet("color: #f2f2f2; border-bottom: none;background-color: transparent;")
        layout.addWidget(title_label, 0, Qt.AlignCenter)
        
        # 设置样式
        if is_selected:
            item.setStyleSheet('color: rgba(120, 89, 255, 1); border-bottom: 2px solid rgba(120, 89, 255, 1);')
        else:
            item.setStyleSheet('color: #f2f2f2; border-bottom: none;')
        
        # 添加目录项点击事件
        item.mousePressEvent = lambda event: self.on_tabs_clicked(item, event)
        item.setCursor(Qt.PointingHandCursor)

        return item

    def create_games_list(self):
        """创建右侧游戏列表"""
        panel = QWidget()
        panel.setContentsMargins(0, 0, 0, 0)
        panel.setStyleSheet("background-color: transparent;")
        
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 如果找到选中的目录，加载该目录的版本数据
        version_data = [
            {
                'name': '1.21.9',
                'desc': '描述信息12343211'
            },{
                'name': '1.21.9',
                'desc': '描述信息12343211'
            },{
                'name': '1.21.9',
                'desc': '描述信息12343211'
            },{
                'name': '1.21.9',
                'desc': '描述信息12343211'
            },{
                'name': '1.21.9',
                'desc': '描述信息12343211'
            },{
                'name': '1.21.9',
                'desc': '描述信息12343211'
            },{
                'name': '1.21.9',
                'desc': '描述信息12343211'
            },{
                'name': '1.21.9',
                'desc': '描述信息12343211'
            },{
                'name': '1.21.9',
                'desc': '描述信息12343211'
            },{
                'name': '1.21.9',
                'desc': '描述信息12343211'
            },{
                'name': '1.21.9',
                'desc': '描述信息12343211'
            },{
                'name': '1.21.9',
                'desc': '描述信息12343211'
            },{
                'name': '1.21.9',
                'desc': '描述信息12343211'
            },{
                'name': '1.21.9',
                'desc': '描述信息12343211'
            },{
                'name': '1.21.9',
                'desc': '描述信息12343211'
            },{
                'name': '1.21.9',
                'desc': '描述信息12343211'
            },{
                'name': '1.21.9',
                'desc': '描述信息12343211'
            },{
                'name': '1.21.9',
                'desc': '描述信息12343211'
            },{
                'name': '1.21.9',
                'desc': '描述信息12343211'
            },
        ]
        
        # 添加版本项
        for data in version_data:
            item = self.create_download_item(
                data["name"],
                data["desc"],
                data.get('is_selected', False)
            )
            layout.addWidget(item)
            layout.addSpacing(10)

        # 添加拉伸空间
        layout.addStretch()
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setStyleSheet("""
            QScrollArea {
                background-color: transparent;
                border: none;
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

    def create_download_item(self, version, description, is_selected=False):
        """创建版本项"""
        item = QWidget()
        item.setStyleSheet('background-color: rgba(190, 183, 255, 0.1);')
        item.setFixedHeight(70)
        
        # 存储数据
        item.setProperty("version", version)
        item.setProperty("description", description)
        item.setProperty("is_selected", is_selected)

        layout = QHBoxLayout(item)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 选中图标
        icon_name = "selected.png" if is_selected else "not-selected.png"
        select_icon = self.create_icon_label(
            os.path.join(self.resource_path, 'images', 'version', icon_name),
            size=(30, 30)
        )
        layout.addSpacing(15)
        layout.addWidget(select_icon)
        layout.addSpacing(15)
        
        # 文本区域
        text_widget = QWidget()
        text_widget.setStyleSheet("background-color: transparent;")
        text_layout = QVBoxLayout(text_widget)
        text_layout.setContentsMargins(0, 14, 0, 14)
        text_layout.setSpacing(5)
        
        version_label = QLabel(f'版本号：{version}')
        version_label.setFont(QFont("Source Han Sans CN Normal", 10, QFont.Weight.Bold))
        version_label.setStyleSheet("color: #f2f2f2;")
        
        desc_label = QLabel(description)
        desc_label.setMaximumWidth(200)
        desc_label.setFont(QFont("Source Han Sans CN Normal", 9, QFont.Weight.Normal))
        desc_label.setStyleSheet("color: rgba(255, 255, 255, 0.7);")
        
        text_layout.addWidget(version_label, 0, Qt.AlignVCenter)
        text_layout.addWidget(desc_label, 0, Qt.AlignVCenter)
        
        layout.addWidget(text_widget)
        # layout.addStretch(1)
        
        # 添加版本项点击事件
        item.mousePressEvent = lambda event: self.on_version_clicked(item, event)
        item.setCursor(Qt.PointingHandCursor)

        return item

    def create_icon_label(self, icon_path, size=(30, 30), cursor=None):
        """创建图标标签"""
        label = QLabel()
        label.setFixedSize(size[0] + 1, size[1] + 1)
        label.setPixmap(QPixmap(icon_path).scaled(
            size[0], size[1], 
            Qt.IgnoreAspectRatio, 
            Qt.SmoothTransformation
        ))
        
        if cursor:
            label.setCursor(cursor)
        label.setStyleSheet("background-color: transparent; border: none;")
        return label

    def on_tabs_clicked(self, item, event):
        """处理目录项点击事件 - 更新配置文件并刷新版本列表"""
        # 更新所有目录项的选中状态
        for tab in self.header_items:
            is_selected = tab == item
            tab.setProperty("is_selected", is_selected)
            
            # 更新样式
            if is_selected:
                tab.setStyleSheet('color: rgba(120, 89, 255, 1); border-bottom: 2px solid rgba(120, 89, 255, 1);')
            else:
                tab.setStyleSheet('color: #f2f2f2; border-bottom: none;')

    def on_version_clicked(self, item, event):
        """点击某版本事件"""
        # 更新所有版本项的选中状态
        pass
    