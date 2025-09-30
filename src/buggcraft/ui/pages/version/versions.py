"""版本管理
 - 版本列表
"""

import os
import logging
import minecraft_launcher_lib

from PySide6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout, QFileDialog, QDialog, QScrollArea
)
from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtGui import QFont, QPixmap, QColor, QPainter

from config.settings import get_settings_manager
from core.minecraft.version import delete_minecraft_directory, delete_minecraft_version, open_folder
from ui.dialog.VersionDeleteDialog import VersionDeleteDialog
from ui.widgets.lable import SmartLabel


logger = logging.getLogger(__name__)


class MinecraftSettingSignals(QObject):
    """游戏启动时需要指定游戏路径、游戏版本，这些信息如果发生变动未及时传递信号，启动游戏路径版本是错误的。
    这里的信号需要同步到主UI中"""
    versions = Signal(str)   # 用户修改了游戏版本
    directory = Signal(str)  # 用户修改了游戏路径


class VersionsPage(QWidget):
    """用户面板 - 可折叠"""

    def __init__(self, resource_path, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.resource_path = resource_path
        
        self.background_color = QColor(0, 0, 0, 0)  # 透明背景
        
        self.signals = MinecraftSettingSignals()
        self.version_delete_dialog = VersionDeleteDialog()

        # 初始化设置管理器
        self.settings_manager = get_settings_manager()
        self.init_ui()

    def init_ui(self):
        """初始化用户界面"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(0)
        
        # 创建主容器
        content_container = QWidget(self)
        content_container.setContentsMargins(0, 0, 0, 0)
        container_layout = QHBoxLayout(content_container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(10)
        
        # 左侧游戏安装路径区域
        self.directory_panel = self.create_directory_panel()
        container_layout.addWidget(self.directory_panel)
        
        # 右侧游戏版本列表区域
        self.version_list_panel = self.create_version_list_panel()
        container_layout.addWidget(self.version_list_panel, 1)
        main_layout.addWidget(content_container)
        


    def create_image_button(self, text, image_path, click_handler, width, height, font_size=11):
        """创建图片按钮"""
        button = QLabel()
        button.mousePressEvent = lambda event: click_handler()
        button.setCursor(Qt.PointingHandCursor)
        button.setFixedSize(width, height)
        # button.setMaximumWidth(width)
        # button.setMaximumHeight(height)
        
        if image_path and os.path.exists(image_path):
            pixmap = QPixmap(image_path)
            if not pixmap.isNull():
                button.setPixmap(pixmap.scaled(width, height, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
        
        text_label = QLabel(text, button)
        text_label.setFont(QFont("Source Han Sans CN Heavy", font_size))
        text_label.setAlignment(Qt.AlignCenter)
        text_label.setStyleSheet("color: #f2f2f2; background-color: transparent;")
        text_label.setGeometry(0, 0, width, height)
        return button
    
    def create_directory_panel(self):
        """创建左侧游戏安装路径面板"""
        # 容器
        panel = QWidget()
        # panel.setMaximumWidth(260)
        # panel.setContentsMargins(10, 0, 10, 0)
        panel.setStyleSheet("background-color: rgba(92, 90, 152, 0.25);")
        
        # 布局
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # 存储目录项的引用
        self.directory_items = []

        # 从配置文件加载目录数据
        for data in self.load_directory_data():
            item = self.create_directory_item(
                data["is_selected"],
                data["title"],
                data["path"],
                data["has_delete"]
            )
            self.directory_items.append(item)
            layout.addWidget(item)
        
        layout.addWidget(self.create_add_directory_item())
        
        # 添加拉伸空间
        layout.addStretch()
        
        # 添加安装新游戏按钮
        install_button = self.create_image_button(
            "安装新游戏", 
            os.path.join(self.resource_path, 'images', 'user', 'legal_login_btn.png'),
            lambda: print('安装新游戏'),
            235, 40,
            font_size=10
        )
        layout.addWidget(install_button)
        
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

    def create_directory_item(self, is_selected, title, path, has_delete=False):
        """创建目录项"""
        # 容器
        item = QWidget()
        item.setContentsMargins(0, 2, 0, 2)
        item.setStyleSheet("background-color: transparent;")
        item.setFixedHeight(60)
        
        # 存储数据
        item.setProperty("is_selected", is_selected)
        item.setProperty("title", title)
        item.setProperty("path", path)

        # 设置样式
        if is_selected:
            item.setStyleSheet('background-color: rgba(120, 89, 255, 1);')
        else:
            item.setStyleSheet('background-color: rgba(173, 157, 244, 0.2); border: 1px solid rgba(120, 89, 255, 1);')
        
        # 布局
        layout = QHBoxLayout(item)
        layout.setContentsMargins(10, 2, 10, 2)
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
        text_widget.setStyleSheet("background-color: transparent; border: none;")
        text_layout = QVBoxLayout(text_widget)
        text_layout.setContentsMargins(0, 10, 0, 10)
        text_layout.setSpacing(5)
        
        title_label = SmartLabel(title, max_heiht=140)
        title_label.setStyleSheet("color: #f2f2f2; font-size: 14px; font-weight: bold; border: none;")
        
        path_label = SmartLabel(path, max_heiht=140)
        # path_label.setMaximumWidth(135)
        path_label.setStyleSheet("color: #f2f2f2; font-size: 11px; border: none;")
        
        text_layout.addWidget(title_label)
        text_layout.addWidget(path_label)
        
        layout.addWidget(text_widget)
        # layout.addSpacing(5)
        # layout.addStretch()
        
        # 删除图标（如果有）
        if has_delete:
            delete_widget = QWidget()
            delete_widget.setContentsMargins(0, 0, 0, 0)
            delete_widget.setStyleSheet("background-color: transparent; border: none;")
            delete_layout = QVBoxLayout(delete_widget)
            delete_layout.setContentsMargins(0, 10, 8, 0)
            delete_layout.setSpacing(0)
            
            delete_icon = self.create_icon_label(
                os.path.join(self.resource_path, 'images', 'version', 'close.png'),
                size=(16, 16),
                cursor=Qt.PointingHandCursor
            )
            # 添加删除点击事件
            delete_icon.mousePressEvent = lambda event: self.on_delete_directory(item, event)
            delete_layout.addWidget(delete_icon, 0)
            delete_layout.addStretch()
            
            layout.addWidget(delete_widget)
        
        # layout.addStretch()
        
        # 添加目录项点击事件
        item.mousePressEvent = lambda event: self.on_directory_clicked(item, event)
        item.setCursor(Qt.PointingHandCursor)

        return item

    def create_add_directory_item(self):
        """创建添加目录项"""
        item = QWidget()
        item.setStyleSheet('background-color: transparent; border: 1px solid rgba(120, 89, 255, 1);')
        item.setFixedHeight(40)
        
        layout = QHBoxLayout(item)
        
        # 添加图标
        add_icon = self.create_icon_label(
            os.path.join(self.resource_path, 'images', 'version', 'add.png'),
            size=(12, 12)
        )
        
        # 文本
        text_label = QLabel('添加游戏文件夹')
        text_label.setStyleSheet("color: rgba(209, 204, 255, 1); font-weight: bold; font-size: 13px; border: none;")
        
        layout.addStretch()
        layout.addWidget(add_icon, 0, Qt.AlignCenter)
        layout.addWidget(text_label, 0, Qt.AlignCenter)
        layout.addStretch()
        
        # 添加点击事件
        item.mousePressEvent = self.on_add_directory
        item.setCursor(Qt.PointingHandCursor)
        return item

    def create_version_list_panel(self):
        """创建右侧游戏版本列表面板"""
        panel = QWidget()
        panel.setStyleSheet("background-color: transparent;")
        
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        
        # 存储版本项的引用
        self.version_items = []
        
        # 获取当前选中的目录
        selected_directory = None
        for item in self.directory_items:
            if item.property("is_selected"):
                selected_directory = item.property("path")
                break
        
        # 如果找到选中的目录，加载该目录的版本数据
        if selected_directory:
            version_data = self.load_version_data(selected_directory)
            
            # 添加版本项
            for data in version_data:
                item = self.create_version_item(
                    data["version"],
                    data["description"],
                    data["is_selected"]
                )
                self.version_items.append(item)
                layout.addWidget(item, 1)

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

    def create_version_item(self, version, description, is_selected=False):
        """创建版本项"""
        item = QWidget()
        item.setStyleSheet('background-color: rgba(190, 183, 255, 0.25);')
        item.setFixedHeight(68)
        
        # 存储数据
        item.setProperty("version", version)
        item.setProperty("description", description)
        item.setProperty("is_selected", is_selected)

        layout = QHBoxLayout(item)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(0)
        
        # 选中图标
        icon_name = "selected.png" if is_selected else "not-selected.png"
        select_icon = self.create_icon_label(
            os.path.join(self.resource_path, 'images', 'version', icon_name),
            size=(30, 30)
        )
        layout.addSpacing(10)
        layout.addWidget(select_icon)
        layout.addSpacing(15)
        
        # 文本区域
        text_widget = QWidget()
        text_widget.setStyleSheet("background-color: transparent;")
        text_layout = QVBoxLayout(text_widget)
        text_layout.setContentsMargins(0, 14, 0, 14)
        text_layout.setSpacing(5)
        
        version_label = QLabel(f'版本号：{version}')
        version_label.setStyleSheet("color: #f2f2f2; font-size: 13px;")
        
        desc_label = QLabel(description)
        desc_label.setMaximumWidth(200)
        desc_label.setStyleSheet("color: #f2f2f2; font-size: 13px;")
        
        text_layout.addWidget(version_label, 0, Qt.AlignVCenter)
        text_layout.addWidget(desc_label, 0, Qt.AlignVCenter)
        
        layout.addWidget(text_widget)
        layout.addStretch(1)
        
        # 操作图标区域
        icons_widget = QWidget()
        icons_widget.setStyleSheet("background-color: transparent;")
        icons_layout = QHBoxLayout(icons_widget)
        icons_layout.setContentsMargins(10, 5, 15, 5)
        icons_layout.setSpacing(15)
        
        # 设置图标
        setting_icon = self.create_icon_label(
            os.path.join(self.resource_path, 'images', 'version', 'setting.png'),
            size=(17, 17),
            cursor=Qt.PointingHandCursor
        )
        setting_icon.mousePressEvent = lambda event: self.on_version_settings(item, event)
        icons_layout.addWidget(setting_icon)
        
        # 文件夹图标
        folder_icon = self.create_icon_label(
            os.path.join(self.resource_path, 'images', 'version', 'folder.png'),
            size=(18, 18),
            cursor=Qt.PointingHandCursor
        )
        folder_icon.mousePressEvent = lambda event: self.on_open_version_folder(item, event)
        icons_layout.addWidget(folder_icon)
        
        # 删除图标
        delete_icon = self.create_icon_label(
            os.path.join(self.resource_path, 'images', 'version', 'delete.png'),
            size=(16, 16),
            cursor=Qt.PointingHandCursor
        )
        delete_icon.mousePressEvent = lambda event: self.on_delete_version(item, event)
        icons_layout.addWidget(delete_icon)
        
        layout.addWidget(icons_widget)
        
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

    def load_directory_data(self):
        """从配置文件加载目录数据"""
        # 获取当前启用的目录
        enable_directory = self.settings_manager.get_setting('minecraft', {}).get("directory", {}).get("enable", None)
        
        # 获取所有已安装目录
        installed_directories = self.settings_manager.get_setting('minecraft', {}).get("directory", {}).get("installed", [])
        
        # 准备目录数据
        directory_data = []
        for directory in installed_directories:
            # 获取目录名称（使用路径的最后一部分）
            dir_name = os.path.basename(directory)
            
            # 检查是否是当前启用的目录
            is_selected = directory == enable_directory
            
            directory_data.append({
                "is_selected": is_selected,
                "title": dir_name,
                "path": directory,
                "has_delete": True
            })
        
        return directory_data

    def load_version_data(self, directory_path):
        """扫描指定目录下的 Minecraft 版本"""
        from datetime import datetime
        try:
            # 使用 minecraft_launcher_lib 获取已安装版本
            installed_versions = minecraft_launcher_lib.utils.get_installed_versions(directory_path)
            
            # 获取当前启用的版本
            enable_version = self.settings_manager.get_setting('minecraft.version.enable')
            
            # 准备版本数据
            version_data = []
            for version in installed_versions:
                version_id = version['id']
                
                # 获取版本类型和发布日期
                version_type = version.get('type', 'release').capitalize()
                release_time = version.get('releaseTime')
                
                # 格式化发布日期
                if release_time:
                    try:
                        release_date = datetime.strptime(release_time, "%Y-%m-%dT%H:%M:%S%z")
                        formatted_date = release_date.strftime("%Y/%m/%d")
                    except:
                        formatted_date = release_time
                else:
                    formatted_date = "未知日期"
                
                # 构建描述
                description = f"{version_type}版本，发布于{formatted_date}"
                
                # 检查是否是当前启用的版本
                is_selected = version_id == enable_version
                
                version_data.append({
                    "version": version_id,
                    "description": description,
                    "is_selected": is_selected
                })
            
            return version_data
        
        except Exception as e:
            logger.error(f"扫描目录 {directory_path} 失败: {e}")
            return []

    def on_directory_clicked(self, item, event):
        """处理目录项点击事件 - 更新配置文件并刷新版本列表"""
        # 更新所有目录项的选中状态
        for directory_item in self.directory_items:
            is_selected = directory_item == item
            directory_item.setProperty("is_selected", is_selected)
            
            # 更新样式
            if is_selected:
                directory_item.setStyleSheet('background-color: rgba(120, 89, 255, 1);')
            else:
                directory_item.setStyleSheet('background-color: rgba(173, 157, 244, 0.2);  border: 1px solid rgba(120, 89, 255, 1)')
            
            # 更新选中图标
            select_icon = directory_item.findChild(QLabel)
            if select_icon:
                icon_name = "selected.png" if is_selected else "not-selected.png"
                select_icon.setPixmap(QPixmap(
                    os.path.join(self.resource_path, 'images', 'version', icon_name)
                ).scaled(30, 30, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
        
        # 获取选中目录的数据
        title = item.property("title")
        path = item.property("path")
        
        self.scan_versions(path)
        # 更新配置文件
        self.settings_manager.set_setting("minecraft.directory.enable", path)
        self.settings_manager.save_settings()
        
        # 刷新版本列表
        self.refresh_version_list(path)
        self.signals.directory.emit(path)
        logger.info(f"已切换到新添加的目录: {title}, 路径: {path}")

    def on_delete_directory(self, item, event):
        """处理删除目录事件 - 更新配置文件"""
        # 阻止事件冒泡
        event.accept()
        
        title = item.property("title")
        path = item.property("path")
        
        # 显示确认对话框
        self.version_delete_dialog.set_title(f"游戏删除确认")
        self.version_delete_dialog.set_message(f"您确认要删除 {path} 整个游戏吗？")
        self.version_delete_dialog.set_message_text(f"此操作不可回退，将删除所有版本、存档、资源包、光影、Mod等文件！")

        if self.version_delete_dialog.exec() == QDialog.Accepted:
            delete_minecraft_directory(path)

            installed_directories: list = self.settings_manager.get_setting("minecraft", {}).get("directory", {}).get("installed", [])
            if not path in installed_directories:
                return
            
            installed_directories.remove(path)
            
            self.settings_manager.set_setting("minecraft.directory.installed", installed_directories)
            self.settings_manager.save_settings()
            
            if item in self.directory_items:
                # 从界面中移除该项
                self.directory_items.remove(item)
                item.setParent(None)
                item.deleteLater()
                
                # 如果删除的是当前选中的目录，选择第一个目录
                if self.settings_manager.get_setting("minecraft.directory.enable") == path and self.directory_items:
                    self.on_directory_clicked(self.directory_items[0], None)

    def on_add_directory(self, event):
        """处理添加目录事件 - 更新配置文件"""
        # 打开目录选择对话框
        directory = QFileDialog.getExistingDirectory(
            self, 
            "选择游戏目录 (.minecraft/)",
            "", 
            QFileDialog.ShowDirsOnly
        )

        if not directory:
            return
        
        installed_directories = self.settings_manager.get_setting("minecraft", {}).get("directory", {}).get("installed", [])
        if directory in installed_directories:
            return
        
        installed_directories.append(directory)
        
        self.settings_manager.set_setting("minecraft.directory.installed", installed_directories)
        self.settings_manager.save_settings()
        
        self.scan_versions(directory)  # 扫描新目录下的版本
        
        # 创建新目录项
        new_item = self.create_directory_item(
            is_selected=False,
            title=os.path.basename(directory),
            path=directory,
            has_delete=True
        )
        
        self.directory_items.append(new_item)
        
        # 找到添加按钮的位置
        # 添加按钮在倒数第三个位置
        # 在添加按钮之前插入新项
        layout = self.directory_panel.widget().layout()
        add_item_index = layout.count() - 3
        layout.insertWidget(add_item_index, new_item)

        # 自动切换到新添加的目录
        self.on_directory_clicked(new_item, None)

    def on_version_clicked(self, item, event):
        """处理版本项点击事件 - 更新配置文件"""
        # 更新所有版本项的选中状态
        for version_item in self.version_items:
            is_selected = version_item == item
            version_item.setProperty("is_selected", is_selected)
            
            # 更新选中图标
            select_icon = version_item.findChild(QLabel)
            if select_icon:
                icon_name = "selected.png" if is_selected else "not-selected.png"
                select_icon.setPixmap(QPixmap(
                    os.path.join(self.resource_path, 'images', 'version', icon_name)
                ).scaled(30, 30, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
        
        # 获取选中版本的数据
        version = item.property("version")
        
        # 更新配置文件
        self.settings_manager.set_setting("minecraft.version.enable", version)
        self.settings_manager.save_settings()
        self.signals.versions.emit(version)
        print(f"选中版本: {version}")

    def on_version_settings(self, item, event):
        """处理版本设置事件"""
        # 阻止事件冒泡
        event.accept()
        
        version = item.property("version")
        print(f"打开版本设置: {version}")
        
        # 这里可以打开版本设置对话框

    def on_open_version_folder(self, item, event):
        """处理打开版本文件夹事件"""
        # 阻止事件冒泡
        event.accept()
        minecraft_version = item.property("version")
        minecraft_directory = self.settings_manager.get_setting("minecraft.directory.enable")
        minecraft_path = os.path.abspath(os.path.join(minecraft_directory, "versions", minecraft_version))
        open_folder(minecraft_path)
        logger.info(f"打开版本文件夹: {minecraft_path}")

    def on_delete_version(self, item, event):
        """处理删除版本事件 - 更新配置文件"""
        # 阻止事件冒泡
        event.accept()
        version = item.property("version")
        
        # 显示确认对话框
        self.version_delete_dialog.set_title(f"版本删除确认")
        self.version_delete_dialog.set_message(f"您确认要删除 {version} 游戏版本吗？")
        self.version_delete_dialog.set_message_text(f"当前游戏版本已开启版本隔离，将删除 存档、资源包、光影、Mod等文件！")
        if self.version_delete_dialog.exec() == QDialog.Accepted:
            delete_minecraft_version(
                self.settings_manager.get_setting("minecraft", {}).get("directory", {}).get("enable", None), 
                version
            )
            # 获取现有版本列表
            installed_versions: list = self.settings_manager.get_setting("minecraft", {}).get("version", {}).get("installed", [])
            
            # 移除版本
            if version in installed_versions:
                installed_versions.remove(version)

                self.settings_manager.set_setting("minecraft.version.installed", installed_versions)
                self.settings_manager.save_settings()
                
                # 从界面中移除该项
                if item in self.version_items:
                    self.version_items.remove(item)
                    item.setParent(None)
                    item.deleteLater()
                
                # 如果删除的是当前选中的版本，选择第一个版本
                if self.settings_manager.get_setting("minecraft.version.enable") == version and self.version_items:
                    self.on_version_clicked(self.version_items[0], None)

    def scan_versions(self, directory_path):
        """扫描目录下的版本并更新配置"""
        try:
            # 扫描目录下的版本
            installed_versions = minecraft_launcher_lib.utils.get_installed_versions(directory_path)
            version_ids = [v['id'] for v in installed_versions]

            # 如果没有当前启用的版本，设置第一个版本为启用
            if not self.settings_manager.get_setting('minecraft.version.enable') in version_ids:
                self.settings_manager.set_setting('minecraft.version.enable', version_ids[0])

            self.settings_manager.set_setting("minecraft.version.installed", version_ids)
            self.settings_manager.save_settings()
            self.signals.versions.emit(version_ids[0])
            logger.info(f"更新版本: {', '.join(version_ids)}")
        
        except Exception as e:
            logger.error(f"扫描版本失败: {e}")

    def refresh_version_list(self, directory_path):
        """刷新版本列表 - 扫描目录并更新UI"""
        # 扫描目录下的版本
        self.scan_versions(directory_path)
        for i in reversed(range(self.version_list_panel.widget().layout().count())):
            # 移除所有子部件
            item = self.version_list_panel.widget().layout().itemAt(i)
            if item.widget():
                item.widget().setParent(None)
            self.version_list_panel.widget().layout().removeItem(item)

        # 清空版本项列表
        self.version_items = []
        
        # 加载新版本的版本数据
        version_data = self.load_version_data(directory_path)
        
        # 添加新版本项
        for data in version_data:
            item = self.create_version_item(
                data["version"],
                data["description"],
                data["is_selected"]
            )
            self.version_items.append(item)
            self.version_list_panel.widget().layout().addWidget(item)
        
        # 添加拉伸空间
        self.version_list_panel.widget().layout().addStretch()

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
