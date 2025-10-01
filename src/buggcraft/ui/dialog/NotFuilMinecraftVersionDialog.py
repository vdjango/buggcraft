"""版本删除确认"""

import sys
import os

from PySide6.QtWidgets import (
    QDialog, QLabel, QVBoxLayout, QHBoxLayout, QPushButton, 
    QWidget, QApplication, QFrame, QGraphicsDropShadowEffect
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPalette, QMouseEvent, QPixmap

from core.auth.microsoft import MicrosoftAuthenticator, MinecraftSignals


class VersionNotFuilDialog(QDialog):

    cancel_signal = Signal()  # 取消
    reopen_signal = Signal()  # 重新打开浏览器

    def __init__(self, parent=None):
        """打开启动器没有发现版本时提示"""
        super().__init__(parent)
        self._parent = parent

        self.title = '未找到可用的游戏版本'
        self.message = "在开始前，请先下载任意版本游戏或导入游戏。"
        self.message_text = "若已存在游戏，请选择下方游戏导入或安装新游戏"

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(650, 300)
        
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
        header_layout.setContentsMargins(25, 15, 25, 15)

        title_layout = QHBoxLayout()

        self.title_label = QLabel(self.title)
        self.title_label.setStyleSheet("""
            color: rgba(220, 220, 220, 1);
            font-size: 15px;
            font-weight: bold;
        """)
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
        content_widget.setStyleSheet("background-color: rgba(39, 41, 55, 1);")
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(28, 20, 28, 20)
        content_layout.setSpacing(0)
        
        # 提示信息
        self.message_label = QLabel(self.message)
        self.message_label.setWordWrap(True)
        self.message_label.setStyleSheet("""
            color: #e0e0e0;
            font-size: 13px;
            font-weight: bold;
        """)
        self.message_text_label = QLabel(self.message_text)
        self.message_text_label.setWordWrap(True)
        self.message_text_label.setContentsMargins(0, 20, 0, 15)
        self.message_text_label.setStyleSheet("""
            color: #c0c0c0;
            font-size: 12px;
            font-weight: medium;
        """)

        content_layout.addWidget(self.message_label)
        content_layout.addWidget(self.message_text_label)
        content_layout.addStretch()
        
        # 按钮区域
        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(0, 10, 0, 10)
        button_layout.setSpacing(20)
        button_layout.addStretch()
        
        self.confirm_button = QPushButton("确认")
        self.confirm_button.setFixedSize(100, 35)
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
        self.confirm_button.clicked.connect(self.accept)
        button_layout.addWidget(self.confirm_button)
        
        # 取消按钮  TODO 待加载背景图
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setFixedSize(100, 35)
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
    
    def set_title(self, title):
        self.title = title
        self.title_label.setText(self.title)

    def set_message(self, message):
        self.message = message
        self.message_label.setText(self.message)

    def set_message_text(self, message_text):
        self.message_text = message_text
        self.message_text_label.setText(self.message_text)

    def add_shadow_effect(self):
        """添加自定义阴影效果"""
        shadow = QGraphicsDropShadowEffect(self.main_widget)
        shadow.setBlurRadius(20)  # 阴影模糊半径
        shadow.setColor(QColor(0, 0, 0, 150))  # 阴影颜色和透明度
        shadow.setOffset(0, 0)  # 零偏移量确保阴影均匀分布在四周
        
        # 应用阴影效果
        self.main_widget.setContentsMargins(25, 25, 25, 25)  # 四周均匀的边距
        self.main_widget.setGraphicsEffect(shadow)
    
    def set_messages(self, mess):
        """设置提示信息"""
        self.message_label.setText(mess)

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

