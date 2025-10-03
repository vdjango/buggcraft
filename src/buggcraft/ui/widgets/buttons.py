# QMButton, PreciseSpacingButton

import os
from PySide6.QtWidgets import (QWidget, QLabel, QVBoxLayout, QHBoxLayout)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QPixmap, QPainter, QPalette


class QMButton(QLabel):
    """切换账号按钮 - 使用setPixmap设置背景图"""
    
    # 定义点击信号
    clicked = Signal()
    
    def __init__(self,
        text,
        parent=None,
        size=(244, 44),
        font_size=12,
        background_image=None,
        icon = None,
        icon_after=False,  # icon 放后面
        offset_right=0,  # icon图标位置偏移量
        icon_size=(14, 14),
        background_hover = "background-color: rgba(255, 255, 255, 0.1);",
        background_color = "background-color: rgba(34, 34, 34, 1);",
        scale_ratio=1.0
    ):
        super().__init__(parent)
        self._text = text
        self.background_image = background_image
        self.background_hover = background_hover
        self.background_color = background_color  # f"background-color: #222222;"
        self._size_w, self._size_h = size

        self.offset_right = offset_right
        self.font_size = font_size
        self.icon = icon
        self.icon_after = icon_after
        
        self.icon_size = icon_size
        self.scale_ratio = scale_ratio
        self.init_ui()
        
    def init_ui(self):
        # 设置按钮固定大小
        self.setFixedSize(self._size_w * self.scale_ratio, self._size_h * self.scale_ratio)
        self.setAlignment(Qt.AlignCenter)
        
        # 设置背景图片
        if self.background_image and os.path.exists(self.background_image):
            self.setPixmap(QPixmap(self.background_image).scaled(
                self._size_w * self.scale_ratio,
                self._size_h * self.scale_ratio,
                Qt.IgnoreAspectRatio,
                Qt.SmoothTransformation
            ))
        else:
            self.setStyleSheet(self.background_color)
        
        # 创建包含文本和箭头的容器
        self.content_widget = QWidget(self)
        self.content_widget.setGeometry(0, 0, self._size_w* self.scale_ratio, self._size_h * self.scale_ratio)

        # 创建水平布局
        content_layout = QHBoxLayout(self.content_widget)
        content_layout.setContentsMargins(self.offset_right * self.scale_ratio, 0, 0, 0)
        content_layout.setSpacing(5)
        
        # 创建文本标签
        self.text_label = QLabel(self._text)
        self.text_label.setFont(QFont("Source Han Sans CN Normal", self.font_size, QFont.Weight.Bold))  # self.font_size
        
        self.text_label.setStyleSheet(f"color: #f2f2f2; background-color: transparent;")
        self.text_label.setAlignment(Qt.AlignCenter)
        
        # 创建箭头图标标签
        w, h = self.icon_size
        self.icon_label = QLabel()
        if self.icon and os.path.exists(self.icon):
            self.icon_label.setPixmap(QPixmap(self.icon).scaled(
                w * self.scale_ratio,
                h * self.scale_ratio,
                Qt.IgnoreAspectRatio,
                Qt.SmoothTransformation
            ))
        self.icon_label.setStyleSheet(f"background-color: transparent;")
        self.icon_label.setAlignment(Qt.AlignCenter)
        
        # self.icon_after
        _icon = [self.text_label]
        # 将文本和图标添加到布局中
        content_layout.addStretch()
        if self.icon and os.path.exists(self.icon):
            _icon.append(self.icon_label)
        
        if not self.icon_after:
            _icon.reverse()

        for i in _icon:
            content_layout.addWidget(i)
            # content_layout.addSpacing(self.icon_offset_right)
            
        content_layout.addStretch()

        # 启用鼠标跟踪以检测悬停事件
        self.setMouseTracking(True)
    
    def mousePressEvent(self, event):
        """处理鼠标点击事件"""
        self.clicked.emit()
        super().mousePressEvent(event)
    
    def setText(self, text):
        """设置按钮文本"""
        self.text_label.setText(text)
    
    def setIcon(self, icon_path):
        """设置按钮图标"""
        w, h = self.icon_size
        if os.path.exists(icon_path):
            self.icon_label.setPixmap(QPixmap(icon_path).scaled(
                w * self.scale_ratio, 
                h * self.scale_ratio, 
                Qt.IgnoreAspectRatio, 
                Qt.SmoothTransformation
            ))
    
    def setBackground(self, bg_path):
        """设置按钮背景"""
        if os.path.exists(bg_path):
            self.setPixmap(QPixmap(bg_path).scaled(
                self._size_w * self.scale_ratio,
                self._size_h * self.scale_ratio,
                Qt.IgnoreAspectRatio,
                Qt.SmoothTransformation
            ))
    
    def enterEvent(self, event):
        """鼠标进入事件 - 添加悬停效果"""
        self.setStyleSheet(self.background_hover)
        super().enterEvent(event)
    
    def leaveEvent(self, event):
        """鼠标离开事件 - 移除悬停效果"""
        self.setStyleSheet(self.background_color)
        super().leaveEvent(event)


