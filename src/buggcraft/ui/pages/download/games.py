"""版本管理
 - 版本列表
"""

import os
import logging

from PySide6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout, QScrollArea, QStackedWidget, QLineEdit
)
from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtGui import QFont, QPixmap

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
                try:
                    result = func(*args, **kwargs)
                    if instance and hasattr(instance, 'on_thread_result'):
                        instance.on_thread_result(result)
                except Exception as e:
                    if instance and hasattr(instance, 'on_thread_error'):
                        instance.on_thread_error(str(e))
        
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
        
        self.update_signal.connect(self.on_games_finished)
        # 初始化设置管理器
        self.settings_manager = get_settings_manager()
        
        self.signals = MinecraftDownloadSignals()
        self.version_delete_dialog = VersionDeleteDialog()
        self.install_dialog = MinecraftInstallDialog(self)
        # 创建线程池并执行任务
        self.thread_pool = QThreadPool.globalInstance()
        # 创建安装器实例
        self.installer = CrossPlatformMinecraftInstaller(
            game_dir=self.settings_manager.get_setting('minecraft.directory.enable'),  # 使用默认Minecraft目录
            mirror=MirrorSource.BMCLAPI,
            max_workers=15,
            callback=InstallerCallback()
        )
        # 游戏版本列表
        self.minecraft_versions = [
            {
                "id": "1.4.1",
                "type": "snapshot",
                "url": "https://piston-meta.mojang.com/v1/packages/14c3ba517b5baabdfc61b60eb49d9aa7da012906/1.4.1.json",
                "time": "2022-03-10T09:51:38+00:00",
                "releaseTime": "2012-11-22T22:00:00+00:00",
                "sha1": "14c3ba517b5baabdfc61b60eb49d9aa7da012906",
                "complianceLevel": 0
            },
            {
                "id": "1.4",
                "type": "snapshot",
                "url": "https://piston-meta.mojang.com/v1/packages/d979a4671611bf8704c0a2a0cf09964ca25eefd7/1.4.json",
                "time": "2022-03-10T09:51:38+00:00",
                "releaseTime": "2012-11-18T22:00:00+00:00",
                "sha1": "d979a4671611bf8704c0a2a0cf09964ca25eefd7",
                "complianceLevel": 0
            },
            {
                "id": "1.3.2",
                "type": "release",
                "url": "https://piston-meta.mojang.com/v1/packages/598eedd6f67db4aefbae6ed119029e3d7373ecf5/1.3.2.json",
                "time": "2022-03-10T09:51:38+00:00",
                "releaseTime": "2012-08-15T22:00:00+00:00",
                "sha1": "598eedd6f67db4aefbae6ed119029e3d7373ecf5",
                "complianceLevel": 0
            },
            {
                "id": "1.3.1",
                "type": "release",
                "url": "https://piston-meta.mojang.com/v1/packages/637aa8466c4dac462b88682caaf753290f37798f/1.3.1.json",
                "time": "2022-03-10T09:51:38+00:00",
                "releaseTime": "2012-07-31T22:00:00+00:00",
                "sha1": "637aa8466c4dac462b88682caaf753290f37798f",
                "complianceLevel": 0
            },
            {
                "id": "1.3",
                "type": "snapshot",
                "url": "https://piston-meta.mojang.com/v1/packages/b384219c6d4879e56b92eea01a0d986e20d55dea/1.3.json",
                "time": "2022-03-10T09:51:38+00:00",
                "releaseTime": "2012-07-25T22:00:00+00:00",
                "sha1": "b384219c6d4879e56b92eea01a0d986e20d55dea",
                "complianceLevel": 0
            },
            {
                "id": "1.2.5",
                "type": "release",
                "url": "https://piston-meta.mojang.com/v1/packages/5158765caf1ca14958cb6c45d52c8e09ed9b046c/1.2.5.json",
                "time": "2022-03-10T09:51:38+00:00",
                "releaseTime": "2012-03-29T22:00:00+00:00",
                "sha1": "5158765caf1ca14958cb6c45d52c8e09ed9b046c",
                "complianceLevel": 0
            },
            {
                "id": "1.2.4",
                "type": "release",
                "url": "https://piston-meta.mojang.com/v1/packages/69a67fcf11ed1298c6b43a00d64461908a318749/1.2.4.json",
                "time": "2022-03-10T09:51:38+00:00",
                "releaseTime": "2012-03-21T22:00:00+00:00",
                "sha1": "69a67fcf11ed1298c6b43a00d64461908a318749",
                "complianceLevel": 0
            },
            {
                "id": "1.2.3",
                "type": "release",
                "url": "https://piston-meta.mojang.com/v1/packages/2f7eaec33e3017a413c677eefa59df2e5919e536/1.2.3.json",
                "time": "2022-03-10T09:51:38+00:00",
                "releaseTime": "2012-03-01T22:00:00+00:00",
                "sha1": "2f7eaec33e3017a413c677eefa59df2e5919e536",
                "complianceLevel": 0
            },
            {
                "id": "1.2.2",
                "type": "release",
                "url": "https://piston-meta.mojang.com/v1/packages/4e2e449ba0b8b5da7055f0decea1a3257b282f17/1.2.2.json",
                "time": "2022-03-10T09:51:38+00:00",
                "releaseTime": "2012-02-29T22:00:01+00:00",
                "sha1": "4e2e449ba0b8b5da7055f0decea1a3257b282f17",
                "complianceLevel": 0
            },
            {
                "id": "1.2.1",
                "type": "release",
                "url": "https://piston-meta.mojang.com/v1/packages/1a45c035ebb969dbac4e0c39582e974ad7f74a9e/1.2.1.json",
                "time": "2022-03-10T09:51:38+00:00",
                "releaseTime": "2012-02-29T22:00:00+00:00",
                "sha1": "1a45c035ebb969dbac4e0c39582e974ad7f74a9e",
                "complianceLevel": 0
            },
            {
                "id": "1.1",
                "type": "release",
                "url": "https://piston-meta.mojang.com/v1/packages/c0cb9368dbdbb1e8dbcb9363a28d8da74cf6fc5e/1.1.json",
                "time": "2022-03-10T09:51:38+00:00",
                "releaseTime": "2012-01-11T22:00:00+00:00",
                "sha1": "c0cb9368dbdbb1e8dbcb9363a28d8da74cf6fc5e",
                "complianceLevel": 0
            },
            {
                "id": "1.0",
                "type": "release",
                "url": "https://piston-meta.mojang.com/v1/packages/75062586b830dd5160f13f1c9130eb365e01f1b9/1.0.json",
                "time": "2022-03-10T09:51:38+00:00",
                "releaseTime": "2011-11-17T22:00:00+00:00",
                "sha1": "75062586b830dd5160f13f1c9130eb365e01f1b9",
                "complianceLevel": 0
            }
        ]
        # self.minecraft_versions = []
        # 创建安装器实例
        # self.optifine_installer = OptiFineInstaller(minecraft_dir)
    
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
        # self.on_page_activate()  # 加载游戏版本列表数据

    @run_in_thread
    def get_games_version(self):
        import json
        self.minecraft_versions = self.installer.get_available_versions()
        print(json.dumps(self.minecraft_versions, indent=2))
        self.update_signal.emit()
    
    def on_page_activate(self):
        """当页面被激活时调用"""
        import json
        print("页面被激活")
        self.get_games_version()
    
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
        self.games_content = self.create_games_list()  # 游戏内容
        self.mods_content = self.create_mods_list()    # 模组内容
        self.resource_content = self.create_resource_list()  # 资源包内容
        self.shader_content = self.create_shader_list()      # 光影包内容
        
        # 添加到堆栈中
        self.content_stack.addWidget(self.games_content)    # 索引0：游戏
        self.content_stack.addWidget(self.mods_content)     # 索引1：模组
        self.content_stack.addWidget(self.resource_content) # 索引2：资源包
        self.content_stack.addWidget(self.shader_content)   # 索引3：光影包
        
        # 默认显示游戏内容
        self.content_stack.setCurrentIndex(0)
        
        used_layout.addWidget(self.content_stack)
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
        if search_text:
            print(f"搜索关键词: {search_text}")
            # TODO: 在这里实现实际的搜索逻辑
            # 可以根据search_text过滤游戏版本列表
        else:
            print("请输入搜索关键词")

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
        
        # 添加版本项
        for data in self.minecraft_versions:
            item = self.create_download_item(
                data["id"],
                f"{data['type']} {data['releaseTime']}",
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

    def clear_games_list(self):
        """清除现有的游戏版本列表"""
        layout = self.version_list_panel.widget().layout()
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
    
    def add_games_list(self):
        """添加游戏版本"""
        # 添加版本项
        for data in self.minecraft_versions:
            item = self.create_download_item(
                data["id"],
                f"{data['type']} {data['releaseTime']}",
                data.get('is_selected', False)
            )
            self.version_list_panel.widget().layout().addWidget(item)
            self.version_list_panel.widget().layout().addSpacing(10)
            
    def on_games_finished(self):
        """刷新游戏列表"""
        self.clear_games_list()
        self.add_games_list()
    
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

    def on_version_clicked(self, item, event):
        """点击某版本事件"""
        # 更新所有版本项的选中状态
        print('property', item.property("version"), f"{item.property('description')}")
        self.install_dialog.set_version(item.property("version"), f"{item.property('description')}")
        self.install_dialog.exec()
        pass

    def create_mods_list(self):
        """创建模组列表内容（暂时复制游戏列表结构）"""
        panel = QWidget()
        panel.setContentsMargins(0, 0, 0, 0)
        panel.setStyleSheet("background-color: transparent;")
        
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 添加版本项 
        for data in self.minecraft_versions:
            item = self.create_download_item(
                data["id"],
                f"模组 {data['type']} {data['releaseTime']}",
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

    def create_resource_list(self):
        """创建资源包列表内容（暂时复制游戏列表结构）"""
        panel = QWidget()
        panel.setContentsMargins(0, 0, 0, 0)
        panel.setStyleSheet("background-color: transparent;")
        
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 添加版本项 
        for data in self.minecraft_versions:
            item = self.create_download_item(
                data["id"],
                f"资源包 {data['type']} {data['releaseTime']}",
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

    def create_shader_list(self):
        """创建光影包列表内容（暂时复制游戏列表结构）"""
        panel = QWidget()
        panel.setContentsMargins(0, 0, 0, 0)
        panel.setStyleSheet("background-color: transparent;")
        
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 添加版本项 
        for data in self.minecraft_versions:
            item = self.create_download_item(
                data["id"],
                f"光影包 {data['type']} {data['releaseTime']}",
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
    