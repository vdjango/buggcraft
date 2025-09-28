import os
from PySide6.QtWidgets import (
    QWidget, QLabel, QPushButton, QHBoxLayout
)
from PySide6.QtGui import QFont,  QColor, QIcon, QPainter, QMouseEvent
from PySide6.QtCore import Qt, QPoint, Signal


class TitleBar(QWidget):
    """优化的自定义标题栏 - 添加页面切换信号"""
    
    # 添加页面切换信号
    tab_switch_clicked = Signal(str)
    
    def __init__(self, parent, resource_path):
        super().__init__(parent)
        self.parent = parent
        self.resource_path = resource_path
        self.setObjectName("TitleBar")
        self.dragging = False
        self.drag_position = QPoint()
        
        # 图标资源
        start_icon = QIcon(os.path.abspath(os.path.join(self.resource_path, 'images', 'bar', 'ic.png')))
        
        # 标签页配置
        self.tab_icons = {
            "开始": start_icon,
            "设置": start_icon
        }
        self.tab_names = ["开始", "设置"]
        
        # 版本按钮配置
        self.version_buttons = ["版本选择", "版本管理"]
        
        # 控制按钮配置
        self.control_buttons = ["最小化", "关闭"]
        
        # 创建透明图标
        self.transparent_icon = QIcon(os.path.abspath(os.path.join(self.resource_path, 'images', 'bar', 'ic_no.png')))
        
        self.setFixedHeight(58)  # 固定高度，确保按钮不被裁切
        self.init_ui()
    
    def paintEvent(self, event):
        """重绘事件 - 确保背景绘制"""
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 0))   
        super().paintEvent(event)

    def init_ui(self):
        # 主水平布局
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(22, -5, 15, 0)
        main_layout.setSpacing(0)
        
        # 左侧拉伸，将所有按钮推到右侧
        main_layout.addStretch(1)
        
        # 为开始和设置按钮创建独立容器
        self.tab_buttons = []
        
        # 创建标签按钮容器
        tab_container = QWidget()
        tab_container.setFixedSize(250, 50)  # 设置容器大小
        tab_container.setStyleSheet("background: transparent;")   
        
        # 创建开始和设置按钮
        for i, name in enumerate(self.tab_names):
            tab_button = self.create_tab_button(name)
            self.tab_buttons.append(tab_button)
            
            # 设置按钮的父容器
            tab_button.setParent(tab_container)
            
            if i == 0:  # 开始按钮
                tab_button.move(0, -8)   
            else:  # 设置按钮
                tab_button.move(124, -8)   
        
        # 将容器添加到主布局
        main_layout.addWidget(tab_container)
        
        # 标签按钮和版本按钮之间的间距
        main_layout.addSpacing(5)
        
        # 创建版本按钮（版本选择、版本设置）
        self.version_btn_list = []
        
        # 创建版本选择按钮
        version_selection_btn = self.create_version_selection_button()
        self.version_btn_list.append(version_selection_btn)
        main_layout.addWidget(version_selection_btn)
        
        # 版本按钮之间的间距
        main_layout.addSpacing(5)
        
        # 创建版本设置按钮
        version_settings_btn = self.create_version_settings_button()
        self.version_btn_list.append(version_settings_btn)
        main_layout.addWidget(version_settings_btn)
        
        # 版本按钮和控制按钮之间的间距
        main_layout.addSpacing(5)
        
        # 创建控制按钮（最小化、关闭）
        self.control_btn_list = []
        for i, name in enumerate(self.control_buttons):
            control_btn = self.create_control_button(name)
            self.control_btn_list.append(control_btn)
            main_layout.addWidget(control_btn)
            # 控制按钮之间添加小间距
            if i < len(self.control_buttons) - 1:
                main_layout.addSpacing(5)
        
        # 设置初始选中状态
        self.set_active_tab(0)

    def create_tab_button(self, name):
        """创建单个标签按钮 - 使用背景图片和居中文字"""
        tab_button = QLabel()
        tab_button.setObjectName(f"tab_{name}")
        tab_button.mousePressEvent = lambda e: self.on_tab_clicked(name)
        
        # 设置按钮文字
        tab_button.setText(name)
        tab_button.setFont(QFont("Source Han Sans CN Heavy", 10))
        tab_button.setAlignment(Qt.AlignCenter)   
        
        # 设置初始样式
        tab_button.setStyleSheet("""
            QLabel {
                color: #8e8e8e;
                font-weight: bold;
                background: transparent;
                padding-left: 15px;
                padding-top: 5px;
            }
        """)
        
        # 设置背景图片
        tab_button.setFixedSize(123, 45)
        
        return tab_button

    def create_version_selection_button(self):
        """创建版本选择按钮 - 使用version_selection_background.png背景图片"""
        version_btn = QLabel()
        version_btn.setObjectName("version_版本选择")
        version_btn.mousePressEvent = lambda e: self.tab_switch_clicked.emit('版本选择')
        
        # 设置按钮文字
        version_btn.setText("版本选择")
        version_btn.setFont(QFont("Source Han Sans CN Heavy", 10))
        version_btn.setAlignment(Qt.AlignCenter)
        
        # 设置按钮尺寸（190x33像素）
        version_btn.setFixedSize(190, 33)
        
        # 设置背景图片
        bg_path = os.path.abspath(os.path.join(self.resource_path, 'images', 'bar', 'version_selection_background.png'))
        if os.path.exists(bg_path):
            bg_path_url = bg_path.replace('\\', '/')
            version_btn.setStyleSheet(f"""
                QLabel {{
                    color: #FFFFFF;
                    font-weight: bold;
                    background-image: url({bg_path_url});
                    background-repeat: no-repeat;
                    background-position: center;
                    text-align: center;
                    qproperty-alignment: AlignCenter;
                    padding-top: 0px;
                    padding-bottom: 4px;
                }}
            """)
        else:
            # 如果图片不存在，使用默认样式
            version_btn.setStyleSheet("""
                QLabel {
                    color: #FFFFFF;
                    font-weight: bold;
                    background-color: rgba(64, 64, 64, 0.8);
                    border: 1px solid #888;
                    text-align: center;
                    qproperty-alignment: AlignCenter;
                    padding-top: 0px;
                    padding-bottom: 4px;
                }
            """)
        
        return version_btn

    def create_version_settings_button(self):
        """创建版本设置按钮 - 使用version_settings_background.png背景图片"""
        version_btn = QLabel()
        version_btn.setObjectName("version_版本设置")
        version_btn.mousePressEvent = lambda e: self.tab_switch_clicked.emit('版本管理')
        
        # 设置按钮文字
        version_btn.setText("版本管理")
        version_btn.setFont(QFont("Source Han Sans CN Heavy", 10))
        version_btn.setAlignment(Qt.AlignCenter)
        
        # 设置按钮尺寸（128x33像素）
        version_btn.setFixedSize(128, 33)
        
        # 设置背景图片
        bg_path = os.path.abspath(os.path.join(self.resource_path, 'images', 'bar', 'version_settings_background.png'))
        if os.path.exists(bg_path):
            bg_path_url = bg_path.replace('\\', '/')
            version_btn.setStyleSheet(f"""
                QLabel {{
                    color: #FFFFFF;
                    font-weight: bold;
                    background-image: url({bg_path_url});
                    background-repeat: no-repeat;
                    background-position: center;
                    text-align: center;
                    qproperty-alignment: AlignCenter;
                    padding-top: 0px;
                    padding-bottom: 4px;
                }}
            """)
        else:
            # 如果图片不存在，使用默认样式
            version_btn.setStyleSheet("""
                QLabel {
                    color: #FFFFFF;
                    font-weight: bold;
                    background-color: rgba(64, 64, 64, 0.8);
                    border: 1px solid #888;
                    text-align: center;
                    qproperty-alignment: AlignCenter;
                    padding-top: 0px;
                    padding-bottom: 4px;
                }
            """)
        
        return version_btn

    def create_control_button(self, name):
        """创建控制按钮 - 使用min.png和close.png背景图片"""
        control_btn = QPushButton()
        control_btn.setObjectName(f"control_{name}")
        
        # 设置按钮尺寸（30x33像素）
        control_btn.setFixedSize(30, 33)
        
        # 根据按钮名称设置背景图片和功能
        if name == "最小化":
            bg_image = "min.png"
            control_btn.clicked.connect(self.parent.showMinimized)
        elif name == "关闭":
            bg_image = "close.png"
            control_btn.clicked.connect(self.parent.close)
        else:
            bg_image = "min.png"  # 默认使用最小化图片
        
        bg_path = os.path.abspath(os.path.join(self.resource_path, 'images', 'bar', bg_image))
        if os.path.exists(bg_path):
            bg_path_url = bg_path.replace('\\', '/')
            control_btn.setStyleSheet(f"""
                QPushButton {{
                    background-image: url({bg_path_url});
                    background-repeat: no-repeat;
                    background-position: center;
                    border: none;
                }}
                QPushButton:hover {{
                    background-color: rgba(255, 255, 255, 0.1);
                }}
            """)
        else:
            # 如果图片不存在，使用默认样式
            if name == "最小化":
                control_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #00AA36;
                        border-radius: 0px;
                    }
                    QPushButton:hover {
                        background-color: #55BB6A;
                    }
                """)
            else:  # 关闭按钮
                control_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #FF0000;
                        border-radius: 0px;
                    }
                    QPushButton:hover {
                        background-color: #F00036;
                    }
                """)
        
        return control_btn

    def set_active_tab(self, index):
        """设置活动标签页"""
        for i, tab_button in enumerate(self.tab_buttons):
            if i == index:
                # 激活状态 - 设置ic.png作为背景图片
                bg_path = os.path.abspath(os.path.join(self.resource_path, 'images', 'bar', 'ic.png'))
                if os.path.exists(bg_path):
                    bg_path_url = bg_path.replace('\\', '/')
                    tab_button.setStyleSheet(f"""
                        QLabel {{
                            color: #FFFFFF;
                            font-weight: bold;
                            background-image: url({bg_path_url});
                            background-repeat: no-repeat;
                            background-position: center;
                            padding-left: 15px;
                            padding-top: 5px;
                        }}
                    """)
                else:
                    # 如果图片不存在，使用颜色样式
                    tab_button.setStyleSheet("""
                        QLabel {
                            color: #FFFFFF;
                            font-weight: bold;
                            background-color: #7959FF;
                            padding-left: 15px;
                            padding-top: 5px;
                        }
                    """)
            else:
                # 非激活状态 - 透明背景
                tab_button.setStyleSheet("""
                    QLabel {
                        color: #8e8e8e;
                        font-weight: bold;
                        background: transparent;
                        padding-left: 15px;
                        padding-top: 5px;
                    }
                """)

    def on_tab_clicked(self, name):
        """标签点击事件处理"""
        if name in self.tab_names:
            index = self.tab_names.index(name)
            self.set_active_tab(index)
            
            # 发射页面切换信号
            self.tab_switch_clicked.emit(name)
            
            # # 调用父窗口的标签切换方法（如果存在）
            # if hasattr(self.parent, 'switch_pages'):
            #     self.parent.switch_pages(index)
    
    # 保留原有的窗口拖动功能
    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self.dragging = True
            self.drag_position = event.globalPosition().toPoint() - self.parent.frameGeometry().topLeft()
            event.accept()
    
    def mouseMoveEvent(self, event: QMouseEvent):
        if self.dragging and event.buttons() & Qt.LeftButton:
            self.parent.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()
    
    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self.dragging = False
            event.accept()