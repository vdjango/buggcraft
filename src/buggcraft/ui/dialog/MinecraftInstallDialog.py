"""版本删除确认"""
import sys
import os

from PySide6.QtWidgets import (
    QDialog, QLabel, QVBoxLayout, QHBoxLayout, QPushButton, QApplication,
    QWidget, QStackedWidget, QFrame, QGraphicsDropShadowEffect, QLayout, QSizePolicy
)
from PySide6.QtCore import Qt, QRect, QSize, QPoint, Signal
from PySide6.QtGui import QColor, QPalette, QMouseEvent, QPixmap, QFont


class FlowLayout(QLayout):
    """自定义流式布局 - 横向排列，自动换行"""
    
    def __init__(self, parent=None, margin=0, spacing=-1):
        super().__init__(parent)
        
        self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)
        self.item_list = []
    
    def addItem(self, item):
        """添加项目到布局"""
        self.item_list.append(item)
    
    def count(self):
        """返回项目数量"""
        return len(self.item_list)
    
    def itemAt(self, index):
        """获取指定索引的项目"""
        if 0 <= index < len(self.item_list):
            return self.item_list[index]
        return None
    
    def takeAt(self, index):
        """移除并返回指定索引的项目"""
        if 0 <= index < len(self.item_list):
            return self.item_list.pop(index)
        return None
    
    def expandingDirections(self):
        """布局扩展方向"""
        return Qt.Orientations(0)
    
    def hasHeightForWidth(self):
        """支持高度随宽度变化"""
        return True
    
    def heightForWidth(self, width):
        """根据宽度计算所需高度"""
        return self._do_layout(QRect(0, 0, width, 0), True)
    
    def setGeometry(self, rect):
        """设置布局几何形状"""
        super().setGeometry(rect)
        self._do_layout(rect, False)
    
    def sizeHint(self):
        """返回布局的推荐大小"""
        return self.minimumSize()
    
    def minimumSize(self):
        """返回布局的最小大小"""
        size = QSize()
        
        for item in self.item_list:
            size = size.expandedTo(item.minimumSize())
        
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), 
                     margins.top() + margins.bottom())
        return size
    
    def _do_layout(self, rect, test_only):
        """执行布局计算"""
        left, top, right, bottom = self.getContentsMargins()
        effective_rect = rect.adjusted(+left, +top, -right, -bottom)
        x = effective_rect.x()
        y = effective_rect.y()
        line_height = 0
        
        for item in self.item_list:
            widget = item.widget()
            if widget is None:
                continue
            
            # 计算间距
            space_x = self.spacing()
            space_y = self.spacing()
            if space_x == -1:
                space_x = widget.style().layoutSpacing(
                    QSizePolicy.PushButton, QSizePolicy.PushButton, Qt.Horizontal)
            if space_y == -1:
                space_y = widget.style().layoutSpacing(
                    QSizePolicy.PushButton, QSizePolicy.PushButton, Qt.Vertical)
            
            # 计算下一个项目的位置
            next_x = x + item.sizeHint().width() + space_x
            if next_x - space_x > effective_rect.right() and line_height > 0:
                # 换行
                x = effective_rect.x()
                y = y + line_height + space_y
                next_x = x + item.sizeHint().width() + space_x
                line_height = 0
            
            if not test_only:
                # 设置项目位置
                item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))
            
            x = next_x
            line_height = max(line_height, item.sizeHint().height())
        
        return y + line_height - rect.y() + bottom


from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QPixmap, QCursor
import os

