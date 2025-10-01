"""版本管理
 - 版本设置
"""
import os
from typing import Any

from PySide6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout, QScrollArea, QComboBox
)
from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtGui import QFont, QPixmap, QColor, QPainter

from config.settings import get_settings_manager
from config.javafinder import JavaPathFinder
from ui.widgets.collapse import CollapsePanel
from ui.pages.version.memory_panel import MemorySettingsPanel
from ui.widgets.radio import QMRadioButton, QMRadioGroup
from core.visibility import VisibilitySettings


import logging
logger = logging.getLogger(__name__)


from PySide6.QtWidgets import QComboBox
from PySide6.QtCore import Qt, QPoint, QRect
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QComboBox, QWidget, QHBoxLayout, QLabel
from PySide6.QtCore import Qt, QSize, QEvent
from PySide6.QtGui import QPixmap, QPainter, QIcon, QPolygon


class QMComboBox(QComboBox):
    """修复后的自定义下拉框 - 推荐版本"""
    
    def __init__(self, parent):
        super().__init__(parent)
        self.resource_path = parent.resource_path
        self.is_expanded = False
        self.expanded_icon = None
        self.collapsed_icon = None
        self.icon_label = None
        self.init_ui()
    
    def init_ui(self):
        """初始化 UI"""
        # 设置样式
        self.setStyleSheet("""
            QComboBox {
                background-color: rgba(0, 0, 0, 0.3);
                color: rgba(255, 255, 255, 1);
                border-radius: 0px;
                padding: 5px;
                padding-left: 10px;
                min-height: 30px;
                padding-right: 30px;  /* 为图标留出空间 */
            }
            
            QComboBox:hover {
                background-color: rgba(0, 0, 0, 0.2);
            }
            
            QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: center right;
                height: 30px;  /* 增加宽度 */
                border-left: none;  /* 移除左边框 */
            }
            
            QComboBox::down-arrow {
                image: none;  /* 禁用默认箭头 */
            }
            
            QComboBox QAbstractItemView {
                min-height: 30px;
                background-color: rgba(0, 0, 0, 0.3);
                color: rgba(255, 255, 255, 1);
                border: 1px solid rgba(120, 89, 255, 0.5);
                selection-background-color: rgba(120, 89, 255, 0.9);
                selection-color: rgba(255, 255, 255, 1);
                outline: none;
                padding: 5px;
            }
            
            QComboBox QAbstractItemView::item {
                height: 30px;  /* 设置每一项的高度 */
                padding: 5px 10px;
                border-bottom: 1px solid rgba(60, 60, 70, 0.5);
            }
            
            QComboBox QAbstractItemView::item:last {
                border-bottom: none;
            }
            
            QComboBox QAbstractItemView::item:hover {
                background-color: rgba(120, 89, 255, 0.3);
            }
        """)
        
        # 加载图标
        self.load_icons()
        
        # 创建图标标签
        self.icon_label = QLabel(self)
        self.icon_label.setFixedSize(16, 16)
        self.icon_label.setStyleSheet("background-color: transparent;")
        
        # 更新图标
        self.update_icon()
        
        # 安装事件过滤器
        self.view().installEventFilter(self)
    
    def load_icons(self):
        """加载图标文件 - 带详细日志"""
        # 加载收起状态图标
        collapsed_path = os.path.join(self.resource_path, 'images', 'version', "fold-up.png")
        print(f"尝试加载收起状态图标: {collapsed_path}")
        
        if os.path.exists(collapsed_path):
            self.collapsed_icon = QPixmap(collapsed_path)
            if self.collapsed_icon.isNull():
                print(f"图标加载失败: {collapsed_path}")
                self.collapsed_icon = self.create_default_collapsed_icon()
            else:
                print(f"图标加载成功: {collapsed_path}")
                self.collapsed_icon = self.collapsed_icon.scaled(16, 16, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        else:
            print(f"图标文件不存在: {collapsed_path}")
            self.collapsed_icon = self.create_default_collapsed_icon()
        
        # 加载展开状态图标
        expanded_path = os.path.join(self.resource_path, 'images', 'version', "expand.png")
        print(f"尝试加载展开状态图标: {expanded_path}")
        
        if os.path.exists(expanded_path):
            self.expanded_icon = QPixmap(expanded_path)
            if self.expanded_icon.isNull():
                print(f"图标加载失败: {expanded_path}")
                self.expanded_icon = self.create_default_expanded_icon()
            else:
                print(f"图标加载成功: {expanded_path}")
                self.expanded_icon = self.expanded_icon.scaled(16, 16, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        else:
            print(f"图标文件不存在: {expanded_path}")
            self.expanded_icon = self.create_default_expanded_icon()
    
    def create_default_collapsed_icon(self):
        """创建默认收起状态图标"""
        pixmap = QPixmap(16, 16)
        pixmap.fill(Qt.transparent)
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 绘制向下箭头
        center_x = pixmap.width() // 2
        center_y = pixmap.height() // 2
        
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255))
        
        points = [
            QPoint(center_x - 4, center_y - 2),  # 左上点
            QPoint(center_x + 4, center_y - 2),   # 右上点
            QPoint(center_x, center_y + 4)        # 下顶点
        ]
        
        painter.drawPolygon(QPolygon(points))
        painter.end()
        
        return pixmap
    
    def create_default_expanded_icon(self):
        """创建默认展开状态图标"""
        pixmap = QPixmap(16, 16)
        pixmap.fill(Qt.transparent)
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 绘制向上箭头
        center_x = pixmap.width() // 2
        center_y = pixmap.height() // 2
        
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255))
        
        points = [
            QPoint(center_x, center_y - 4),  # 上顶点
            QPoint(center_x - 4, center_y + 2),  # 左下点
            QPoint(center_x + 4, center_y + 2)   # 右下点
        ]
        
        painter.drawPolygon(QPolygon(points))
        painter.end()
        
        return pixmap
    
    def eventFilter(self, obj, event):
        """事件过滤器 - 检测下拉列表的显示和隐藏"""
        if obj == self.view() and event.type() == QEvent.Show:
            self.is_expanded = True
            self.update_icon()
        elif obj == self.view() and event.type() == QEvent.Hide:
            self.is_expanded = False
            self.update_icon()
        return super().eventFilter(obj, event)
    
    def update_icon(self):
        """更新图标状态"""
        if self.is_expanded:
            # 展开状态图标
            if not self.expanded_icon.isNull():
                self.icon_label.setPixmap(self.expanded_icon)
            else:
                self.icon_label.setPixmap(self.create_default_expanded_icon())
        else:
            # 收起状态图标
            if not self.collapsed_icon.isNull():
                self.icon_label.setPixmap(self.collapsed_icon)
            else:
                self.icon_label.setPixmap(self.create_default_collapsed_icon())
    
    def resizeEvent(self, event):
        """调整大小事件 - 更新图标位置"""
        super().resizeEvent(event)
        self.update_icon_position()
    
    def update_icon_position(self):
        """更新图标位置"""
        padding = 10
        x = self.width() - self.icon_label.width() - padding
        y = (self.height() - self.icon_label.height()) // 2
        self.icon_label.move(x, y)


