"""版本管理
 - 版本列表
 - 版本设置
"""

# StartGamePage 类
import os

from PySide6.QtWidgets import (
    QWidget, QLabel, QLineEdit, QVBoxLayout, QHBoxLayout, QFrame, QStackedWidget, QFileDialog, QMessageBox
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QFont, QPixmap, QColor, QPainter

from core.auth.microsoft import Authenticator, MinecraftSignals
from ui.widgets.buttons import QMStartButton
from ui.dialog.LoginDialog import LoginWaitDialog
from config.settings import get_settings_manager
from core.launcher import MinecraftLibLauncher
from utils.helpers import get_physical_resolution

import logging
logger = logging.getLogger(__name__)


class VersionControlPage(QWidget):
    """用户面板 - 可折叠"""
    
    started_changed = Signal()  # 游戏开始信号
    login_success = Signal(dict, str)  # 用户名, 登录类型
    

    def __init__(self, parent, resource_path, cache_path):
        super().__init__(parent)
        self.parent = parent
        self.cache_path = cache_path
        self.resource_path = resource_path
        
        self.current_login_mode = "版本列表"  # 当前登录模式：版本列表/版本设置
        self.background_color = QColor(0, 0, 0, 0)  # 透明背景
        
        # 初始化设置管理器
        self.settings_manager = get_settings_manager()

        # 初始化UI
        self.init_ui()

    def init_ui(self):
        """初始化用户界面"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 创建选项卡容器
        self.tab_container = QWidget()
        tab_container_layout = QHBoxLayout(self.tab_container)
        tab_container_layout.setContentsMargins(15, 0, 15, 25)
        
        # 创建选项卡按钮区域
        self.tab_buttons_widget = self.create_tab_buttons()
        # self.tab_buttons_widget.setStyleSheet("background-color: #225500;")

        # 右侧堆叠内容
        self.version_stack = QStackedWidget()
        self.version_stack.setFixedWidth(926 - 178 - 62)
        self.version_stack.setContentsMargins(10, 10, 10, 10)
        # self.version_stack.setStyleSheet("background-color: #552299;")

        tab_container_layout.addWidget(self.tab_buttons_widget)
        tab_container_layout.addSpacing(22)
        tab_container_layout.addWidget(self.version_stack)
        
        self.create_page_version_lists()  # 版本列表页
        self.create_page_version_setting()  # 版本设置页
        # self.version_stack.setCurrentIndex(0)

        main_layout.addWidget(self.tab_container)
        

    def create_tab_buttons(self):
        """创建选项卡按钮区域"""
        tab_buttons_widget = QWidget()
        tab_buttons_widget.setFixedWidth(178)
        tab_buttons_widget.setContentsMargins(0, 24, 0, 0)
        tab_buttons_layout = QVBoxLayout(tab_buttons_widget)
        tab_buttons_layout.setContentsMargins(0, 0, 0, 0)
        tab_buttons_layout.addSpacing(0)
        
        # 添加下划线（水平分隔线）
        underline = QHBoxLayout()
        title_underline = QFrame()
        title_underline.setFrameShape(QFrame.HLine)
        title_underline.setStyleSheet("background-color: rgba(139, 133, 218, 1);")
        title_underline.setFixedWidth(155)
        title_underline.setFixedHeight(2)
        underline.addWidget(title_underline)
        
        tab_buttons_layout.addLayout(underline)
        tab_buttons_layout.addSpacing(20)

        # 离线选项卡按钮
        self.offline_tab_btn = self.create_tab_button(
            "版本列表",
            self.version_lists_btn_clicked,
            size=(155, 44), font_size=10
        )
        tab_buttons_layout.addWidget(self.offline_tab_btn, 0, Qt.AlignCenter)
        
        # 正版选项卡按钮
        self.external_tab_btn = self.create_tab_button(
            "版本设置",
            self.version_settings_btn_clicked,
            size=(155, 44), font_size=10
        )
        tab_buttons_layout.addWidget(self.external_tab_btn, 0, Qt.AlignCenter)
        tab_buttons_layout.addStretch()
        
        # 设置初始状态：版本列表默认选中
        self.update_tab_button_style("版本列表", False)
        self.update_tab_button_style("版本设置", True)
        
        return tab_buttons_widget

    def create_tab_button(self, text, click_handler, size=(155, 44), font_size=12):
        """创建选项卡按钮"""
        button = QLabel()
        button.mousePressEvent = lambda event: click_handler()
        button.setFixedSize(*size)
        button.setStyleSheet("background-color: transparent;")
        
        # 添加文本
        text_label = QLabel(text, button)
        text_label.setFont(QFont("Source Han Sans CN Heavy", font_size))
        text_label.setAlignment(Qt.AlignCenter)  
        text_label.setStyleSheet("color: white; background-color: transparent;")
        text_label.setGeometry(0, 0, *size)   
        
        return button

    def version_settings_btn_clicked(self):
        """版本列表按钮点击事件"""
        # self.external_content.show()
        # self.offline_content.hide()
        
        self.update_tab_button_style("版本列表", True)
        self.update_tab_button_style("版本设置", False)
        self.current_login_mode = "版本列表"
        # self.update_ui_state()
        # self.restore_login_state()

    def version_lists_btn_clicked(self):
        """版本设置按钮点击事件"""
        # self.external_content.hide()
        # self.offline_content.show()
        # self.auth_manager.current_mode = 'offline'
        self.update_tab_button_style("版本列表", False)
        self.update_tab_button_style("版本设置", True)
        self.current_login_mode = "版本设置"
        # self.update_ui_state()
        # self.restore_login_state()

    def update_tab_button_style(self, tab_name, is_active):
        """更新选项卡按钮样式"""
        if tab_name == "版本列表":
            btn = self.external_tab_btn
            active_image = os.path.join(self.resource_path, 'images', 'user', 'external_tab_btn_active.png')
        else:
            btn = self.offline_tab_btn
            active_image = os.path.join(self.resource_path, 'images', 'user', 'external_tab_btn_active.png')
        
        if is_active and os.path.exists(active_image):
            btn.setPixmap(QPixmap(active_image).scaled(155, 44, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
        else:
            btn.clear()
            btn.setStyleSheet("background-color: transparent;")

    def create_image_button(self, text, image_path, click_handler, width, height, font_size=11):
        """创建图片按钮"""
        button = QLabel()
        button.mousePressEvent = lambda event: click_handler()
        button.setCursor(Qt.PointingHandCursor)
        button.setFixedSize(width, height)
        
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
    
    # ----- page 版本列表页 -----

    def create_page_version_lists(self):
        """版本列表页 - 带点击事件"""
        # 创建主容器
        content = QWidget()
        content.setContentsMargins(0, 0, 0, 0)
        container_layout = QHBoxLayout(content)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(10)
        
        # 左侧游戏安装路径区域
        self.directory_panel = self.create_directory_panel()
        container_layout.addWidget(self.directory_panel)
        
        # 右侧游戏版本列表区域
        self.version_list_panel = self.create_version_list_panel()
        container_layout.addWidget(self.version_list_panel)
        
        self.version_stack.addWidget(content)
        return content
    
    def create_directory_panel(self):
        """创建左侧游戏安装路径面板"""
        # 容器
        panel = QWidget()
        panel.setFixedWidth(260)
        panel.setStyleSheet("background-color: rgba(92, 90, 152, 0.35);")
        
        # 布局
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # 存储目录项的引用
        self.directory_items = []
        
        # 添加目录项
        directory_data = [
            {"is_selected": True, "title": "当前文件夹", "path": "G:\\buggcraftx\\.buggcraft\\", "has_delete": True},
            {"is_selected": False, "title": "官方启动器文件夹", "path": "G:\\buggcraftx\\.buggcraft\\", "has_delete": True}
        ]

        for data in directory_data:
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
        
        return panel

    def create_directory_item(self, is_selected, title, path, has_delete=False):
        """创建目录项"""
        # 容器
        item = QWidget()
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
            item.setStyleSheet('background-color: rgba(173, 157, 244, 0.21); border: 1px solid rgba(120, 89, 255, 1);')
        
        # 布局
        layout = QHBoxLayout(item)
        layout.setContentsMargins(15, 0, 0, 0)
        layout.setSpacing(0)
        
        # 选中图标
        icon_name = "selected.png" if is_selected else "not-selected.png"
        select_icon = self.create_icon_label(
            os.path.join(self.resource_path, 'images', 'version', icon_name),
            size=(30, 30)
        )
        
        layout.addWidget(select_icon)
        layout.addSpacing(15)
        
        # 文本区域
        text_widget = QWidget()
        text_widget.setStyleSheet("background-color: transparent; border: none;")
        text_layout = QVBoxLayout(text_widget)
        text_layout.setContentsMargins(0, 10, 0, 10)
        text_layout.setSpacing(5)
        
        title_label = QLabel(title)
        title_label.setStyleSheet("color: #f2f2f2; font-size: 14px; font-weight: bold; border: none;")
        
        path_label = QLabel(path)
        path_label.setStyleSheet("color: #f2f2f2; font-size: 11px; border: none;")
        
        text_layout.addWidget(title_label)
        text_layout.addWidget(path_label)
        
        layout.addWidget(text_widget, 1)
        layout.addSpacing(5)
        
        # 删除图标（如果有）
        if has_delete:
            delete_widget = QWidget()
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
            delete_layout.addWidget(delete_icon)
            delete_layout.addStretch()
            
            layout.addWidget(delete_widget)
        
        layout.addStretch()
        
        # 添加目录项点击事件
        item.mousePressEvent = lambda event: self.on_directory_clicked(item, event)
        item.setCursor(Qt.PointingHandCursor)

        return item

    def create_add_directory_item(self):
        """创建添加目录项"""
        item = QWidget()
        item.setStyleSheet('background-color: transparent; border: 1px solid rgba(120, 89, 255, 1);')
        item.setFixedHeight(45)
        
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
        
        # 添加版本项
        version_data = [
            {"version": "1.20.8", "description": "最新正式版本，发布于2025/04/21", "is_selected": True},
            {"version": "1.20.7", "description": "稳定版本，发布于2025/03/15", "is_selected": False}
        ]
        
        for data in version_data:
            item = self.create_version_item(
                data["version"],
                data["description"],
                data["is_selected"]
            )
            self.version_items.append(item)
            layout.addWidget(item)

        # 添加版本项
        # layout.addWidget(self.create_version_item(
        #     version="1.20.8",
        #     description="最新正式版本，发布于2025/04/21",
        #     is_selected=True
        # ))
        
        # layout.addWidget(self.create_version_item(
        #     version="1.20.7",
        #     description="稳定版本，发布于2025/03/15",
        #     is_selected=False
        # ))
        
        # 添加拉伸空间
        layout.addStretch()
        
        return panel

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
        layout.setContentsMargins(15, 0, 0, 0)
        layout.setSpacing(0)
        
        # 选中图标
        icon_name = "selected.png" if is_selected else "not-selected.png"
        select_icon = self.create_icon_label(
            os.path.join(self.resource_path, 'images', 'version', icon_name),
            size=(30, 30)
        )
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
        desc_label.setStyleSheet("color: #f2f2f2; font-size: 13px;")
        
        text_layout.addWidget(version_label)
        text_layout.addWidget(desc_label)
        
        layout.addWidget(text_widget, 1)
        layout.addSpacing(5)
        
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

    # ----- page 版本设置页 -----
    def create_page_version_setting(self):
        """版本设置页"""
        pass

    # ----- page -----

    def on_directory_clicked(self, item, event):
        """处理目录项点击事件"""
        # 更新所有目录项的选中状态
        for directory_item in self.directory_items:
            is_selected = directory_item == item
            directory_item.setProperty("is_selected", is_selected)
            
            # 更新样式
            if is_selected:
                directory_item.setStyleSheet('background-color: rgba(120, 89, 255, 1);')
            else:
                directory_item.setStyleSheet('background-color: rgba(173, 157, 244, 0.21);')
            
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
        print(f"选中目录: {title}, 路径: {path}")
        
        # 可以在这里触发其他操作，如刷新版本列表等
        self.refresh_version_list(path)

    def on_delete_directory(self, item, event):
        """处理删除目录事件"""
        # 阻止事件冒泡，避免触发目录项点击事件
        event.accept()
        
        title = item.property("title")
        path = item.property("path")
        
        # 显示确认对话框
        reply = QMessageBox.question(
            self, 
            "确认删除", 
            f"确定要删除目录 '{title}' 吗？\n路径: {path}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # 执行删除操作
            print(f"删除目录: {title}, 路径: {path}")
            # 从界面中移除该项
            if item in self.directory_items:
                self.directory_items.remove(item)
                item.setParent(None)
                item.deleteLater()

    def on_add_directory(self, event):
        """处理添加目录事件"""
        # 打开目录选择对话框
        directory = QFileDialog.getExistingDirectory(
            self, 
            "选择游戏目录",
            "", 
            QFileDialog.ShowDirsOnly
        )
        
        if directory:
            print(f"添加目录: {directory}")
            
            # 创建新目录项
            new_item = self.create_directory_item(
                is_selected=False,
                title=os.path.basename(directory),
                path=directory,
                has_delete=True
            )
            
            # 添加到目录列表
            self.directory_items.append(new_item)
            
            # 找到添加按钮的位置
            layout = self.directory_panel.layout()
            add_item_index = layout.count() - 3  # 添加按钮在倒数第三个位置
            
            # 在添加按钮之前插入新项
            layout.insertWidget(add_item_index, new_item)

    def on_install_new_game(self):
        """处理安装新游戏事件"""
        print("安装新游戏")
        # 这里可以打开安装新游戏的对话框或页面

    def on_version_clicked(self, item, event):
        """处理版本项点击事件"""
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
        description = item.property("description")
        print(f"选中版本: {version}, 描述: {description}")
        
        # 可以在这里触发其他操作，如准备启动游戏等

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
        
        version = item.property("version")
        print(f"打开版本文件夹: {version}")
        
        # 这里可以打开版本文件夹

    def on_delete_version(self, item, event):
        """处理删除版本事件"""
        # 阻止事件冒泡
        event.accept()
        
        version = item.property("version")
        
        # 显示确认对话框
        reply = QMessageBox.question(
            self, 
            "确认删除", 
            f"确定要删除版本 '{version}' 吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # 执行删除操作
            print(f"删除版本: {version}")
            # 从界面中移除该项
            if item in self.version_items:
                self.version_items.remove(item)
                item.setParent(None)
                item.deleteLater()

    def refresh_version_list(self, directory_path):
        """刷新版本列表"""
        print(f"刷新版本列表，目录: {directory_path}")
        # 这里可以根据目录路径加载版本列表


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
