"""版本管理
 - 版本列表
"""

import os
import logging

from PySide6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout, QStackedWidget, QLineEdit, QPushButton
)
from PySide6.QtCore import Qt, Signal, QObject, QMetaObject, Q_ARG, QMetaType
from PySide6.QtGui import QFont, QPixmap

from ui.pages.download.games_panel.games import GamesPanel
from ui.widgets.lazy import LazyGameLoader
from config.settings import get_settings_manager
from ui.dialog.VersionDeleteDialog import VersionDeleteDialog
from ui.widgets.collapse import CollapsePanel
from ui.widgets.ComboBox import QMComboBox
from ui.dialog.MinecraftInstallDialog import MinecraftInstallDialog
from core.minecraft_forge import CrossPlatformMinecraftInstaller, MirrorSource, InstallerCallback

logger = logging.getLogger(__name__)


from PySide6.QtCore import QThreadPool, QRunnable, Slot
import time


from PySide6.QtCore import QTimer
import time

from PySide6.QtCore import QThreadPool, QRunnable, Slot
from functools import wraps
import time


def run_in_thread(func):
    """真正的线程装饰器"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        # 获取实例（如果是方法）
        instance = args[0] if args else None
        
        class ThreadedTask(QRunnable):
            @Slot()
            def run(self):
                result = func(*args, **kwargs)
                
        # 提交到线程池
        task = ThreadedTask()
        QThreadPool.globalInstance().start(task)
    
    return wrapper


class MinecraftDownloadSignals(QObject):
    """游戏完成时传递信号"""
    download = Signal(str)   # 下载时的信号
    complete = Signal(str)   # 下载完成时的信号


class GamesPage(QWidget):
    """游戏下载"""

    update_signal = Signal()  # 游戏列表更新
    
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.resource_path = parent.resource_path
        
        # 初始化设置管理器
        self.settings_manager = get_settings_manager()
        
        # 创建安装器实例
        self.installer = CrossPlatformMinecraftInstaller(
            game_dir=self.settings_manager.get_setting('minecraft.directory.enable'),  # 使用默认Minecraft目录
            mirror=MirrorSource.MODRINTH,
            max_workers=15,
            callback=InstallerCallback()
        )
        # 游戏版本列表
        self.current_page = 0
        self.items_per_page = 20  # 每页显示的游戏数量
        self.loaded_data = []     # 已加载的游戏数据
        self.minecraft_versions = []
    
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
        
        # 创建内容切换器
        self.content_stack = QStackedWidget()
        self.content_stack.setContentsMargins(0, 0, 0, 0)
        self.content_stack.setStyleSheet("background-color: transparent;")
        
        # 为每个tab创建独立的内容组件
        self.games_content = GamesPanel(self)  # 游戏内容
        # self.mods_content = GamesPanel(self)    # 模组内容
        # self.resource_content = GamesPanel(self)  # 资源包内容
        # self.shader_content = GamesPanel(self)      # 光影包内容
        
        # # 添加到堆栈中
        self.content_stack.addWidget(self.games_content)    # 索引0：游戏
        # self.content_stack.addWidget(self.mods_content)     # 索引1：模组
        # self.content_stack.addWidget(self.resource_content) # 索引2：资源包
        # self.content_stack.addWidget(self.shader_content)   # 索引3：光影包
        
        # 默认显示游戏内容
        self.content_stack.setCurrentIndex(0)
        
        used_layout.addWidget(self.content_stack)
        main_layout.addWidget(content_container)
        
        self.gamed_version_combo.currentTextChanged.connect(
            lambda t: self.search(t)
        )
        
    def search(self, text):
        self.search_input.clear()
        self.games_content.filter_games(None, text)
        
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
        
        # 搜索输入框 - 替换原来的QLabel为QLineEdit
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText('请输入名称或关键词')
        self.search_input.setFont(QFont("Source Han Sans CN Normal", 10, QFont.Weight.Normal))
        self.search_input.setStyleSheet("""
            QLineEdit {
                color: rgba(255, 255, 255, 0.9); 
                background-color: transparent;
                border: none;
                padding: 0px 5px;
            }
            QLineEdit::placeholder {
                color: rgba(255, 255, 255, 0.7);
            }
        """)
        # 连接回车键事件到搜索功能
        self.search_input.returnPressed.connect(self.on_search_clicked)
        layout.addWidget(self.search_input, 1)
        
        # 搜索按钮 - 替换背景为Search.png图片
        self.search_button = QLabel('搜索')
        self.search_button.setFont(QFont("Source Han Sans CN Normal", 10, QFont.Weight.Bold))
        self.search_button.setFixedSize(78, 35)  # 调整为图片尺寸78x35
        self.search_button.setAlignment(Qt.AlignCenter)
        
        # 构建Search.png图片路径
        search_bg_path = os.path.join(self.resource_path, 'images', 'Install', 'Search.png').replace('\\', '/')
        print(f"搜索按钮背景图片路径: {search_bg_path}")
        
        self.search_button.setStyleSheet(f"""
            QLabel {{
                color: rgba(255, 255, 255, 0.9);
                background-image: url("{search_bg_path}");
                background-repeat: no-repeat;
                background-position: center;
                border: none;
            }}
            QLabel:hover {{
                opacity: 0.8;
            }}
            QLabel:pressed {{
                opacity: 0.6;
            }}
        """)
        self.search_button.setCursor(Qt.PointingHandCursor)
        
        # 添加搜索按钮点击事件
        self.search_button.mousePressEvent = lambda event: self.on_search_clicked()
        
        layout.addWidget(self.search_button)
        return container
    
    def on_search_clicked(self):
        """处理搜索按钮点击事件"""
        search_text = self.search_input.text().strip()
        print(f"搜索关键词: {search_text}")
        self.games_content.filter_games(search_text)

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
        
        # 根据点击的tab切换内容
        clicked_title = item.property("title")
        if clicked_title == "游戏":
            self.content_stack.setCurrentIndex(0)
        elif clicked_title == "模组":
            self.content_stack.setCurrentIndex(1)
        elif clicked_title == "资源包":
            self.content_stack.setCurrentIndex(2)
        elif clicked_title == "光影包":
            self.content_stack.setCurrentIndex(3)