from PySide6.QtWidgets import QWidget, QLabel, QListWidget, QListWidgetItem, QVBoxLayout, QFrame
from PySide6.QtCore import Qt, QSize, QPropertyAnimation, Property, QRect, QPoint, QEasingCurve
from PySide6.QtGui import QPainter, QColor, QBrush, QPen, QLinearGradient


class SettingsPage(QWidget):
    """用户面板 - 可折叠"""

    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.cache_path = parent.cache_path
        self.resource_path = parent.resource_path
        self.background_color = QColor(0, 0, 0, 0)  # 透明背景

        self.disabled = True
        
        # 初始化设置管理器
        self.settings_manager = get_settings_manager()
        self.available_java_versions = self.settings_manager.get_setting("java.installations", [])
        self.init_ui()

        if not self.available_java_versions:
            self.load_java_path()
        
        independent_setting = False
        version = self.settings_manager.get_setting('minecraft.version.enable')
        if version is not None:
            independent_setting = self.settings_manager.get_setting(f"minecraft.version_setting.{version}.enable", False)
        self.is_disabled(independent_setting)

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
        
        # 设置区域
        # # 左侧游戏安装路径区域
        self.settings_panel = self.create_settings_panel()
        container_layout.addWidget(self.settings_panel)

        main_layout.addWidget(content_container)

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
    
    def create_version_item(self, version='1.21.8', description='asdasdadasdadasd', is_selected=False):
        """创建版本项"""
        version = self.settings_manager.get_setting('minecraft.version.enable')
        description = self.settings_manager.get_setting('minecraft.directory.enable')
        item = QWidget()
        item.setStyleSheet('background-color: rgba(190, 183, 255, 0.25);')
        item.setFixedHeight(68)
        
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
        self.java_auto_button = QMRadioButton(
            self,
            "是否启用特定游戏设置",
            None,
            data_property='auto',
            messages_max_heiht=100
        )
        icons_layout.addWidget(self.java_auto_button)
        
        # 文件夹图标
        folder_icon = self.create_icon_label(
            os.path.join(self.resource_path, 'images', 'version', 'folder.png'),
            size=(18, 18),
            cursor=Qt.PointingHandCursor
        )
        # folder_icon.mousePressEvent = lambda event: self.on_open_version_folder(item, event)
        # icons_layout.addWidget(folder_icon)
        
        # 删除图标
        delete_icon = self.create_icon_label(
            os.path.join(self.resource_path, 'images', 'version', 'delete.png'),
            size=(16, 16),
            cursor=Qt.PointingHandCursor
        )
        # delete_icon.mousePressEvent = lambda event: self.on_delete_version(item, event)
        # icons_layout.addWidget(delete_icon)
        
        layout.addWidget(icons_widget)
        
        # 添加版本项点击事件
        # item.mousePressEvent = lambda event: self.on_version_clicked(item, event)
        # item.setCursor(Qt.PointingHandCursor)

        return item
    
    def create_version_independent(self):
        """创建 版本隔离 设置内容"""
        version = self.settings_manager.get_setting('minecraft.version.enable')
        description = self.settings_manager.get_setting('minecraft.directory.enable')

        content = QWidget()
        content.setStyleSheet("background-color: transparent;")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        button_group = QMRadioGroup()
        
        # 默认选择选项
        independent_button = QMRadioButton(
            self,
            f'启用 {version} 独立版本设置',
            f'单独启用设置：{description}',
            data_property=True
        )
        layout.addWidget(independent_button)
        button_group.add_button(independent_button)

        default_button = QMRadioButton(
            self,
            f'跟随全局设置',
            f'不在为版本 {version} 独立设置，将跟随全局设置',
            data_property=False
        )
        layout.addWidget(default_button)
        button_group.add_button(default_button)

        # 设置默认选中
        _isolation = default_button
        if version is not None:
            _isolation = {
                False: default_button,
                True: independent_button
            }.get(self.settings_manager.get_setting(f"minecraft.version_setting.{version}.enable", False))
        button_group.set_selected_button(_isolation)
        button_group.button_selected.connect(self.is_disabled)
        panel = CollapsePanel(self, f'启用 {version} 游戏版本设置', '启用后当前版本不受全局设置管控，不影响其他游戏设置', True, is_collaspe=False)
        panel.set_content(content)
        return panel
    
    def create_settings_panel(self):
        # 容器
        panel = QWidget()

        # 布局
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        # 当前选择版本信息
        version = self.create_version_independent()
        layout.addWidget(version, 1)
        
        # 版本隔离
        self.version_isolation = self.create_version_isolation()
        layout.addWidget(self.version_isolation)

        # 游戏Java
        self.java_content = self.create_java_content()
        self.java_panel = CollapsePanel(self, '游戏Java', self.settings_manager.get_setting("java.name", '系统将自动选择最适合的 Java 版本'))
        self.java_panel.set_content(self.java_content)
        layout.addWidget(self.java_panel)

        # 自动分配内存
        self.minecraft_free = MemorySettingsPanel(self)  # self.create_minecraft_free()
        layout.addWidget(self.minecraft_free)

        # 启动器可见性
        self.launcher_visibility = self.create_launcher_visibility()
        layout.addWidget(self.launcher_visibility)

        # 设置游戏窗口分辨率
        self.launcher_resolution = self.create_minecraft_resolution()
        layout.addWidget(self.launcher_resolution)

        # 进程优先级
        self.minecraft_process_priority = self.create_process_priority()
        layout.addWidget(self.minecraft_process_priority)

        # 游戏调试
        self.minecraft_debug = self.create_minecraft_debug()
        layout.addWidget(self.minecraft_debug)

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

    def create_version_isolation(self):
        """创建 版本隔离 设置内容"""
        content = QWidget()
        content.setStyleSheet("background-color: transparent;")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # 创建按钮组
        button_group = QMRadioGroup()
        button_group.button_selected.connect(self.on_isolate_selected)

        # 默认选择选项
        default_button = QMRadioButton(
            self,
            '默认 (".minecraft/")',
            '(资源存放在 ".minecraft/")',
            data_property=False
        )
        layout.addWidget(default_button)
        button_group.add_button(default_button)

        # 版本独立选择选项
        isolate_button = QMRadioButton(
            self,
            "个版本独立",
            '(存放在 ".minecraft/versions/<版本名>/"，除 assets、libraries 外)',
            data_property=True,
            text_max_heiht=100,
            messages_max_heiht=400
        )
        layout.addWidget(isolate_button)
        button_group.add_button(isolate_button)

        # 设置默认选中
        _isolation = {
            False: default_button,
            True: isolate_button
        }.get(self.settings_manager.get_setting("minecraft.isolation", True))
        button_group.set_selected_button(_isolation)

        panel = CollapsePanel(self, '版本隔离', '默认 (".minecraft/")', True)
        panel.set_content(content)
        return panel

    def create_java_content(self):
        """创建 Java 设置内容"""
        content = QWidget()
        content.setStyleSheet("background-color: transparent;")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        
        # 创建按钮组
        _launlation = {}
        self.java_button_group = QMRadioGroup()
        
        self.java_auto_button = QMRadioButton(
            self,
            "使用推荐的 Java 版本",
            "系统将自动选择最适合的 Java 版本",
            data_property='auto'
        )
        layout.addWidget(self.java_auto_button)
        self.java_button_group.add_button(self.java_auto_button)
        _launlation.update({"使用推荐的 Java 版本": self.java_auto_button})
        
        # 版本选项
        for java_path, version in self.available_java_versions:
            version_button = QMRadioButton(
                self,
                version,
                java_path
            )
            layout.addWidget(version_button)
            self.java_button_group.add_button(version_button)
            _launlation.update({version: version_button})
        
        # 自定义选项
        custom_button = QMRadioButton(
            self,
            "自定义 Java 路径",
            None,
            data_property='custom',
            slot_desc=self.create_custom_java_button()
        )
        layout.addWidget(custom_button)
        self.java_button_group.add_button(custom_button)
        _launlation.update({"自定义 Java 路径": custom_button})

        # 设置默认选中
        self.java_button_group.set_selected_button(_launlation.get(self.settings_manager.get_setting("java.name", '使用推荐的 Java 版本')))
        self.java_button_group.button_selected.connect(lambda item: self.on_java_changed(item))
        return content

    def create_custom_java_button(self):
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
        title_label.setFont(QFont("Source Han Sans CN", 11))
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

    def create_launcher_visibility(self):
        """启动器可见性"""
        content = QWidget()
        content.setStyleSheet("background-color: transparent;")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # 启动器可见性
        self.launcher_visibility_combo = QMComboBox(self)
        self.launcher_visibility_combo.addItems([
            VisibilitySettings.KEEP_VISIBLE,
            VisibilitySettings.MINIMIZE,
            VisibilitySettings.HIDE,
            VisibilitySettings.CLOSE
        ])
        self.launcher_visibility_combo.currentTextChanged.connect(
            lambda t: self.on_setting_changed("launcher.visibility", t)
        )
        # 默认选择选项 设置当前选中的选项
        visibility = self.settings_manager.get_setting("launcher.visibility", "游戏启动后保持不变")
        index = self.launcher_visibility_combo.findText(visibility)
        if index >= 0:
            self.launcher_visibility_combo.setCurrentIndex(index)

        layout.addWidget(self.launcher_visibility_combo)

        panel = CollapsePanel(self, '启动器可见性', None, is_collaspe=False, header_height=50)
        panel.set_content(content)
        return panel

    def create_minecraft_resolution(self):
        """设置游戏窗口分辨率"""
        content = QWidget()
        content.setStyleSheet("background-color: transparent;")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # 启动器可见性
        self.minecraft_resolution = QMComboBox(self)
        self.minecraft_resolution.addItems(["默认", "与启动器一致", "最大化"])
        self.minecraft_resolution.currentTextChanged.connect(
            lambda t: self.on_setting_changed("launcher.window_size", t)
        )
        # 默认选择选项 设置当前选中的选项
        visibility = self.settings_manager.get_setting("launcher.window_size", "默认")
        index = self.minecraft_resolution.findText(visibility)
        if index >= 0:
            self.minecraft_resolution.setCurrentIndex(index)

        layout.addWidget(self.minecraft_resolution)
        panel = CollapsePanel(self, '游戏窗口分辨率', None, is_collaspe=False, header_height=50)
        panel.set_content(content)
        return panel

    def create_process_priority(self):
        """进程优先级"""
        content = QWidget()
        content.setStyleSheet("background-color: transparent;")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # 创建按钮组
        _launlation = {}
        button_group = QMRadioGroup()
        button_group.button_selected.connect(lambda t: self.on_setting_changed("launcher.process_priority", t))

        # 选择选项
        for item, desc in [
            ('游戏性能优先', '为游戏分配最多系统资源，获得最佳游戏体验。可能影响其他程序运行'),
            ('平衡模式', '系统资源合理分配。推荐大多数情况使用'),
            ('系统流畅优先', '优先保证其他程序运行。可能影响游戏性能')
        ]:
            default_button = QMRadioButton(
                self,
                item, desc,
                data_property=item,
                text_max_heiht=100,
                messages_max_heiht=420
            )
            layout.addWidget(default_button)
            button_group.add_button(default_button)
            _launlation.update({item: default_button})

        # 设置默认选中
        button_group.set_selected_button(_launlation.get(self.settings_manager.get_setting("launcher.process_priority", '平衡模式')))
    
        panel = CollapsePanel(self, '进程优先级', '系统将优先处理游戏进程，减少卡顿和延迟，提供最佳游戏性能', True)
        panel.set_content(content)
        return panel
    
    def create_minecraft_debug(self):
        """游戏调试模式"""
        content = QWidget()
        content.setStyleSheet("background-color: transparent;")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # 创建按钮组
        _launlation = {}
        button_group = QMRadioGroup()
        button_group.button_selected.connect(lambda t: self.on_setting_changed("launcher.debug", t))

        # 选择选项
        for item, desc in [
            ('是', '启用游戏调试模式，显示详细的日志输出，可用于问题诊断'),
            ('否（推荐）', '禁用游戏调试模式，获得最佳游戏性能')
        ]:
            default_button = QMRadioButton(
                self,
                item,
                desc,
                data_property=item
            )
            layout.addWidget(default_button)
            button_group.add_button(default_button)
            _launlation.update({item: default_button})

        # 设置默认选中
        button_group.set_selected_button(_launlation.get(self.settings_manager.get_setting("launcher.debug", '否（推荐）')))
    
        panel = CollapsePanel(self, '游戏调试模式', '提供额外的诊断信息，用于问题排查和整合包开发测试。无特殊需求建议保持关闭状态', True)
        panel.set_content(content)
        return panel

    def load_java_path(self):
        """自动加载系统中Java路径"""

        # 在后台线程中执行搜索（避免阻塞UI）
        from PySide6.QtCore import QThread, Signal, QObject
        
        class JavaSearchWorker(QObject):
            finished = Signal(list)
            error = Signal(str)
            
            def run(self):
                try:
                    finder = JavaPathFinder()
                    java_installations = finder.find_all_java_installations()
                    self.finished.emit(java_installations)
                except Exception as e:
                    self.error.emit(str(e))
        
        # 创建和工作线程
        self.search_thread = QThread()
        self.worker = JavaSearchWorker()
        self.worker.moveToThread(self.search_thread)
        
        # 连接信号和槽
        self.search_thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.on_java_search_finished)
        self.worker.finished.connect(self.search_thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.error.connect(self.on_java_search_error)
        self.search_thread.finished.connect(self.search_thread.deleteLater)
        
        # 启动线程
        self.search_thread.start()

    def auto_search_java(self):
        """自动选择Java"""
        java_avail = self.settings_manager.get_setting("java.installations", [])
        finder = JavaPathFinder()
        best_java = finder.recommend_best_java(java_avail)

        self.settings_manager.set_setting("java.name", '使用推荐的 Java 版本')
        self.settings_manager.set_setting("java.path", best_java)
        self.settings_manager.save_settings()
        self.java_panel.set_messages(best_java)

    def is_disabled(self, disabled):
        """是否启用独立版本设置，启用后取消其他设置项的禁用状态"""
        self.disabled = disabled
        version = self.settings_manager.get_setting('minecraft.version.enable')
        if version is not None:
            self.on_setting_changed(f"minecraft.version_setting.{version}.enable", disabled)
        
        # 设置ui状态
        self.version_isolation.set_disabled(self.disabled)
        self.java_panel.set_disabled(self.disabled)
        self.minecraft_free.set_disabled(self.disabled)
        self.launcher_visibility.set_disabled(self.disabled)
        self.launcher_resolution.set_disabled(self.disabled)
        self.minecraft_process_priority.set_disabled(self.disabled)
        self.minecraft_debug.set_disabled(self.disabled)


    def on_setting_changed(self, key: str, value: Any):
        """处理设置改变，更新配置管理器并保存"""
        # 更新配置管理器
        self.settings_manager.set_setting(key, value)
        self.settings_manager.save_settings()
    
    def on_isolate_selected(self, proprty):
        """处理自动选择标签点击事件"""
        print('处理自动选择标签点击事件', proprty)
        self.settings_manager.set_setting("minecraft.isolation", proprty)
        self.settings_manager.save_settings()

    def on_java_changed(self, java):
        """"""
        if isinstance(java, tuple):
            name, path = java
            self.java_panel.set_messages(name)
            self.settings_manager.set_setting("java.name", name)
            self.settings_manager.set_setting("java.path", path)
            self.settings_manager.save_settings()
        elif isinstance(java, str) and java == 'auto':
            """自动选择"""
            self.java_panel.set_messages('请稍后，正在搜索...')
            self.auto_search_java()
        elif isinstance(java, str) and java == 'auto':
            """手动选择"""
            self.java_panel.set_messages(java)
            # self.auto_search_java()

    def clear_java_options(self):
        """清除现有的Java选项 - 在主线程中执行"""
        # 移除所有子部件
        layout = self.java_panel.content.layout()
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        
        self.java_button_group.button_selected.disconnect()

    def add_java_options(self, java_installations):
        """添加Java选项 - 在主线程中执行"""
        # 创建自动选择按钮
        self.java_auto_button = QMRadioButton(
            self,
            "使用推荐的 Java 版本",
            "系统将自动选择最适合的 Java 版本",
            data_property='auto'
        )
        self.java_panel.content.layout().addWidget(self.java_auto_button)
        self.java_button_group.add_button(self.java_auto_button)
        
        # 添加找到的Java版本
        for java_path, version in java_installations:
            if version in ['未知版本']:
                continue
        
            # 创建单选按钮
            java_button = QMRadioButton(
                self,
                f"Java {version}",
                f"路径: {java_path}",
                data_property=java_path
            )
            self.java_panel.content.layout().addWidget(java_button)
            self.java_button_group.add_button(java_button)
        
        # 自定义选项
        custom_button = QMRadioButton(
            self,
            "自定义 Java 路径",
            None,
            data_property='custom',
            slot_desc=self.create_custom_java_button()
        )
        self.java_panel.content.layout().addWidget(custom_button)
        self.java_button_group.add_button(custom_button)

        # 设置默认选中
        self.java_button_group.set_selected_button(self.java_auto_button)
        self.java_button_group.button_selected.connect(lambda item: self.on_java_changed(item))

    def on_java_search_finished(self, java_installations):
        """Java搜索完成处理"""
        self.clear_java_options()

        # 添加新的Java路径选项
        self.add_java_options(java_installations)

        self.settings_manager.set_setting('java.installations', java_installations)
        self.settings_manager.save_settings()

        # 自动选择推荐的Java
        finder = JavaPathFinder()
        best_java = finder.recommend_best_java(java_installations)
        self.java_panel.set_messages(best_java)

    def on_java_search_error(self, error_message):
        """Java搜索错误处理"""
        print("搜索出错", f"错误信息: {error_message}")

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
