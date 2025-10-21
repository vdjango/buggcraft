"""版本管理
 - 版本列表
"""

import os
import logging

from functools import wraps
from PySide6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout, QScrollArea, QStackedWidget, QLineEdit, QPushButton
)
from PySide6.QtCore import Qt, Signal, QObject, QThreadPool, QRunnable, Slot
from PySide6.QtGui import QFont, QPixmap

from ui.widgets.lazy import LazyGameLoader
from config.settings import get_settings_manager
from ui.dialog.VersionDeleteDialog import VersionDeleteDialog
from ui.widgets.collapse import CollapsePanel
from ui.widgets.ComboBox import QMComboBox
from ui.dialog.MinecraftInstallDialog import MinecraftInstallDialog
from core.minecraft_forge import CrossPlatformMinecraftInstaller, MirrorSource, InstallerCallback

logger = logging.getLogger(__name__)


def run_in_thread(func):
    """真正的线程装饰器"""
    @wraps(func)
    def wrapper(*args, **kwargs):

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


class GamesPanel(QWidget):
    """游戏下载"""

    update_signal = Signal()  # 游戏列表更新
    
    def __init__(self, parent):
        super().__init__(None)
        self._parent = parent
        self.resource_path = parent.resource_path
        
        # 初始化设置管理器
        self.settings_manager = get_settings_manager()
        self.install_dialog = MinecraftInstallDialog(self)
        
        # 创建安装器实例
        self.installer = CrossPlatformMinecraftInstaller(
            game_dir=self.settings_manager.get_setting('minecraft.directory.enable'),  # 使用默认Minecraft目录
            mirror=MirrorSource.MODRINTH,
            max_workers=15,
            callback=InstallerCallback()
        )
        self.minecraft_version_manifest_type_to_str = {
            "release": "正式版",
            "snapshot": "快照",
            "old_alpha": "旧版"
        }
        self.minecraft_version_manifest_type = {
            "正式版": "release",
            "快照": "snapshot",
            "旧版": "old_alpha"
        }
        self.filter_text = None  # 筛选版本
        self.filter_type = self.minecraft_version_manifest_type['正式版']  # 筛选版本
        self.minecraft_versions_cache = []
        self.minecraft_versions = []  # 已加载的游戏数据
        
        self.loaded_count = 0
        self.batch_size = 20  # 每次加载的项目数量
        self.is_loading = False
        
        self.init_ui()
        
        # 监听滚动事件
        self.games_panel.verticalScrollBar().valueChanged.connect(self.check_scroll_position)
        self.update_signal.connect(self.on_games_finished)
        
        self.get_games_version()

    def check_scroll_position(self):
        """检查滚动位置，决定是否加载更多"""
        if self.is_loading or self.loaded_count >= len(self.minecraft_versions):
            return
        
        scroll_bar = self.games_panel.verticalScrollBar()
        scroll_pos = scroll_bar.value()
        scroll_max = scroll_bar.maximum()
        
        # 当滚动到距离底部100像素以内时加载更多
        if scroll_pos >= scroll_max - 100:
            self.load_next_batch()
    
    def load_next_batch(self):
        """加载下一批游戏"""
        if self.is_loading or self.loaded_count >= len(self.minecraft_versions):
            return
        
        self.is_loading = True
        self._add_batch_items()
    
    def _add_batch_items(self):
        """实际添加批次项目"""
        start_idx = self.loaded_count
        end_idx = min(self.loaded_count + self.batch_size, len(self.minecraft_versions))
        # print('加载下一批游戏', start_idx, end_idx, len(self.minecraft_versions))
        
        for i in range(start_idx, end_idx):
            data = self.minecraft_versions[i]
            item = self.create_download_item(
                data["id"],
                f"{self.minecraft_version_manifest_type_to_str[data['type']]} | 发布时间：{data['releaseTime']}",
                data.get('is_selected', False)
            )
            self.layout_panel.insertWidget(self.layout_panel.count() - 1, item)
            self.layout_panel.insertSpacing(self.layout_panel.count() - 1, 10)
        
        self.loaded_count = end_idx
        self.is_loading = False
        # self.loading_indicator.setVisible(False)
        
        # 通知UI更新
        # self.items_added.emit(start_idx, end_idx)
        # self.loading_finished.emit()
    
    def on_items_added(self, start_idx, end_idx):
        """当新项目添加时调用"""
        # 可以更新状态或执行其他操作
        print(f"已加载项目 {start_idx} 到 {end_idx}")

    @run_in_thread
    def get_games_version(self):
        """在后台线程中获取游戏版本"""
        self.minecraft_versions = self.installer.get_available_versions()
        self.minecraft_versions_cache = self.minecraft_versions
        self.update_signal.emit()
    
    @Slot()
    def on_games_finished(self):
        """刷新游戏列表 - 使用懒加载"""
        self.filter_games(filter_type="正式版")

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
        self.games_panel = self.create_games_list()
        container_layout.addWidget(self.games_panel)
        main_layout.addWidget(content_container)
    
    def create_games_list(self):
        """创建右侧游戏列表"""
        panel = QWidget()
        panel.setContentsMargins(0, 0, 0, 0)
        panel.setStyleSheet("background-color: transparent;")
        
        self.layout_panel = QVBoxLayout(panel)
        self.layout_panel.setContentsMargins(0, 0, 0, 0)
        self.layout_panel.setSpacing(0)

        # 添加版本项
        for data in self.minecraft_versions:
            item = self.create_download_item(
                data["id"],
                f"{self.minecraft_version_manifest_type_to_str[data['type']]} | 发布时间：{data['releaseTime']}",
                data.get('is_selected', False)
            )
            self.layout_panel.addWidget(item)
            self.layout_panel.addSpacing(10)

        # 添加拉伸空间
        self.layout_panel.addStretch()
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
            os.path.join(self.resource_path, 'images', 'user', 'offline_login.png'),
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
        desc_label.setFont(QFont("Source Han Sans CN Normal", 9, QFont.Weight.Normal))
        desc_label.setStyleSheet("color: rgba(255, 255, 255, 0.7);")
        
        text_layout.addWidget(version_label, 0, Qt.AlignVCenter)
        text_layout.addWidget(desc_label, 0, Qt.AlignVCenter)
        
        layout.addWidget(text_widget)
        
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

    def on_version_clicked(self, item, event):
        """点击某版本事件"""
        # 更新所有版本项的选中状态
        print('property', item.property("version"), f"{item.property('description')}")
        self.install_dialog.set_version(item.property("version"), f"{item.property('description')}")
        self.install_dialog.exec()
        pass
    
    def filter_games(self, text=None, filter_type=None):
        """
        统一过滤方法：根据文本和类型过滤游戏
        
        Args:
            text: 搜索文本，用于过滤游戏ID
            filter_type: 过滤类型，如果为None则使用当前filter_type
        """
        # 重置为缓存数据
        self.minecraft_versions = self.minecraft_versions_cache
        filtered_data = self.minecraft_versions
        
        # 更新过滤条件
        if text is not None:
            self.filter_text = text if text else None
        
        if filter_type is not None:
            # 处理类型映射（保留原有逻辑）
            self.filter_type = self.minecraft_version_manifest_type.get(filter_type) if filter_type else None
        
        # 应用类型过滤
        if self.filter_type:
            filtered_data = [
                v for v in filtered_data 
                if self.filter_type.lower() in v["type"].lower()
            ]
        
        # 应用文本过滤
        if self.filter_text:
            filtered_data = [
                v for v in filtered_data 
                if self.filter_text.lower() in v["id"].lower()
            ]
        
        # 刷新数据
        self.minecraft_versions = filtered_data
        self.loaded_count = 0
        self.clear_games_list()
        self.load_next_batch()

    def clear_games_list(self):
        """清除现有的游戏版本列表"""
        layout = self.games_panel.widget().layout()
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