class QMStartButton(QWidget):
    """紧凑型双行文本按钮（固定尺寸240x44）"""
    
    clicked = Signal()  # 点击信号
    
    def __init__(self, line1="开始游戏", line2="游戏版本号", parent=None, resource_path=None):
        super().__init__(parent)
        self.resource_path = resource_path
        
        # 加载背景图片
        self.bg_pixmap = None
        self.load_background_image()
        
        # 设置按钮背景图片
        self.setFixedSize(239, 74)
        
        # 创建主布局 - 设置为无边距 居中
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        # 创建文本容器
        self.text_container = QWidget()

        self.text_container.setFixedSize(239, 74)
        self.text_layout = QVBoxLayout(self.text_container)
        self.text_layout.setContentsMargins(0, 0, 0, 0)   
        self.text_layout.setSpacing(0)  
        
        # 第一行文本标签
        self.line1_label = QLabel(line1)
        self.line1_label.setFont(QFont("CKTKingKong", 13, QFont.Weight.Bold))
        self.line1_label.setAlignment(Qt.AlignCenter)
        self.line1_label.setStyleSheet(f"""
            QLabel {{
                color: #6D6FFE;
                margin: 0;
                padding: 0;
                background: transparent;
            }}
        """)
        
        # 第二行文本标签
        self.line2_label = QLabel(line2)
        self.line2_label.setFont(QFont("Source Han Sans CN Normal", 10, QFont.Weight.Normal))
        self.line2_label.setAlignment(Qt.AlignCenter)
        self.line2_label.setStyleSheet(f"""
            QLabel {{
                color: #6D6FFE;
                margin: 0;
                padding: 0;
                background: transparent;
            }}
        """)
        
        # 垂直居中
        self.text_layout.addStretch(1)
        self.text_layout.addWidget(self.line1_label)
        self.text_layout.setSpacing(2)
        self.text_layout.addWidget(self.line2_label)
        self.text_layout.addStretch(1)
        
        # 将文本容器添加到主布局， 居中
        self.main_layout.addWidget(self.text_container, 0, Qt.AlignCenter)
        
        # 设置按钮样式
        self.set_start_style()
        
        # 设置光标
        self.setCursor(Qt.PointingHandCursor)
    
    def load_background_image(self):
        """加载背景图片"""
        if self.resource_path:
            bg_image_path = os.path.abspath(os.path.join(self.resource_path, 'images', 'user', 'start_game_btn.png'))
        if os.path.exists(bg_image_path):
            self.bg_pixmap = QPixmap(bg_image_path)
            if self.bg_pixmap and not self.bg_pixmap.isNull():
                self.bg_pixmap = self.bg_pixmap.scaled(
                    239, 74, 
                    Qt.KeepAspectRatio, 
                    Qt.SmoothTransformation
                )
    
    def paintEvent(self, event):
        """绘制背景图片"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        if self.bg_pixmap and not self.bg_pixmap.isNull():
            # 计算居中位置
            x = (self.width() - self.bg_pixmap.width()) // 2
            y = (self.height() - self.bg_pixmap.height()) // 2
            painter.drawPixmap(x, y, self.bg_pixmap)
        
        super().paintEvent(event)
    
    def set_start_style(self):
        """启动游戏样式"""
        self.setStyleSheet(f"""
            QWidget {{
                background: transparent;
                border-radius: 4px;
                margin: 0;
                padding: 0;
            }}
        """)
    
    def set_stop_style(self):
        """停止游戏样式"""
        self.setStyleSheet(f"""
            QWidget {{
                background-color: transparent;
                border-radius: 4px;
                margin: 0;
                padding: 0;
            }}
        """)
    
    def set_texts(self, line1, line2):
        """设置两行文本"""
        self.line1_label.setText(line1)
        self.line2_label.setText(line2)
    
    def mousePressEvent(self, event):
        """鼠标点击事件"""
        self.set_start_style()
        super().mousePressEvent(event)
    
    def mouseReleaseEvent(self, event):
        """鼠标释放事件"""
        self.set_start_style()
        self.clicked.emit()
        super().mouseReleaseEvent(event)

