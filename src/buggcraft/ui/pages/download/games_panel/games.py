"""版本管理
 - 版本列表
"""

import os
import logging
import json
import threading
from pathlib import Path

from functools import wraps
from PySide6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout, QScrollArea, QStackedWidget, QLineEdit, QPushButton
)
from PySide6.QtCore import Qt, Signal, QObject, QThreadPool, QRunnable, Slot
from PySide6.QtGui import QFont, QPixmap
from ui.fonts import system_font

from ui.widgets.lazy import LazyGameLoader
from config.settings import get_settings_manager
from ui.dialog.VersionDeleteDialog import VersionDeleteDialog
from ui.widgets.collapse import CollapsePanel
from ui.widgets.ComboBox import QMComboBox
from ui.dialog.MinecraftInstallDialog import MinecraftInstallDialog
from core.minecraft_forge import CrossPlatformMinecraftInstaller, MirrorSource, InstallerCallback
from core.downloads import MinecraftDownloader, DownloadCancelled

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
        args[0].catalog_pool.start(task)
    
    return wrapper


class MinecraftDownloadSignals(QObject):
    """游戏完成时传递信号"""
    download = Signal(str)   # 下载时的信号
    complete = Signal(str)   # 下载完成时的信号


class GamesPanel(QWidget):
    """游戏下载"""

    update_signal = Signal(list, str)
    
    def __init__(self, parent):
        super().__init__(None)
        self._parent = parent
        self.resource_path = parent.resource_path
        
        # 初始化设置管理器
        self.settings_manager = get_settings_manager()
        self.install_dialog = MinecraftInstallDialog(self)
        self.install_dialog.download_signal.connect(self.start_install)
        self.install_dialog.import_signal.connect(lambda: self._parent.parent.tasks_page.import_modpack())
        
        self.catalog_cancel = threading.Event()
        self.catalog_pool = QThreadPool(self)
        self.catalog_pool.setMaxThreadCount(1)
        self.catalog_loading = False
        self.catalog_cache = Path(self.settings_manager.config_path) / 'minecraft-catalog.json'
        self.minecraft_version_manifest_type_to_str = {
            "release": "正式版",
            "snapshot": "快照",
            "old_alpha": "旧版 Alpha",
            "old_beta": "旧版 Beta",
        }
        self.minecraft_version_manifest_type = {
            "正式版": "release",
            "快照": "snapshot",
            "旧版": "old_"
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
        if self.catalog_loading or self.catalog_cancel.is_set():
            return
        self.catalog_loading = True
        try:
            downloader = MinecraftDownloader(
                Path(self.settings_manager.config_path) / 'catalog-cache',
                source=self.settings_manager.get_setting('settings.general.mirrors', '自动'),
                cancel=self.catalog_cancel,
            )
            versions = downloader.manifest()['versions']
            self.update_signal.emit(versions, '')
        except DownloadCancelled:
            pass
        except Exception as exc:
            self.update_signal.emit([], str(exc))
        finally:
            self.catalog_loading = False
    
    @Slot(list, str)
    def on_games_finished(self, versions, error):
        """刷新游戏列表 - 使用懒加载"""
        if self.catalog_cancel.is_set():
            return
        if versions:
            self.minecraft_versions_cache = versions
            try:
                self.catalog_cache.write_text(json.dumps(versions, ensure_ascii=False), encoding='utf-8')
            except OSError:
                logger.exception('Unable to save Minecraft version catalogue')
        elif not self.minecraft_versions_cache:
            try:
                cached = json.loads(self.catalog_cache.read_text(encoding='utf-8'))
                if isinstance(cached, list):
                    self.minecraft_versions_cache = cached
            except (OSError, ValueError):
                pass
        self.catalog_status.setText(
            '版本列表刷新失败，显示上次记录。可点击重试。' if error and self.minecraft_versions_cache
            else '无法获取版本列表，请检查网络后重试。' if error else ''
        )
        self.catalog_status.setToolTip(error)
        self.catalog_status.setVisible(bool(error))
        self.retry_catalog.setVisible(bool(error))
        self.filter_games()

    def init_ui(self):
        """初始化用户界面"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        state = QHBoxLayout()
        self.catalog_status = QLabel('正在获取游戏版本列表…')
        self.catalog_status.setStyleSheet('color: #c9c1e5; padding: 8px;')
        self.catalog_status.setWordWrap(True)
        self.retry_catalog = QPushButton('重试')
        self.retry_catalog.clicked.connect(self.get_games_version)
        self.retry_catalog.hide()
        state.addWidget(self.catalog_status, 1)
        state.addWidget(self.retry_catalog)
        main_layout.addLayout(state)
        
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
        text_widget.setAttribute(Qt.WA_TransparentForMouseEvents)
        text_widget.setStyleSheet("background-color: transparent;")
        text_layout = QVBoxLayout(text_widget)
        text_layout.setContentsMargins(0, 14, 0, 14)
        text_layout.setSpacing(5)
        
        version_label = QLabel(f'版本号：{version}')
        version_label.setFont(system_font(10, QFont.Weight.Bold))
        version_label.setStyleSheet("color: #f2f2f2;")
        
        desc_label = QLabel(description)
        desc_label.setFont(system_font(9, QFont.Weight.Normal))
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
        label.setAttribute(Qt.WA_TransparentForMouseEvents)
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
        if event is not None and event.button() != Qt.LeftButton:
            return
        self.install_dialog.set_version(
            item.property("version"), str(item.property("description") or "")
        )
        self.install_dialog.exec()

    def start_install(self, version, loader="", loader_version=""):
        download_pages = self._parent.parent
        target_directory = self.settings_manager.get_setting("minecraft.directory.enable")
        if loader:
            if loader == "NeoForge":
                version_id = f"neoforge-{loader_version}"
            elif loader in ("Fabric", "Quilt"):
                version_id = f"{loader.lower()}-loader-{loader_version}-{version}"
            else:
                version_id = f"{version}-forge-{loader_version}"
            download_pages.tasks_page.start_install(version_id, target_directory, loader,
                                                     version, loader_version)
        else:
            download_pages.tasks_page.start_install(version, target_directory)

    def shutdown(self):
        self.catalog_cancel.set()
        return self.catalog_pool.activeThreadCount() == 0
    
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
        if not self.minecraft_versions and self.retry_catalog.isHidden():
            self.catalog_status.setText('没有符合当前筛选条件的版本。')
            self.catalog_status.show()
        elif self.minecraft_versions and self.retry_catalog.isHidden():
            self.catalog_status.hide()

    def clear_games_list(self):
        """清除现有的游戏版本列表"""
        layout = self.games_panel.widget().layout()
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        layout.addStretch()
