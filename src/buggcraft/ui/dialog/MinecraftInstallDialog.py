"""版本删除确认"""

import sys
import os

from PySide6.QtWidgets import (
    QDialog, QLabel, QVBoxLayout, QHBoxLayout, QPushButton, 
    QWidget, QApplication, QFrame, QGraphicsDropShadowEffect
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPalette, QMouseEvent, QPixmap, QFont

from core.auth.microsoft import MicrosoftAuthenticator, MinecraftSignals


import threading
import time
import sys

from PySide6.QtWidgets import (
    QDialog, QLabel, QVBoxLayout, QHBoxLayout, QPushButton, 
    QWidget, QApplication, QFrame, QGraphicsDropShadowEffect
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPalette, QMouseEvent

from core.auth.microsoft import MicrosoftAuthenticator, MinecraftSignals


from PySide6.QtWidgets import QLayout, QWidget, QSizePolicy
from PySide6.QtCore import QRect, QSize, QPoint, Qt


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
        
        # 头部区域
        header_widget = QWidget()
        header_widget.setStyleSheet("background-color: rgba(39, 41, 55, 1);")
        header_layout = QVBoxLayout(header_widget)
        header_layout.setContentsMargins(18, 15, 18, 15)

        title_layout = QHBoxLayout()

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
        
        # 内容区域
        content_widget = QWidget()
        # content_widget.setFixedHeight(435-80)
        content_widget.setStyleSheet("background-color: rgba(39, 41, 55, 1);")
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(18, 18, 18, 18)
        content_layout.setSpacing(0)

        content_layout.addWidget(
            self.create_version_item(self.version, self.description)
        )
        content_layout.addSpacing(18)
        
        # 流式布局
        flow_widget = QWidget()
        flow_widget.setStyleSheet("background-color: rgba(39, 41, 55, 1);")
        flow_layout = FlowLayout(flow_widget)
        flow_layout.setContentsMargins(0, 0, 0, 0)
        flow_layout.setSpacing(18)
        
        flow_layout.addWidget(self.create_installation_item('Minecraft', 'self.version', True))
        flow_layout.addWidget(self.create_installation_item('Forge', '未选择', True))
        flow_layout.addWidget(self.create_installation_item('NeoForge', '未选择'))
        flow_layout.addWidget(self.create_installation_item('OptiFine', '未选择', True))
        flow_layout.addWidget(self.create_installation_item('Fabric', '未选择'))
        # flow_layout.addWidget(self.create_installation_item('Fabric API', '未选择'))
        # flow_layout.addWidget(self.create_installation_item())
        # flow_layout.addWidget(self.create_installation_item())
        # flow_layout.addWidget(self.create_installation_item())
        # content_layout.addWidget(self.create_installation_item())
        # content_layout.addWidget(self.create_installation_item())
        # content_layout.addWidget(self.create_installation_item())
        # content_layout.addWidget(self.create_installation_item())
        
        content_layout.addWidget(flow_widget)
        content_layout.addStretch(1)
        
        # 按钮区域
        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(0, 18, 0, 0)
        button_layout.setSpacing(20)
        button_layout.addStretch()

        self.confirm_button = QPushButton("安装")
        self.confirm_button.setFixedSize(70, 35)
        self.confirm_button.setStyleSheet("""
            QPushButton {
                background-color: #7859FF;
                color: #e0e0e0;
                border: none;
                font-size: 13px;
                font-weight: medium;
            }
            QPushButton:hover {
                background-color: #8A6FFF;
            }
            QPushButton:pressed {
                background-color: #6A4FFF;
            }
        """)
        self.confirm_button.clicked.connect(self.on_installed)
        button_layout.addWidget(self.confirm_button)
        
        # 取消按钮  TODO 待加载背景图
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setFixedSize(70, 35)
        self.cancel_button.setStyleSheet("""
            QPushButton {
                background-color: #2F2E4B;
                color: #e0e0e0;
                border: none;
                font-size: 13px;
                font-weight: medium;
            }
            QPushButton:hover {
                background-color: #3F3E5B;
            }
            QPushButton:pressed {
                background-color: #1F1E3B;
            }
        """)
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_button)

        content_layout.addLayout(button_layout)
        main_layout.addWidget(content_widget)
        
        self.add_shadow_effect()

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
        
        # 选中图标 - 使用InstallNewGame.png 
        select_icon = self.create_icon_label(
            os.path.join(self._parent.resource_path, 'images', 'Install', 'InstallNewGame.png'),
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
        
        self.text_label = QLabel(f'安装实例：{self.version}')
        self.text_label.setFont(QFont("Source Han Sans CN Normal", 10, QFont.Weight.Bold))
        self.text_label.setStyleSheet("color: #f2f2f2;")
        
        self.desc_label = QLabel(self.description)
        self.desc_label.setFont(QFont("Source Han Sans CN Normal", 9, QFont.Weight.Normal))
        self.desc_label.setStyleSheet("color: rgba(255, 255, 255, 0.7);")
        
        text_layout.addWidget(self.text_label, 0, Qt.AlignVCenter)
        text_layout.addWidget(self.desc_label, 0, Qt.AlignVCenter)
        
        layout.addWidget(text_widget)
        layout.addStretch(1)
        
        return item
    
    def create_installation_item(self, name, description, is_selected=False):
        item = QWidget()
        item.setCursor(Qt.PointingHandCursor)
        item.setFixedSize(110, 120)
        if is_selected:
            item.setStyleSheet('background-color: rgba(190, 183, 255, 0.20);')
            item.setDisabled(False)
        else:
            item.setStyleSheet('background-color: rgba(190, 183, 255, 0.10);')
            item.setDisabled(True)

        # 存储数据
        item.setProperty("name", name)
        item.setProperty("description", description)
        item.setProperty("is_selected", is_selected)

        layout = QVBoxLayout(item)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(0)
        
        # 图标 - 使用InstallNewGame.png 
        select_icon = self.create_icon_label(
            os.path.join(self._parent.resource_path, 'images', 'Install', 'InstallNewGame.png'),
            size=(50, 50)
        )
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
        
        return item
    
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
        self.text_label.setText(f"安装实例：{self.version}")
        self.desc_label.setText(f"{self.description}")
    
    def on_installed(self):
        self.download_signal.emit()
        self.accept()
    
    def on_import(self):
        self.import_signal.emit()
        self.accept()

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


