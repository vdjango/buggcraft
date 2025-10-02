# 设置页面

import os
from typing import Any

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QFrame, QPushButton, QStackedWidget, QLineEdit, QComboBox, QSlider,
    QRadioButton, QButtonGroup, QScrollArea, QFormLayout, QSpacerItem, QSizePolicy
)
from PySide6.QtGui import QFont, QPixmap, QPainter, QIcon
from PySide6.QtCore import Qt, Signal, QSize
from .base_page import BasePage
from utils.helpers import MemorySliderManager
from config.settings import get_settings_manager
from config.javafinder import JavaPathFinder
from core.visibility import VisibilitySettings
from ui.widgets.collapse import CollapsePanel

import logging
logger = logging.getLogger(__name__)



class SettingsPage(BasePage):
    """设置页面 - 继承BasePage"""
    
    # 定义信号
    settings_changed = Signal(str, object)  # 设置改变信号，参数为设置键和值
    
    def __init__(self, parent=None, config_path=None, resource_path=None, scale_ratio=1.0, ):
        super().__init__(parent, config_path, resource_path, scale_ratio)
        # self.settings_manager = get_settings_manager(self.parent.config_path)  # 获取配置管理器
        
        self.init_ui()
        # self.load_settings_to_ui()  # 加载设置 - 方法不存在，暂时注释
        self.load_cache_settings()  # 加载缓存设置

    def on_page_activate(self):
        """当页面被激活时调用"""
        print("设置页面被激活")
    
    def on_page_deactivate(self):
        """当页面被隐藏时调用"""
        print("设置页面被隐藏")

    def create_scaled_icon(self, icon_name, size=(20, 20)):
        """
        创建缩放后的图标
        
        Args:
            icon_name: 图标文件名 
            size: 目标尺寸 
            
        Returns:
            QIcon: 缩放后的图标对象
        """
        from PySide6.QtGui import QIcon
        
        icon_path = os.path.join(self.resource_path, 'images', 'version', icon_name)
        
        if os.path.exists(icon_path):
            pixmap = QPixmap(icon_path)
            if not pixmap.isNull():
                scaled_pixmap = pixmap.scaled(size[0], size[1], Qt.KeepAspectRatio, Qt.SmoothTransformation)
                return QIcon(scaled_pixmap)
        
        # 如果图标不存在，返回空图标
        return QIcon()
        
    def init_ui(self):
        """初始化UI"""
        # 创建主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 创建选项卡容器
        self.tab_container = QWidget()
        tab_container_layout = QHBoxLayout(self.tab_container)
        tab_container_layout.setContentsMargins(15, 0, 15, 0)

        # 创建选项卡按钮区域
        self.tab_buttons_widget = self.create_tab_buttons()

        # 创建选项卡内容区域
        self.tab_content = QWidget()
        self.tab_content.setFixedWidth(926 - 178 - 62)
        self.tab_content.setContentsMargins(25, 0, 25, 0)

        tab_container_layout.addWidget(self.tab_buttons_widget)
        tab_container_layout.addSpacing(23)
        tab_container_layout.addWidget(self.tab_content)

        main_layout.addWidget(self.tab_container)
        
        # tab_content设置布局
        tab_content_layout = QVBoxLayout(self.tab_content)
        tab_content_layout.setContentsMargins(0, 0, 0, 0)
        tab_content_layout.setSpacing(0)
        
        # 右侧设置内容
        self.settings_stack = QStackedWidget()
        self.settings_stack.setContentsMargins(0, 5, 0, 5) 
        tab_content_layout.addWidget(self.settings_stack)
        
        # 添加设置页面
        self.create_launch_settings()
        self.create_java_management()
        self.create_download_settings()
        self.create_about_settings()
        
        # 设置初始状态：通用设置默认选中
        self.update_tab_button_style("通用设置", True)
        self.update_tab_button_style("Java管理", False)
        self.update_tab_button_style("下载", False)
        self.update_tab_button_style("关于", False)

    def create_tab_buttons(self):
        """创建选项卡按钮区域  """
        tab_buttons_widget = QWidget()
        tab_buttons_widget.setFixedWidth(178)
        tab_buttons_widget.setContentsMargins(0, 0, 0, 0)   
        tab_buttons_layout = QVBoxLayout(tab_buttons_widget)
        tab_buttons_layout.setContentsMargins(0, 0, 0, 0)
        tab_buttons_layout.addSpacing(20)   

        # 创建紫色分隔线
        shared_separator = QFrame()
        shared_separator.setFrameShape(QFrame.HLine)
        shared_separator.setStyleSheet("background-color: rgba(139, 133, 218, 1);")
        shared_separator.setFixedWidth(155)
        shared_separator.setFixedHeight(2)
        tab_buttons_layout.addWidget(shared_separator, 0, Qt.AlignCenter)
        tab_buttons_layout.addSpacing(10)
        
        # 通用设置按钮
        self.general_tab_btn = self.create_tab_button(
            "通用设置",
            self.general_tab_btn_clicked,
            size=(155, 44), font_size=10
        )
        tab_buttons_layout.addWidget(self.general_tab_btn, 0, Qt.AlignCenter)
        
        # Java管理按钮
        self.java_tab_btn = self.create_tab_button(
            "Java管理",
            self.java_tab_btn_clicked,
            size=(155, 44), font_size=10
        )
        tab_buttons_layout.addWidget(self.java_tab_btn, 0, Qt.AlignCenter)
        
        # 下载按钮
        self.download_tab_btn = self.create_tab_button(
            "下载",
            self.download_tab_btn_clicked,
            size=(155, 44), font_size=10
        )
        tab_buttons_layout.addWidget(self.download_tab_btn, 0, Qt.AlignCenter)
        
        # 关于按钮
        self.about_tab_btn = self.create_tab_button(
            "关于",
            self.about_tab_btn_clicked,
            size=(155, 44), font_size=10
        )
        tab_buttons_layout.addWidget(self.about_tab_btn, 0, Qt.AlignCenter)
        tab_buttons_layout.addStretch()
        
        # 设置初始状态：通用设置默认选中
        self.update_tab_button_style("通用设置", True)
        
        return tab_buttons_widget

    def create_tab_button(self, text, click_handler, size=(155, 44), font_size=12):
        """创建选项卡按钮 """
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

    def update_tab_button_style(self, tab_name, is_active):
        """更新选项卡按钮样式 """
        if tab_name == "通用设置":
            btn = self.general_tab_btn
        elif tab_name == "Java管理":
            btn = self.java_tab_btn
        elif tab_name == "下载":
            btn = self.download_tab_btn
        elif tab_name == "关于":
            btn = self.about_tab_btn
        else:
            return
            
        active_image = os.path.join(self.resource_path, 'images', 'user', 'external_tab_btn_active.png')
        
        if is_active and os.path.exists(active_image):
            btn.setPixmap(QPixmap(active_image).scaled(155, 44, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
        else:
            btn.clear()
            btn.setStyleSheet("background-color: transparent;")

    # 按钮点击事件处理函数
    def general_tab_btn_clicked(self):
        """通用设置按钮点击事件"""
        self.settings_stack.setCurrentIndex(0)
        self.update_tab_button_style("通用设置", True)
        self.update_tab_button_style("Java管理", False)
        self.update_tab_button_style("下载", False)
        self.update_tab_button_style("关于", False)

    def java_tab_btn_clicked(self):
        """Java管理按钮点击事件"""
        self.settings_stack.setCurrentIndex(1)
        self.update_tab_button_style("通用设置", False)
        self.update_tab_button_style("Java管理", True)
        self.update_tab_button_style("下载", False)
        self.update_tab_button_style("关于", False)

    def download_tab_btn_clicked(self):
        """下载按钮点击事件"""
        self.settings_stack.setCurrentIndex(2)
        self.update_tab_button_style("通用设置", False)
        self.update_tab_button_style("Java管理", False)
        self.update_tab_button_style("下载", True)
        self.update_tab_button_style("关于", False)

    def about_tab_btn_clicked(self):
        """关于按钮点击事件"""
        self.settings_stack.setCurrentIndex(3)
        self.update_tab_button_style("通用设置", False)
        self.update_tab_button_style("Java管理", False)
        self.update_tab_button_style("下载", False)
        self.update_tab_button_style("关于", True)
    
    def create_launch_settings(self):
        """创建通用设置设置页面"""
        # 创建滚动区域以容纳所有设置
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

        import os
        from ui.widgets.card.qmcard import QMCard
        from ui.widgets.slider import StepSlider

        main_layout = QWidget()
        main_layout.setStyleSheet("background-color: transparent;")

        layout = QVBoxLayout(main_layout)
        layout.setSpacing(10)   
        layout.setContentsMargins(15, 15, 15, 15)   
        
        # 启动器更新 区域 - 使用可复用的CollapsePanel
        update_container = QWidget()
        update_container_layout = QVBoxLayout(update_container)
        update_container_layout.setContentsMargins(0, 0, 0, 0)
        update_container_layout.setSpacing(0)  
        
        # 创建版本选择内容组件
        version_content_widget = self.create_version_selection_content()
        
        # 创建刷新按钮组件
        refresh_btn = QPushButton()
        refresh_btn.setFixedSize(20, 20)
        
        # 加载刷新图标
        reload_icon_path = os.path.join(self.resource_path, 'settings', 'reload.png')
        if os.path.exists(reload_icon_path):
            reload_pixmap = QPixmap(reload_icon_path)
            if not reload_pixmap.isNull():
                # 使用现有的压缩方法将图片调整为20x20大小
                scaled_pixmap = reload_pixmap.scaled(20, 20, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                refresh_btn.setIcon(QIcon(scaled_pixmap))
                refresh_btn.setIconSize(QSize(20, 20))
                print(f"成功加载图片: {reload_icon_path}")
            else:
                print(f"图片加载失败，pixmap为空: {reload_icon_path}")
                refresh_btn.setText("@")
        else:
            # 如果图片不存在，直接使用文字 "@" 作为图标
            print(f"图片文件不存在: {reload_icon_path}")
            refresh_btn.setText("@")
        
        refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: none;
                border-radius: 10px;
            }
            QPushButton:hover {
                background-color: rgba(90, 90, 90, 0.3);
            }
        """)
        
        # 使用CollapsePanel 折叠面板，并传入刷新按钮
        self.update_collapse_panel = CollapsePanel(
            parent=self,
            title="启动器更新",   
            messages="发现更新 最新版本为：3.6.17",
            content=version_content_widget,
            header_height=60,
            content_height=90,  
            expand_icon_size=16,
            text_font_size=12,
            messages_font_size=11,
            is_collaspe=True,
            custom_button=refresh_btn
        )
        
        # 连接折叠状态变化信号来控制分割线显示
        self.update_collapse_panel.collapse_changed.connect(self.on_collapse_changed)
        
        # 直接添加CollapsePanel到主布局，不使用水平布局
        layout.addWidget(self.update_collapse_panel)

        # 2. 文件下载缓存区域 - 使用CollapsePanel
        
        # 创建缓存内容区域
        cache_content_widget = QWidget()
        cache_content_widget.setStyleSheet("""
            QWidget {
                background-color: transparent;
                border: none;
            }
        """)
        
        cache_content_layout = QVBoxLayout(cache_content_widget)
        cache_content_layout.setContentsMargins(16, 2, 16, 10)  
        cache_content_layout.setSpacing(8)
        
        # 默认缓存选项
        default_cache_layout = QHBoxLayout()
        
        # 构建选中和未选中状态图片的完整路径
        selected_image_path = os.path.join(self.resource_path, 'images', 'version', 'selected1.png')
        unselected_image_path = os.path.join(self.resource_path, 'images', 'version', 'not-selected1.png')
        # 将反斜杠替换为正斜杠，Qt在Windows上也支持正斜杠
        selected_image_path = selected_image_path.replace('\\', '/')
        unselected_image_path = unselected_image_path.replace('\\', '/')
        
        self.default_cache_checkbox = QRadioButton("默认")
        self.default_cache_checkbox.setChecked(True)
        self.default_cache_checkbox.setStyleSheet(f"""
            QRadioButton {{
                color: #FFFFFF;
                font-size: 12px;
                spacing: 10px;
                background-color: transparent;
            }}
            QRadioButton::indicator {{
                width: 20px;
                height: 20px;
            }}
            QRadioButton::indicator:unchecked {{
                image: url({unselected_image_path});
            }}
            QRadioButton::indicator:checked {{
                image: url({selected_image_path});
            }}
        """)
        
        default_path_label = QLabel("(%APPDATA%/.minecraft或~/.minecraft)")
        default_path_label.setStyleSheet("""
            QLabel {
                color: #AAAAAA;
                font-size: 13px;
                background-color: transparent;
                padding-left: 10px;
            }
        """)
        
        default_cache_layout.addWidget(self.default_cache_checkbox, 0, Qt.AlignLeft)
        default_cache_layout.addWidget(default_path_label, 0, Qt.AlignLeft)
        default_cache_layout.addStretch()
        
        # 自定义缓存选项
        custom_cache_layout = QHBoxLayout()
        self.custom_cache_checkbox = QRadioButton("自定义")
        self.custom_cache_checkbox.setStyleSheet(f"""
            QRadioButton {{
                color: #FFFFFF;
                font-size: 12px;
                spacing: 10px;
                background-color: transparent;
            }}
            QRadioButton::indicator {{
                width: 16px;
                height: 16px;
            }}
            QRadioButton::indicator:unchecked {{
                border: 1px solid #FFFFFF;
                background-color: #000000;
                border-radius: 0px;
                background-image: url({unselected_image_path});
                background-repeat: no-repeat;
                background-position: center;
            }}
            QRadioButton::indicator:checked {{
                border: none;
                background-color: transparent;
                image: url({selected_image_path});
                border-radius: 0px;
            }}
        """)
        
        self.custom_cache_path = QLineEdit("C:\\Users\\Administrator\\Documents\\WXWork\\1688858218")
        self.custom_cache_path.setStyleSheet("""
            QLineEdit {
                background-color: #2A2A2A;
                border: 1px solid #555555;
                border-radius: 4px;
                color: #FFFFFF;
                font-size: 13px;
                padding: 4px 8px;
                min-width: 200px;
            }
            QLineEdit:focus {
                border-color: #0078D4;
            }
        """)
        
        # 构建folder图标的完整路径
        folder_icon_path = os.path.join(self.resource_path, 'images', 'version', 'folder.png')
        folder_icon_path = folder_icon_path.replace('\\', '/')
        
        browse_btn = QPushButton()
        browse_btn.setFixedSize(28, 28)
        browse_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                border: none;
                border-radius: 4px;
                background-image: url({folder_icon_path});
                background-repeat: no-repeat;
                background-position: center;
            }}
            QPushButton:hover {{
                background-color: rgba(255, 255, 255, 0.1);
            }}
            QPushButton:pressed {{
                background-color: rgba(255, 255, 255, 0.2);
            }}
        """)
        # 连接浏览按钮点击事件
        browse_btn.clicked.connect(self.browse_custom_cache_path)
        
        custom_cache_layout.addWidget(self.custom_cache_checkbox, 0, Qt.AlignLeft)
        custom_cache_layout.addWidget(self.custom_cache_path, 0, Qt.AlignLeft)
        custom_cache_layout.addWidget(browse_btn, 0, Qt.AlignLeft)
        custom_cache_layout.addStretch()
        
        cache_content_layout.addLayout(default_cache_layout)
        cache_content_layout.addLayout(custom_cache_layout)
        
        # 创建缓存选项的按钮组（互斥选择）
        self.cache_button_group = QButtonGroup()
        self.cache_button_group.addButton(self.default_cache_checkbox)
        self.cache_button_group.addButton(self.custom_cache_checkbox)
        
        # 连接单选框状态变化事件
        self.default_cache_checkbox.toggled.connect(self.on_cache_option_changed)
        self.custom_cache_checkbox.toggled.connect(self.on_cache_option_changed)
        
        # 获取当前缓存路径用于显示
        current_cache_path = self.get_default_cache_path()
        
        # 使用CollapsePanel 折叠面板
        self.cache_collapse_panel = CollapsePanel(
            parent=self,
            title="文件下载缓存",
            messages=current_cache_path,
            content=cache_content_widget,
            header_height=60,
            content_height=90,
            expand_icon_size=16,
            text_font_size=12,
            messages_font_size=11
        )
        
        # 创建包含分割线的容器
        cache_collapse_container = QWidget()
        cache_collapse_container_layout = QVBoxLayout(cache_collapse_container)
        cache_collapse_container_layout.setContentsMargins(0, 0, 0, 0)
        cache_collapse_container_layout.setSpacing(0)
        
        # 添加CollapsePanel的header
        cache_collapse_container_layout.addWidget(self.cache_collapse_panel.header)
        

        
        # 添加CollapsePanel的content
        cache_collapse_container_layout.addWidget(self.cache_collapse_panel.content)
        
        # 连接折叠状态变化信号来控制分割线显示
        self.cache_collapse_panel.collapse_changed.connect(self.on_cache_collapse_changed)
        
        # 创建主布局，直接添加CollapsePanel容器
        cache_main_layout = QVBoxLayout()
        cache_main_layout.setContentsMargins(13, 0, 0, 0)   
        cache_main_layout.setSpacing(0)
        
        cache_main_layout.addWidget(cache_collapse_container)
        
        # 添加到下载页面布局
        cache_container = QWidget()
        cache_container_layout = QVBoxLayout(cache_container)
        cache_container_layout.setContentsMargins(0, 0, 0, 0)   
        cache_container_layout.setSpacing(0)
        cache_container_layout.addLayout(cache_main_layout)
        
        layout.addWidget(cache_container)

        # 3. 语言设置区域 - 使用CollapsePanel组件
        
        language_content_widget = QWidget()
        language_content_widget.setStyleSheet("""
            QWidget {
                background-color: transparent;
                border: none;
            }
        """)
        
        language_content_layout = QVBoxLayout(language_content_widget)
        language_content_layout.setContentsMargins(16, 0, 16, 10)  
        language_content_layout.setSpacing(0)
        
        # 创建"跟随系统语言"选择框布局（作为二级标题）
        follow_system_layout = QHBoxLayout()
        follow_system_layout.setContentsMargins(0, 0, 0, 0)
        follow_system_layout.setSpacing(0)
        
        # 语言选择下拉框
        self.language_combo = QComboBox()
        self.language_combo.addItems(["跟随系统语言", "简体中文", "繁体中文", "English"])
        self.language_combo.setCurrentText("跟随系统语言")  # 默认选中跟随系统语言
        self.language_combo.setFixedSize(140, 29)   
        self.language_combo.setStyleSheet("""
            QComboBox {
                background-color: transparent;
                color: #FFFFFF;
                border: 1px solid #555555;
                border-radius: 4px;
                padding: 2px 8px;
                font-size: 11px;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox::down-arrow {
                image: url(resources/icons/dropdown_arrow.png);
                width: 12px;
                height: 12px;
            }
            QComboBox QAbstractItemView {
                background-color: #2A2A2A;
                color: #FFFFFF;
                border: 1px solid #555555;
                selection-background-color: #3A3A3A;
                font-size: 13px;
            }
        """)
        
        follow_system_layout.addWidget(self.language_combo, 0, Qt.AlignLeft)
        follow_system_layout.addStretch()
        
        language_content_layout.addLayout(follow_system_layout)
        
        # 创建CollapsePanel
        self.language_collapse_panel = CollapsePanel(
            parent=self,
            title="语言(重启后生效)",
            content=language_content_widget,
            header_height=60,
            content_height=50,
            expand_icon_size=16,
            text_font_size=12,
            messages_font_size=11
        )
        
        # 设置宽度
        # 连接折叠状态变化信号
        self.language_collapse_panel.collapse_changed.connect(self.on_language_collapse_changed)
        
        # 连接语言选择变化信号
        self.language_combo.currentTextChanged.connect(self.on_language_changed)
        
        # 创建语言设置的主布局
        language_main_layout = QVBoxLayout()
        language_main_layout.setContentsMargins(15, 15, 15, 15)
        language_main_layout.setSpacing(10)
        
        # 直接添加CollapsePanel
        language_main_layout.addWidget(self.language_collapse_panel)
        language_main_layout.addStretch()
        
        # 添加到语言页面布局
        language_container = QWidget()
        language_container_layout = QVBoxLayout(language_container)
        language_container_layout.setContentsMargins(0, 0, 0, 0)
        language_container_layout.setSpacing(0)
        language_container_layout.addLayout(language_main_layout)
        
        layout.addWidget(language_container)

        # 4. 下载源设置区域 - 使用CollapsePanel重新设计
        
        # 创建下载源内容区域
        download_source_content_widget = QWidget()
        download_source_content_widget.setStyleSheet("""
            QWidget {
                background-color: transparent;
                border: none;
            }
        """)
        
        download_source_content_layout = QVBoxLayout(download_source_content_widget)
        download_source_content_layout.setContentsMargins(16, 10, 16, 10)
        download_source_content_layout.setSpacing(8)
        
        # 1. 版本列表源区域（第一行）
        version_source_layout = QHBoxLayout()
        
        # 添加"版本列表源:"标题标签
        version_source_title_label = QLabel("版本列表源:")
        version_source_title_label.setStyleSheet("""
            QLabel {
                color: #FFFFFF;
                font-size: 12px;
                background-color: transparent;
            }
        """)
        
        # 内嵌下拉选择框
        self.version_source_combo = QComboBox()
        self.version_source_combo.addItems(["选择加载速度快的下载源（平衡，但可能不是最新）", "选择最新版本源", "自定义源"])
        self.version_source_combo.setCurrentText("选择加载速度快的下载源（平衡，但可能不是最新）")
        self.version_source_combo.setFixedSize(280, 24)
        self.version_source_combo.setStyleSheet("""
            QComboBox {
                background-color: #4A90E2;
                border: 1px solid #4A90E2;
                border-radius: 0px;
                padding: 4px 8px;
                color: #FFFFFF;
                font-size: 11px;
            }
            QComboBox:hover {
                background-color: #5BA0F2;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 4px solid #FFFFFF;
                margin-right: 5px;
            }
            QComboBox QAbstractItemView {
                background-color: rgba(60, 60, 60, 0.95);
                border: 1px solid #555;
                selection-background-color: #4A90E2;
                color: #FFFFFF;
            }
        """)
        
        version_source_layout.addWidget(version_source_title_label, 0, Qt.AlignLeft)
        version_source_layout.addSpacing(10)   
        version_source_layout.addWidget(self.version_source_combo, 0, Qt.AlignLeft)
        version_source_layout.addStretch()
        download_source_content_layout.addLayout(version_source_layout)
        
        # 2. 具体下载源信息区域（第二行）
        bmclapi_layout = QHBoxLayout()
        
        # 添加"下载源:"标题标签
        download_source_title_label = QLabel("下载源:")
        download_source_title_label.setStyleSheet("""
            QLabel {
                color: #FFFFFF;
                font-size: 12px;
                background-color: transparent;
            }
        """)
        
        bmclapi_label = QLabel('BMCLAPI(bangbang93, <a href="https://bmclapi2.bangbang93.com" style="color: #4A90E2; text-decoration: none;">https://bmclapi2.bangbang93.com</a>)')
        bmclapi_label.setStyleSheet("""
            QLabel {
                color: #AAAAAA;
                font-size: 11px;
                background-color: transparent;
            }
        """)
        bmclapi_label.setOpenExternalLinks(True)  # 允许打开外部链接
        
        bmclapi_layout.addWidget(download_source_title_label, 0, Qt.AlignLeft)
        bmclapi_layout.addSpacing(10)  
        bmclapi_layout.addWidget(bmclapi_label, 0, Qt.AlignLeft)
        bmclapi_layout.addStretch()
        download_source_content_layout.addLayout(bmclapi_layout)
        
        # 构建选中和未选中状态图片的完整路径
        selected_image_path = os.path.join(self.resource_path, 'images', 'version', 'selected1.png')
        unselected_image_path = os.path.join(self.resource_path, 'images', 'version', 'not-selected1.png')
        selected_image_path = selected_image_path.replace('\\', '/')
        unselected_image_path = unselected_image_path.replace('\\', '/')
        
        # 创建自动选择下载源的单选框
        self.header_auto_select_checkbox = QRadioButton("自动选择下载源")
        self.header_auto_select_checkbox.setChecked(True)
        self.header_auto_select_checkbox.setStyleSheet(f"""
            QRadioButton {{
                color: #FFFFFF;
                font-size: 12px;
                font-weight: bold;
                spacing: 10px;
                background-color: transparent;
            }}
            QRadioButton::indicator {{
                width: 16px;
                height: 16px;
            }}
            QRadioButton::indicator:unchecked {{
                border: 1px solid #FFFFFF;
                background-color: #000000;
                border-radius: 0px;
                background-image: url({unselected_image_path});
            }}
            QRadioButton::indicator:checked {{
                border: 1px solid #FFFFFF;
                background-color: #000000;
                border-radius: 0px;
                image: url({selected_image_path});
            }}
        """)
        
        # 将单选框添加到内容区域的顶部
        auto_select_layout = QHBoxLayout()
        auto_select_layout.setContentsMargins(0, 0, 0, 0)
        auto_select_layout.setSpacing(0)
        auto_select_layout.addWidget(self.header_auto_select_checkbox, 0, Qt.AlignLeft | Qt.AlignVCenter)
        auto_select_layout.addStretch()
        
        # 在内容区域顶部插入单选框
        download_source_content_layout.insertLayout(0, auto_select_layout)
        
        # 使用CollapsePanel 折叠面板
        self.download_source_collapse_panel = CollapsePanel(
            parent=self,
            title="下载源",
            content=download_source_content_widget,
            header_height=60,
            content_height=140,  
            expand_icon_size=16,
            text_font_size=12,
            messages_font_size=11
        )
        
        # 连接折叠状态变化信号来控制分割线显示
        self.download_source_collapse_panel.collapse_changed.connect(self.on_download_source_collapse_changed)
        
        # 创建下载源设置的主布局
        download_source_main_layout = QVBoxLayout()
        download_source_main_layout.setContentsMargins(15, 15, 15, 15)
        download_source_main_layout.setSpacing(10)
        
        # 直接添加CollapsePanel
        download_source_main_layout.addWidget(self.download_source_collapse_panel)
     
        download_source_main_layout.addStretch(1)
        
        # 添加到下载页面布局
        download_source_container = QWidget()
        download_source_container_layout = QVBoxLayout(download_source_container)
        download_source_container_layout.setContentsMargins(0, 0, 0, 0)  
        download_source_container_layout.setSpacing(0)
        download_source_container_layout.addLayout(download_source_main_layout)
        
        layout.addWidget(download_source_container)
        
        # 增加底部空间，为展开内容提供足够空间
        spacer_after_download_source = QSpacerItem(0, 200, QSizePolicy.Minimum, QSizePolicy.Expanding)
        layout.addItem(spacer_after_download_source)
       


        # 设置滚动区域的内容
        scroll_area.setWidget(main_layout)
        
        scroll_area.setMinimumHeight(500)   
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)  
        
        # 创建容器页面
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)  # 移除页面边距，让滚动条贴近右边 
        page_layout.addWidget(scroll_area)
        self.settings_stack.addWidget(page)

    def create_java_management(self):
        """创建Java管理页面"""
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setStyleSheet("background-color: transparent;")

        import os
        from ui.widgets.card.qmcard import QMCard

        main_layout = QWidget()
        main_layout.setStyleSheet("background-color: transparent;")
        layout = QVBoxLayout(main_layout)
        
        # Java管理卡片
        java_card = QMCard(
            title="Java管理",
            icon=os.path.join(self.resource_path, "icons/union@2x.png")
        )
        java_card.setStyleSheet("background-color: transparent;")
        java_card.setBackgroundColor("rgba(50, 50, 50, 0.68)")
        java_card.setStyleSheet("""
            QWidget {
                color: #AFAFAF;
            }
        """)
        
        # Java路径设置
        java_layout = QFormLayout()
        java_path_label = QLabel("Java路径:")
        java_path_label.setStyleSheet("color: #AFAFAF; font-weight: bold;")
        
        self.java_path_input = QLineEdit()
        self.java_path_input.setStyleSheet("""
            QLineEdit {
                background-color: rgba(60, 60, 60, 0.8);
                color: #FFFFFF;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 8px;
                font-size: 12px;
            }
        """)
        
        java_browse_btn = QPushButton("浏览")
        java_browse_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(120, 89, 255, 0.8);
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: rgba(120, 89, 255, 1.0);
            }
        """)
        
        java_layout.addRow(java_path_label, self.java_path_input)
        java_layout.addRow("", java_browse_btn)
        
        java_card.add_layout(java_layout)
        layout.addWidget(java_card)
        layout.addStretch()
        
        scroll_area.setWidget(main_layout)
        return scroll_area

    def create_download_settings(self):
        """创建下载设置页面"""
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setStyleSheet("background-color: transparent;")

        import os
        from ui.widgets.card.qmcard import QMCard

        main_layout = QWidget()
        main_layout.setStyleSheet("background-color: transparent;")
        layout = QVBoxLayout(main_layout)
        
        # 下载设置卡片
        download_card = QMCard(
            title="下载设置",
            icon=os.path.join(self.resource_path, "icons/union@2x.png")
        )
        download_card.setStyleSheet("background-color: transparent;")
        download_card.setBackgroundColor("rgba(50, 50, 50, 0.68)")
        download_card.setStyleSheet("""
            QWidget {
                color: #AFAFAF;
            }
        """)
        
        # 下载源设置
        download_layout = QFormLayout()
        download_source_label = QLabel("下载源:")
        download_source_label.setStyleSheet("color: #AFAFAF; font-weight: bold;")
        
        self.download_source_combo = QComboBox()
        self.download_source_combo.addItems(["官方源", "镜像源1", "镜像源2"])
        self.download_source_combo.setStyleSheet("""
            QComboBox {
                background-color: rgba(60, 60, 60, 0.8);
                color: #FFFFFF;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 8px;
                font-size: 12px;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 5px solid #AFAFAF;
            }
        """)
        
        download_layout.addRow(download_source_label, self.download_source_combo)
        
        download_card.add_layout(download_layout)
        layout.addWidget(download_card)
        layout.addStretch()
        
        scroll_area.setWidget(main_layout)
        return scroll_area

    def create_about_settings(self):
        """创建关于页面"""
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setStyleSheet("background-color: transparent;")

        import os
        from ui.widgets.card.qmcard import QMCard

        main_layout = QWidget()
        main_layout.setStyleSheet("background-color: transparent;")
        layout = QVBoxLayout(main_layout)
        
        # 关于卡片
        about_card = QMCard(
            title="关于 BuggCraft",
            icon=os.path.join(self.resource_path, "icons/union@2x.png")
        )
        about_card.setStyleSheet("background-color: transparent;")
        about_card.setBackgroundColor("rgba(50, 50, 50, 0.68)")
        about_card.setStyleSheet("""
            QWidget {
                color: #AFAFAF;
            }
        """)
        
        # 关于信息
        about_layout = QVBoxLayout()
        
        version_label = QLabel("版本: 1.0.0")
        version_label.setStyleSheet("color: #FFFFFF; font-size: 14px; font-weight: bold;")
        
        description_label = QLabel("BuggCraft 是一个现代化的 Minecraft 启动器")
        description_label.setStyleSheet("color: #AFAFAF; font-size: 12px;")
        description_label.setWordWrap(True)
        
        author_label = QLabel("作者: BuggCraft Team")
        author_label.setStyleSheet("color: #AFAFAF; font-size: 12px;")
        
        about_layout.addWidget(version_label)
        about_layout.addWidget(description_label)
        about_layout.addWidget(author_label)
        
        about_card.add_layout(about_layout)
        layout.addWidget(about_card)
        layout.addStretch()
        
        scroll_area.setWidget(main_layout)
        return scroll_area

    def create_personalization_settings(self):
        """创建个性化设置页面"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # 标题
        title = QLabel("个性化设置 (开发中)")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #ffffff; margin-bottom: 20px;")
        layout.addWidget(title)
        
        layout.addStretch()
        self.settings_stack.addWidget(page)
    
    def create_other_settings(self):
        """创建其他设置页面"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # 标题
        title = QLabel("其他设置 (开发中)")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #ffffff; margin-bottom: 20px;")
        layout.addWidget(title)
        
        layout.addStretch()
        self.settings_stack.addWidget(page)
    
    def get_groupbox_style(self):
        """获取GroupBox的样式"""
        return """
            QGroupBox {
                color: #ffffff;
                font-weight: bold;
                border: 1px solid #555555;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 15px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
        """
    
    def show_launch_settings(self):
        """显示启动参数设置"""
        self.settings_stack.setCurrentIndex(0)
    
    def show_personalization(self):
        """显示个性化设置"""
        self.settings_stack.setCurrentIndex(1)
    
    def show_other_settings(self):
        """显示其他设置"""
        self.settings_stack.setCurrentIndex(2)

        
    def auto_search_java(self, java_path=None):
        """自动搜索Java安装"""
        # 显示搜索中状态
        if not java_path:
            self.auto_search_button.setEnabled(False)
            self.auto_search_button.setText("搜索中...")
        
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
        self.worker.finished.connect(lambda t: self.on_java_search_finished(t, java_path))
        self.worker.finished.connect(self.search_thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.error.connect(self.on_java_search_error)
        self.search_thread.finished.connect(self.search_thread.deleteLater)
        
        # 启动线程
        self.search_thread.start()

    def on_java_search_finished(self, java_installations, find_java):
        """Java搜索完成处理"""
        if not find_java:
            self.auto_search_button.setEnabled(True)
            self.auto_search_button.setText("自动搜索")
        
        if not java_installations:
            self.show_message("未找到Java安装", "请手动安装Java或指定Java路径")
            return
        
        # 更新Java选择下拉框
        current_count = self.game_java_combo.count()
        for i in range(current_count - 1, 0, -1): # 从后往前删，避免索引变化
            self.game_java_combo.removeItem(i)

        # 添加新的Java路径选项，并将路径设置为UserData
        java_data = []
        for java_path, version in java_installations: # 假设这是你的搜索结果
            logger.info(f'  -> {version} - {java_path}')
            java_data.append((version, java_path))
            self.game_java_combo.addItem(java_path, java_path) # 添加Item并设置UserData  version, 

        # 自动选择推荐的Java
        finder = JavaPathFinder()
        best_java = finder.recommend_best_java(java_installations)
        if find_java:
            best_java = finder.recommend_best_java([(find_java, find_java)])
        
        found_index = -1
        for i in range(1, self.game_java_combo.count()): # 从索引1开始，跳过提示项
            if self.game_java_combo.itemData(i) == best_java:
                found_index = i
                break

        if found_index != -1:
            self.game_java_combo.setCurrentIndex(found_index)
        else:
            logger.info("未找到对应的Java路径，可能需更新选项列表")
            # 可选：设置为“自动选择”或第一个可用选项
            self.game_java_combo.setCurrentIndex(0)

        self.show_message("搜索完成", f"找到 {len(java_installations)} 个Java安装")

    def on_java_search_error(self, error_message):
        """Java搜索错误处理"""
        self.auto_search_button.setEnabled(True)
        self.auto_search_button.setText("自动搜索")
        self.show_message("搜索出错", f"错误信息: {error_message}")

    def show_message(self, title, message):
        """显示消息（实现取决于你的UI框架）"""
        # 这里可以使用QMessageBox或你的自定义弹窗
        logger.info(f"{title}: {message}")
        

    def on_setting_changed(self, key: str, value: Any):
        """处理设置改变，更新配置管理器并保存"""
        # 更新配置管理器
        success = self.settings_manager.set_setting(key, value)
        if success:
            # 立即保存配置（或可以延迟保存以提高性能）
            self.settings_manager.save_settings()
            self.settings_changed.emit(key, value)
        else:
            logger.info(f"保存设置失败: {key} = {value}")
    
    def save_all_settings(self):
        """显式保存所有设置（可用于点击保存按钮时）"""
        # 这里可以添加一些验证逻辑
        success = self.settings_manager.save_settings()
        if success:
            logger.info("所有设置已保存")
        else:
            logger.info("保存设置失败")
           
            


    def paintEvent(self, event):
        """重绘事件 - 绘制背景图片与主窗口渲染方式一致"""
        if self.bg_image:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)
            
            widget_width = self.width()
            widget_height = self.height()
            
            scale_x = widget_width / self.bg_image.width()
            scale_y = widget_height / self.bg_image.height()
            scale = min(scale_x, scale_y)   
            
            scaled_width = int(self.bg_image.width() * scale)
            scaled_height = int(self.bg_image.height() * scale)
            
            x = (widget_width - scaled_width) // 2
            y = (widget_height - scaled_height) // 2
            
            scaled_pixmap = self.bg_image.scaled(
                scaled_width, scaled_height,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            painter.drawPixmap(x, y, scaled_pixmap)
        super().paintEvent(event)

    def create_version_selection_content(self):
        """
        创建版本选择内容组件
        返回包含版本选择功能的QWidget
        """
        content_widget = QWidget()
        content_widget.setStyleSheet("""
            QWidget {
                background-color: transparent;
            }
        """)
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(15, 5, 15, 8)  
        content_layout.setSpacing(5)  
        
        # 版本选择区域 - 第一行：稳定版和开发版选择
        version_selection_layout = QHBoxLayout()
        version_selection_layout.setContentsMargins(0, 0, 0, 0)
        version_selection_layout.setSpacing(20)  
        
        selected_image_path = os.path.join(self.resource_path, 'images', 'version', 'selected1.png')
        selected_image_path = selected_image_path.replace('\\', '/')
        
        # 稳定版选择框
        self.stable_version_checkbox = QRadioButton("稳定版")
        self.stable_version_checkbox.setStyleSheet(f"""
            QRadioButton {{
                color: #AFAFAF;
                font-size: 12px;
                spacing: 8px;
                background-color: transparent;
            }}
            QRadioButton::indicator {{
                width: 16px;
                height: 16px;
            }}
            QRadioButton::indicator:unchecked {{
                border: 1px solid #FFFFFF;
                background-color: #000000;
                border-radius: 0px;
            }}
            QRadioButton::indicator:checked {{
                border: none;
                background-color: transparent;
                image: url({selected_image_path});
                border-radius: 0px;
            }}
        """)
        
        # 开发版选择框
        self.dev_version_checkbox = QRadioButton("开发版")
        self.dev_version_checkbox.setStyleSheet(f"""
            QRadioButton {{
                color: #AFAFAF;
                font-size: 12px;
                spacing: 8px;
                background-color: transparent;
            }}
            QRadioButton::indicator {{
                width: 16px;
                height: 16px;
            }}
            QRadioButton::indicator:unchecked {{
                border: 1px solid #FFFFFF;
                background-color: #000000;
                border-radius: 0px;
            }}
            QRadioButton::indicator:checked {{
                border: none;
                background-color: transparent;
                image: url({selected_image_path});
                border-radius: 0px;
            }}
        """)
        self.dev_version_checkbox.setChecked(True)  
        
        # 创建按钮组确保单选
        self.version_button_group = QButtonGroup()
        self.version_button_group.addButton(self.stable_version_checkbox)
        self.version_button_group.addButton(self.dev_version_checkbox)
        
        version_selection_layout.addWidget(self.stable_version_checkbox)
        version_selection_layout.addWidget(self.dev_version_checkbox)
        version_selection_layout.addStretch()
        
        # 版本说明文字 - 第二行
        version_desc_label = QLabel("开发版与预览版包含更多的功能以及错误修复，但也可能会包含其他的问题。")
        version_desc_label.setStyleSheet("""
            QLabel {
                color: #AFAFAF;
                font-size: 11px;
                background-color: transparent;
                margin-top: 2px;
            }
        """)
        version_desc_label.setWordWrap(True)
        
        content_layout.addLayout(version_selection_layout)
        content_layout.addWidget(version_desc_label)        
        return content_widget
    
    def toggle_cache_details(self):
        """切换文件下载缓存详细信息的显示/隐藏"""
        self.cache_expanded = not self.cache_expanded
        self.cache_details_widget.setVisible(self.cache_expanded)
        
        # 更新按钮图标
        if self.cache_expanded:
            self.cache_expand_btn.setText("⌃")  # 向上箭头
        else:
            self.cache_expand_btn.setText("⌄")  # 向下箭头
    
    def on_collapse_changed(self, is_expanded):
        """处理CollapsePanel折叠状态变化"""
        pass
    
    def on_cache_collapse_changed(self, is_expanded):
        """处理缓存CollapsePanel折叠状态变化"""
        # 当展开时更新路径显示
        if is_expanded:
            self.update_cache_path_display()
    
    def on_language_collapse_changed(self, is_expanded):
        """处理语言CollapsePanel折叠状态变化"""
        pass
    
    def on_language_changed(self, text):
        """处理语言选择变化"""
        # 这里可以添加语言切换的实际逻辑
        print(f"语言已切换为: {text}")
    
    def update_language_combo_style(self, is_expanded):
        """
        更新语言下拉框的样式，根据展开状态切换图标
        :param is_expanded: 是否展开状态，True显示fold-up.png，False显示expand.png
        """
        # 根据展开状态选择图标
        icon_name = "fold-up.png" if is_expanded else "expand.png"
        image_path = os.path.join(self.resource_path, 'images', 'version', icon_name).replace('\\', '/')
        
        self.language_combo_in_header.setStyleSheet(f"""
            QComboBox {{
                background-color: rgba(255, 255, 255, 0.1);
                border: 1px solid rgba(255, 255, 255, 0.3);
                border-radius: 0px;
                padding: 4px 30px 4px 8px;
                color: #FFFFFF;
                font-size: 11px;
                background-image: url({image_path});
                background-repeat: no-repeat;
                background-position: right;
            }}
            QComboBox:hover {{
                background-color: rgba(255, 255, 255, 0.15);
                border: 1px solid rgba(255, 255, 255, 0.5);
            }}
            QComboBox::drop-down {{
                border: none;
                width: 0px;
            }}
            QComboBox::down-arrow {{
                width: 0;
                height: 0;
                border: none;
            }}
            QComboBox QAbstractItemView {{
                background-color: #3E344F;
                border: 1px solid rgba(255, 255, 255, 0.3);
                selection-background-color: rgba(255, 255, 255, 0.2);
                color: #FFFFFF;
            }}
        """)
    
    def on_language_combo_show_popup(self):
        """处理语言下拉框显示弹出菜单事件"""
        # 切换到fold-up.png图标
        self.update_language_combo_style(True)
        # 调用原始的showPopup方法
        QComboBox.showPopup(self.language_combo_in_header)
    
    def on_language_combo_hide_popup(self):
        """处理语言下拉框隐藏弹出菜单事件"""
        # 切换到expand.png图标
        self.update_language_combo_style(False)
        # 调用原始的hidePopup方法
        QComboBox.hidePopup(self.language_combo_in_header)
    
    def on_download_source_collapse_changed(self, is_expanded):
        """处理下载源CollapsePanel折叠状态变化"""
        pass
    
    def get_default_cache_path(self):
        """获取默认缓存路径"""
        if os.name == 'nt':  # Windows系统
            appdata = os.environ.get('APPDATA', '')
            return os.path.join(appdata, '.minecraft').replace('\\', '/')
        else:  # Linux/Mac系统
            home = os.path.expanduser('~')
            return os.path.join(home, '.minecraft')
    
    def update_cache_path_display(self):
        """更新缓存路径显示"""
        if self.default_cache_checkbox.isChecked():
            # 显示默认路径
            default_path = self.get_default_cache_path()
            self.cache_collapse_panel.set_messages(default_path)
        elif self.custom_cache_checkbox.isChecked():
            # 显示自定义路径
            custom_path = self.custom_cache_path.text()
            self.cache_collapse_panel.set_messages(custom_path)
        else:
            # 如果都没选中，显示默认路径
            default_path = self.get_default_cache_path()
            self.cache_collapse_panel.set_messages(default_path)
    
    def on_cache_option_changed(self):
        """处理缓存选项变化"""
        # 更新路径显示（无论是否展开都更新）
        self.update_cache_path_display()
        
        # 保存配置
        self.save_cache_settings()
    
    def browse_custom_cache_path(self):
        """浏览自定义缓存路径"""
        from PySide6.QtWidgets import QFileDialog
        
        # 获取当前路径作为起始目录
        current_path = self.custom_cache_path.text()
        if not current_path or not os.path.exists(current_path):
            current_path = os.path.expanduser('~')
        
        # 打开文件夹选择对话框
        folder_path = QFileDialog.getExistingDirectory(
            self,
            "选择缓存文件夹",
            current_path,
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks
        )
        
        if folder_path:
            # 更新自定义路径输入框
            self.custom_cache_path.setText(folder_path)
            # 自动选择自定义选项
            self.custom_cache_checkbox.setChecked(True)
            # 更新路径显示（无论是否展开都更新）
            self.update_cache_path_display()
            # 保存配置
            self.save_cache_settings()
    
    def save_cache_settings(self):
        """保存缓存设置到配置文件"""
        settings_manager = get_settings_manager(self.config_path)
        settings_manager.set_setting('cache_use_default', self.default_cache_checkbox.isChecked())
        settings_manager.set_setting('cache_custom_path', self.custom_cache_path.text())
        settings_manager.save_settings()
    
    def load_cache_settings(self):
        """从配置文件加载缓存设置"""
        settings_manager = get_settings_manager(self.config_path)
        
        # 加载设置，默认使用默认路径
        use_default = settings_manager.get_setting('cache_use_default', True)
        custom_path = settings_manager.get_setting('cache_custom_path', '')
        
        if use_default:
            self.default_cache_checkbox.setChecked(True)
        else:
            self.custom_cache_checkbox.setChecked(True)
            if custom_path:
                self.custom_cache_path.setText(custom_path)
        
        # 立即更新路径显示，无论折叠状态如何
        self.update_cache_path_display()
    
    def on_download_source_collapse_changed(self, is_expanded):
        """处理下载源折叠面板状态变化"""
        pass