class InstallationItem(QWidget):
    """安装项目控件 - 封装为类"""
    
    # 定义点击信号
    clicked = Signal()
    
    def __init__(self, name, description, is_selected=True, is_disabled=False, is_cursor=False, icon=None, parent=None):
        """
        初始化安装项目
        
        Args:
            name: 项目名称
            description: 项目描述
            is_selected: 是否选中状态
            is_disabled: 是否禁用状态
            is_cursor:   是否显示光标
            icon: 图标路径
            parent: 父控件
        """
        super().__init__(parent)
        self._name = name
        self._description = description
        self._is_selected = is_selected
        self._is_disabled = is_disabled
        self._is_cursor = is_cursor
        self._icon_path = icon
        
        # 存储子控件引用
        self._desc_label = None
        self._version_label = None
        self._icon_label = None
        
        self.init_ui()
        self.update_style()
    
    def init_ui(self):
        """初始化UI"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 创建主容器
        self.content_container = QWidget(self)
        self.content_container.setContentsMargins(0, 0, 0, 0)
        self.content_container.setFixedSize(110, 120)
        
        # 主布局
        layout = QVBoxLayout(self.content_container)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(0)
        
        # 图标
        self._icon_label = self.create_icon_label(self._icon_path, size=(50, 50))
        layout.addSpacing(5)
        layout.addWidget(self._icon_label, 0, Qt.AlignCenter)
        layout.addSpacing(10)
        
        # 文本区域
        text_widget = QWidget()
        text_widget.setStyleSheet("background-color: transparent;")
        text_layout = QVBoxLayout(text_widget)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(5)
        
        # 版本名称标签
        self._version_label = QLabel(self._name)
        self._version_label.setFont(QFont("Source Han Sans CN Normal", 10, QFont.Weight.Bold))
        self._version_label.setStyleSheet("color: #f2f2f2;")
        self._version_label.setAlignment(Qt.AlignCenter)
        
        # 描述标签
        self._desc_label = QLabel(self._description)
        self._desc_label.setFont(QFont("Source Han Sans CN Normal", 9, QFont.Weight.Normal))
        self._desc_label.setStyleSheet("color: rgba(255, 255, 255, 0.7);")
        self._desc_label.setAlignment(Qt.AlignCenter)
        
        text_layout.addWidget(self._version_label)
        text_layout.addWidget(self._desc_label)
        
        layout.addWidget(text_widget)
        
        main_layout.addWidget(self.content_container)
    
    def create_icon_label(self, icon_path, size=(50, 50)):
        """创建图标标签"""
        label = QLabel()
        label.setFixedSize(size[0], size[1])
        label.setAlignment(Qt.AlignCenter)
        
        if icon_path and os.path.exists(icon_path):
            pixmap = QPixmap(icon_path)
            if not pixmap.isNull():
                scaled_pixmap = pixmap.scaled(size[0], size[1], Qt.AspectRatioMode.KeepAspectRatio, 
                                            Qt.TransformationMode.SmoothTransformation)
                label.setPixmap(scaled_pixmap)
        else:
            # 使用默认图标
            default_icon = os.path.join(self.get_resource_path(), 'images', 'Install', 'InstallNewGame.png')
            if os.path.exists(default_icon):
                pixmap = QPixmap(default_icon)
                scaled_pixmap = pixmap.scaled(size[0], size[1], Qt.AspectRatioMode.KeepAspectRatio,
                                            Qt.TransformationMode.SmoothTransformation)
                label.setPixmap(scaled_pixmap)
        
        return label
    
    def get_resource_path(self):
        """获取资源路径"""
        # 从父级获取资源路径
        parent = self.parent()
        while parent:
            if hasattr(parent, 'resource_path'):
                return parent.resource_path
            parent = parent.parent()
        return '.'  # 默认返回当前目录
    
    def update_style(self):
        """更新样式"""
        if self._is_disabled:
            self.content_container.setStyleSheet('background-color: rgba(190, 183, 255, 0.20);')
            self.setCursor(Qt.ForbiddenCursor)  # 禁用时显示禁止光标
        else:
            if self._is_selected:
                self.content_container.setStyleSheet('background-color: rgba(190, 183, 255, 0.20);')
            else:
                self.content_container.setStyleSheet('background-color: rgba(190, 183, 255, 0.10);')
            
            if not self._is_cursor:
                self.setCursor(Qt.PointingHandCursor)  # 启用时显示手型光标

        self.setDisabled(self._is_disabled)
    
    def mousePressEvent(self, event):
        """鼠标点击事件"""
        if event.button() == Qt.LeftButton and not self._is_disabled:
            self.clicked.emit()
        super().mousePressEvent(event)
    
    # ===== 公共方法 =====
    
    def set_description(self, description):
        """设置描述文本"""
        self._description = description
        if self._desc_label:
            self._desc_label.setText(description)
    
    def set_selected(self, is_selected):
        """设置选中状态"""
        self._is_selected = is_selected
        self.update_style()
    
    def set_disabled(self, is_disabled):
        """设置禁用状态"""
        self._is_disabled = is_disabled
        self.update_style()
    
    def set_icon(self, icon_path):
        """设置图标"""
        self._icon_path = icon_path
        if self._icon_label and icon_path and os.path.exists(icon_path):
            pixmap = QPixmap(icon_path)
            if not pixmap.isNull():
                scaled_pixmap = pixmap.scaled(50, 50, Qt.AspectRatioMode.KeepAspectRatio,
                                            Qt.TransformationMode.SmoothTransformation)
                self._icon_label.setPixmap(scaled_pixmap)
    
    def set_name(self, name):
        """设置名称"""
        self._name = name
        if self._version_label:
            self._version_label.setText(name)
    
    # ===== 属性访问器 =====
    
    @property
    def name(self):
        return self._name
    
    @property
    def description(self):
        return self._description
    
    @property
    def is_selected(self):
        return self._is_selected
    
    @property
    def is_disabled(self):
        return self._is_disabled
    
    def get_properties(self):
        """获取所有属性（兼容原有代码）"""
        return {
            "name": self._name,
            "description": self._description,
            "is_selected": self._is_selected,
            "is_disabled": self._is_disabled
        }
        

class MinecraftInstallDialog(QDialog):

    import_signal = Signal()  # 导入
    download_signal = Signal()  # 下载

    def __init__(self, parent=None):
        """安装游戏"""
        super().__init__(None)
        self._parent = parent

        self.title = '安装新游戏'
        self.version = None
        self.description = None
        
        self.forge_install: dict = {}

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(719, 535)
        
        # 设置窗口背景色 RGBA(39, 41, 55, 1)
        palette = self.palette()
        palette.setColor(QPalette.Window, QColor(39, 41, 55))
        self.setPalette(palette)
        self.init_ui()
        
    def init_ui(self):
        # 主布局
        self.main_widget = QWidget(self)
        main_layout = QVBoxLayout(self.main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        header = self.create_header()
        main_layout.addWidget(header)
        
        # 内容区域
        self.content_stack = QStackedWidget()
        self.content_stack.setContentsMargins(0, 0, 0, 0)
        self.content_stack.setStyleSheet("background-color: transparent;")
        
        # 游戏安装项
        content_install_widget = self.create_install_panel()
        # Forge列表
        content_forge_widget = self.create_forge_panel()
        
        self.content_stack.addWidget(content_install_widget)
        self.content_stack.addWidget(content_forge_widget)
        
        main_layout.addWidget(self.content_stack)
        
        self.content_stack.setCurrentIndex(0)
        self.add_shadow_effect()
    
    def create_header(self):
        widget = QWidget(self)
        main_layout = QVBoxLayout(widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 头部区域
        header_widget = QWidget()
        header_widget.setStyleSheet("background-color: rgba(39, 41, 55, 1);")
        header_layout = QVBoxLayout(header_widget)
        header_layout.setContentsMargins(18, 15, 18, 15)

        title_layout = QHBoxLayout()

        # 添加logo图标
        logo_icon = self.create_icon_label(
            os.path.join(self._parent.resource_path, 'images', 'Install', 'InstallLogo.png'),
            size=(14, 14)
        )
        title_layout.addWidget(logo_icon)
        title_layout.addSpacing(5)  # logo和标题之间的间距

        self.title_label = QLabel(self.title)
        self.title_label.setFont(QFont("Source Han Sans CN Normal", 11, QFont.Weight.Bold))
        self.title_label.setStyleSheet("color: rgba(220, 220, 220, 1); font-weight: bold;  background-color: transparent;")
        title_layout.addWidget(self.title_label)
        title_layout.addStretch()
        header_layout.addLayout(title_layout)

        # 添加下划线（水平分隔线）
        underline = QHBoxLayout()
        title_underline = QFrame()
        title_underline.setFrameShape(QFrame.HLine)
        title_underline.setStyleSheet("background-color: rgba(139, 133, 218, 1);")
        title_underline.setFixedWidth(self.width()-30*2)
        underline.addWidget(title_underline)
        
        main_layout.addWidget(header_widget)
        main_layout.addLayout(underline)
        return widget
        
    def create_install_panel(self):
        """游戏安装项"""
        content_widget = QWidget()
        content_widget.setStyleSheet("background-color: rgba(39, 41, 55, 1);")
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(18, 18, 18, 18)
        content_layout.setSpacing(0)

        content_layout.addWidget(
            self.create_install_header_item(self.version, self.description)
        )
        content_layout.addSpacing(18)
        
        # 流式布局
        flow_widget = QWidget()
        flow_widget.setStyleSheet("background-color: rgba(39, 41, 55, 1);")
        self.flow_layout = FlowLayout(flow_widget)
        self.flow_layout.setContentsMargins(0, 0, 0, 0)
        self.flow_layout.setSpacing(18)
        
        # Minecraft
        self.flow_minecraft = InstallationItem(
            name='Minecraft',
            description=self.version,
            is_selected=True,
            is_cursor=True,
            icon=os.path.join(self._parent.resource_path, 'images', 'user', 'offline_login.png')
        )
        self.flow_layout.addWidget(self.flow_minecraft)
        
        # Forge
        self.flow_forge = InstallationItem(
            name='Forge',
            description='未选择',
            is_selected=False,
            icon=os.path.join(self._parent.resource_path, 'images', 'forge.png')
        )
        self.flow_forge.clicked.connect(lambda: self.content_stack.setCurrentIndex(1))
        self.flow_layout.addWidget(self.flow_forge)

        # OptiFine
        self.flow_optifine = InstallationItem(
            name='OptiFine',
            description='未选择',
            is_selected=False,
            icon=os.path.join(self._parent.resource_path, 'images', 'of.png')
        )
        # self.flow_optifine.clicked.connect(lambda: self.content_stack.setCurrentIndex(1))
        self.flow_layout.addWidget(self.flow_optifine)
        
        # flow_item, _ = self.create_installation_item('NeoForge', '未选择')
        # self.flow_layout.addWidget(flow_item)
        # flow_item, _ = self.create_installation_item('Fabric', '未选择')
        # self.flow_layout.addWidget(flow_item)
        
        content_layout.addWidget(flow_widget)
        content_layout.addStretch(1)
        
        # 按钮区域
        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(0, 18, 0, 0)
        button_layout.setSpacing(20)
        button_layout.addStretch()

        self.confirm_button = QPushButton("安装")
        self.confirm_button.setFixedSize(72, 35)
        self.confirm_button.setCursor(Qt.PointingHandCursor)
        install_bg_path = os.path.join(self._parent.resource_path, 'images', 'Install', 'Install.png').replace('\\', '/')
        self.confirm_button.setStyleSheet(f"""
            QPushButton {{
                background-image: url({install_bg_path});
                background-repeat: no-repeat;
                background-position: center;
                color: #e0e0e0;
                border: none;
                font-size: 13px;
                font-weight: medium;
            }}
            QPushButton:hover {{
                background-image: url({install_bg_path});
                background-repeat: no-repeat;
                background-position: center;
                opacity: 0.8;
            }}
            QPushButton:pressed {{
                background-image: url({install_bg_path});
                background-repeat: no-repeat;
                background-position: center;
                opacity: 0.6;
            }}
        """)
        self.confirm_button.clicked.connect(self.on_installed)
        button_layout.addWidget(self.confirm_button)
        
        # 取消按钮 - 使用Cancel.png背景图片
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setFixedSize(72, 35)
        self.cancel_button.setCursor(Qt.PointingHandCursor)
        cancel_bg_path = os.path.join(self._parent.resource_path, 'images', 'Install', 'Cancel.png').replace('\\', '/')
        self.cancel_button.setStyleSheet(f"""
            QPushButton {{
                background-image: url({cancel_bg_path});
                background-repeat: no-repeat;
                background-position: center;
                color: #e0e0e0;
                border: none;
                font-size: 13px;
                font-weight: medium;
            }}
            QPushButton:hover {{
                background-image: url({cancel_bg_path});
                background-repeat: no-repeat;
                background-position: center;
                opacity: 0.8;
            }}
            QPushButton:pressed {{
                background-image: url({cancel_bg_path});
                background-repeat: no-repeat;
                background-position: center;
                opacity: 0.6;
            }}
        """)
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_button)

        content_layout.addLayout(button_layout)
        return content_widget
    
    def create_install_header_item(self, version, description, is_selected=False):
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
        
        # 选中图标 - 使用InstallNewGame.png 
        select_icon = self.create_icon_label(
            os.path.join(self._parent.resource_path, 'images', 'user', 'offline_login.png'),
            size=(40, 40)
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
        
        self.install_case_text_label = QLabel(f'安装实例：{version}')
        self.install_case_text_label.setFont(QFont("Source Han Sans CN Normal", 10, QFont.Weight.Bold))
        self.install_case_text_label.setStyleSheet("color: #f2f2f2;")
        
        self.install_case_desc_label = QLabel(description)
        self.install_case_desc_label.setFont(QFont("Source Han Sans CN Normal", 9, QFont.Weight.Normal))
        self.install_case_desc_label.setStyleSheet("color: rgba(255, 255, 255, 0.7);")
        
        text_layout.addWidget(self.install_case_text_label, 0, Qt.AlignVCenter)
        text_layout.addWidget(self.install_case_desc_label, 0, Qt.AlignVCenter)
        
        layout.addWidget(text_widget)
        layout.addStretch(1)
        
        return item
    
    def create_forge_panel(self):
        """Forge列表"""
        # https://bmclapi2.bangbang93.com/forge/minecraft/1.20.1
        content_widget = QWidget()
        content_widget.setStyleSheet("background-color: rgba(39, 41, 55, 1);")
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(18, 18, 18, 18)
        content_layout.setSpacing(5)

        forge_version = [
            {
                "_id": "6488aea60bbbb25aafef0760",
                "__v": 0,
                "build": 47000001,
                "files": [
                {
                    "format": "txt",
                    "category": "changelog",
                    "hash": "051dcb615409887a3844a82b6c41fbe2b7f7d23e"
                },
                {
                    "format": "jar",
                    "category": "installer",
                    "hash": "2bdc0e68530daf0af01cae44a05e7f84849bdc6e"
                },
                {
                    "format": "zip",
                    "category": "mdk",
                    "hash": "b6fa046388656bd0f7566d716d02a9ba5c00cbe9"
                }
                ],
                "mcversion": "1.20.1",
                "modified": "2023-06-13T02:37:00.000Z",
                "version": "47.0.1"
            },
            {
                "_id": "6488aea70bbbb25aafef092b",
                "__v": 0,
                "build": 47000000,
                "files": [
                {
                    "format": "txt",
                    "category": "changelog",
                    "hash": "a15adac6b718cfc42de5d447852e0342e654101b"
                },
                {
                    "format": "jar",
                    "category": "installer",
                    "hash": "d8e8ed1755969d516c23ccef3e0fc2608f3707e6"
                },
                {
                    "format": "zip",
                    "category": "mdk",
                    "hash": "165d584d747b8cfcc3d21341a6d4a65bca973736"
                }
                ],
                "mcversion": "1.20.1",
                "modified": "2023-06-12T22:33:41.000Z",
                "version": "47.0.0"
            },
            {
                "_id": "648b51a40bbbb25aaf3c137e",
                "__v": 0,
                "build": 47000002,
                "files": [
                {
                    "format": "txt",
                    "category": "changelog",
                    "hash": "97e72f53df932b2077cc8bc67e34907e2e4f853c"
                },
                {
                    "format": "jar",
                    "category": "installer",
                    "hash": "bb63e2cd97bf56a0ff81d60333285f8465ccdd53"
                },
                {
                    "format": "zip",
                    "category": "mdk",
                    "hash": "c7d4955af656c613e968e2ca1f012baf86646d8e"
                }
                ],
                "mcversion": "1.20.1",
                "modified": "2023-06-15T02:52:50.000Z",
                "version": "47.0.2"
            }
        ]
        for item in forge_version:
            content_layout.addWidget(
                self.create_forge_item(item['_id'], f"Forge {item['version']}", f"时间：{item['modified']}")
            )
        
        content_layout.addStretch()
        
        # 按钮区域
        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(0, 18, 0, 0)
        button_layout.setSpacing(20)
        button_layout.addStretch()

        # 取消按钮 - 使用Cancel.png背景图片
        cancel_button = QPushButton("返回")
        cancel_button.setFixedSize(72, 35)
        cancel_button.setCursor(Qt.PointingHandCursor)
        cancel_bg_path = os.path.join(self._parent.resource_path, 'images', 'Install', 'Cancel.png').replace('\\', '/')
        cancel_button.setStyleSheet(f"""
            QPushButton {{
                background-image: url({cancel_bg_path});
                background-repeat: no-repeat;
                background-position: center;
                color: #e0e0e0;
                border: none;
                font-size: 13px;
                font-weight: medium;
            }}
            QPushButton:hover {{
                background-image: url({cancel_bg_path});
                background-repeat: no-repeat;
                background-position: center;
                opacity: 0.8;
            }}
            QPushButton:pressed {{
                background-image: url({cancel_bg_path});
                background-repeat: no-repeat;
                background-position: center;
                opacity: 0.6;
            }}
        """)
        cancel_button.clicked.connect(lambda: self.content_stack.setCurrentIndex(0))
        button_layout.addWidget(cancel_button)
        content_layout.addLayout(button_layout)
        return content_widget

    def create_forge_item(self, _id, version, modified, is_selected=False, is_disabled=False):
        """创建版本项"""
        item = QWidget()
        item.setFixedHeight(64)
        if is_disabled:
            item.setStyleSheet('background-color: rgba(190, 183, 255, 0.20);')
        else:
            if is_selected:
                item.setStyleSheet('background-color: rgba(190, 183, 255, 0.20);')
            else:
                item.setStyleSheet('background-color: rgba(190, 183, 255, 0.10);')
        
        item.setDisabled(is_disabled)
        
        # 存储数据
        item.setProperty("_id", _id)
        item.setProperty("version", version)
        item.setProperty("modified", modified)
        item.setProperty("is_selected", is_selected)
        item.setProperty("is_selected", is_disabled)

        layout = QHBoxLayout(item)
        layout.setContentsMargins(0, 10, 0, 10)
        layout.setSpacing(5)
        
        # 选中图标 - 使用InstallNewGame.png 
        select_icon = self.create_icon_label(
            os.path.join(self._parent.resource_path, 'images', 'user', 'offline_login.png'),
            size=(40, 40)
        )
        layout.addSpacing(15)
        layout.addWidget(select_icon)
        layout.addSpacing(10)
        
        # 文本区域
        text_widget = QWidget()
        text_widget.setStyleSheet("background-color: transparent;")
        text_layout = QVBoxLayout(text_widget)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(0)
        
        self.text_label = QLabel(version)
        self.text_label.setFont(QFont("Source Han Sans CN Normal", 10, QFont.Weight.Bold))
        self.text_label.setStyleSheet("color: #f2f2f2;")
        
        self.desc_label = QLabel(modified)
        self.desc_label.setFont(QFont("Source Han Sans CN Normal", 9, QFont.Weight.Normal))
        self.desc_label.setStyleSheet("color: rgba(255, 255, 255, 0.7);")
        
        text_layout.addWidget(self.text_label)
        text_layout.addWidget(self.desc_label)
        
        layout.addWidget(text_widget)
        
        item.mousePressEvent = lambda event: self.on_forge_clicked(item, event)
        item.setCursor(Qt.PointingHandCursor)
        return item
    
    def create_icon_label(self, icon_path, size=(30, 30), cursor=None):
        """创建图标标签"""
        label = QLabel()
        label.setFixedSize(size[0] + 1, size[1] + 1)
        label.setPixmap(QPixmap(icon_path).scaled(
            size[0], size[1], 
            Qt.KeepAspectRatio, 
            Qt.SmoothTransformation
        ))
        
        if cursor:
            label.setCursor(cursor)
        label.setStyleSheet("background-color: transparent; border: none;")
        return label
    
    def create_installation_itemx(self, name, description, is_selected=True, is_disabled=False, icon = None):
        item = QWidget()
        item.setCursor(Qt.PointingHandCursor)
        item.setFixedSize(110, 120)
        if is_disabled:
            item.setStyleSheet('background-color: rgba(190, 183, 255, 0.20);')
        else:
            if is_selected:
                item.setStyleSheet('background-color: rgba(190, 183, 255, 0.20);')
            else:
                item.setStyleSheet('background-color: rgba(190, 183, 255, 0.10);')
            
        item.setDisabled(is_disabled)

        # 存储数据
        item.setProperty("name", name)
        item.setProperty("description", description)
        item.setProperty("is_selected", is_selected)
        item.setProperty("is_selected", is_disabled)

        layout = QVBoxLayout(item)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(0)
        
        # 图标 - 使用InstallNewGame.png 
        if not icon:
            icon = os.path.join(self._parent.resource_path, 'images', 'Install', 'InstallNewGame.png')
        
        select_icon = self.create_icon_label(icon, size=(50, 50))
        layout.addSpacing(5)
        layout.addWidget(select_icon, 0, Qt.AlignCenter)
        layout.addSpacing(10)
        
        # 文本区域
        text_widget = QWidget()
        text_widget.setStyleSheet("background-color: transparent;")
        text_layout = QVBoxLayout(text_widget)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(5)
        
        version_label = QLabel(name)
        version_label.setFont(QFont("Source Han Sans CN Normal", 10, QFont.Weight.Bold))
        version_label.setStyleSheet("color: #f2f2f2;")
        
        desc_label = QLabel(description)
        desc_label.setFont(QFont("Source Han Sans CN Normal", 9, QFont.Weight.Normal))
        desc_label.setStyleSheet("color: rgba(255, 255, 255, 0.7);")
        
        text_layout.addWidget(version_label, 0, Qt.AlignCenter)
        text_layout.addWidget(desc_label, 0, Qt.AlignCenter)
        
        layout.addWidget(text_widget)
        
        item.setCursor(Qt.PointingHandCursor)
        return item, desc_label
    
    def add_shadow_effect(self):
        """添加自定义阴影效果"""
        shadow = QGraphicsDropShadowEffect(self.main_widget)
        shadow.setBlurRadius(20)  # 阴影模糊半径
        shadow.setColor(QColor(0, 0, 0, 150))  # 阴影颜色和透明度
        shadow.setOffset(0, 0)  # 零偏移量确保阴影均匀分布在四周
        
        # 应用阴影效果
        self.main_widget.setContentsMargins(25, 25, 25, 25)  # 四周均匀的边距
        self.main_widget.setGraphicsEffect(shadow)

    def set_version(self, version, description):
        self.version = version
        self.description = description
        self.title_label.setText(f"{self.title} - {self.version}")
        self.install_case_text_label.setText(f"安装实例：{self.version}")
        self.install_case_desc_label.setText(f"{self.description}")
        self.flow_minecraft.set_description(self.version)

    def on_installed(self):
        self.download_signal.emit()
        self.accept()
    
    def on_import(self):
        self.import_signal.emit()
        self.accept()

    def on_forge_clicked(self, item, event):
        """选择forge"""
        version = item.property('version')
        self.forge_install = {
            "_id": item.property('_id'),
            "version": version,
            "modified": item.property('modified')
        }
        self.content_stack.setCurrentIndex(0)
        self.flow_forge.set_selected(True)
        self.flow_forge.set_description(version)
        print('on_forge_clicked', self.forge_install)
        pass
    
    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self._is_dragging = True
            self._drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
    
    def mouseMoveEvent(self, event: QMouseEvent):
        if self._is_dragging and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_position)
            event.accept()
    
    def mouseReleaseEvent(self, event: QMouseEvent):
        self._is_dragging = False
        event.accept()


