"""版本删除确认"""

import sys
import os

from PySide6.QtWidgets import (
    QDialog, QLabel, QVBoxLayout, QHBoxLayout, QPushButton, 
    QWidget, QApplication, QFrame, QGraphicsDropShadowEffect
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPalette, QMouseEvent, QFont
from core.auth.microsoft import MicrosoftAuthenticator, MinecraftSignals


class VersionNotFuilDialog(QDialog):

    import_signal = Signal()  # 导入
    download_signal = Signal()  # 下载

    def __init__(self, parent=None):
        """打开启动器没有发现版本时提示"""
        super().__init__(parent)
        self._parent = parent

        self.title = '就差最后一步啦！'
        self.message = "看起来您还没有安装任何 Minecraft 游戏版本！"
        self.message_text = "在开始建造和探索之前，您需要先安装一个游戏版本。如果您之前玩过 Minecraft，可以导入现有游戏文件；或者直接下载一个新版本开始全新的冒险！"

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(550, 300)
        
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
        self.title_label.setStyleSheet("color: rgba(255, 255, 255, 0.8); background-color: transparent;")

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
        content_layout.setContentsMargins(18, 10, 18, 10)
        content_layout.setSpacing(0)
        
        # 提示信息
        self.message_label = QLabel(self.message)
        self.message_label.setFont(QFont("Source Han Sans CN Normal", 10, QFont.Weight.Black))
        self.message_label.setStyleSheet("color: rgba(255, 255, 255, 0.8); background-color: transparent;")
        self.message_label.setWordWrap(True)

        self.message_text_label = QLabel(self.message_text)
        self.message_text_label.setWordWrap(True)
        self.message_text_label.setContentsMargins(0, 10, 0, 10)
        self.message_text_label.setFont(QFont("Source Han Sans CN Normal", 9, QFont.Weight.Medium))
        self.message_text_label.setStyleSheet("color: rgba(255, 255, 255, 0.6); background-color: transparent;")

        content_layout.addWidget(self.message_label)
        content_layout.addWidget(self.message_text_label)
        content_layout.addStretch()
        
        # 按钮区域
        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(0, 10, 0, 10)
        button_layout.setSpacing(20)
        button_layout.addStretch()
        
        self.confirm_button = QPushButton("导入游戏")
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
        self.confirm_button.clicked.connect(self.on_import)
        button_layout.addWidget(self.confirm_button)

        self.confirm_button = QPushButton("下载游戏")
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
        self.confirm_button.clicked.connect(self.on_download)
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

    def add_shadow_effect(self):
        """添加自定义阴影效果"""
        shadow = QGraphicsDropShadowEffect(self.main_widget)
        shadow.setBlurRadius(20)  # 阴影模糊半径
        shadow.setColor(QColor(0, 0, 0, 150))  # 阴影颜色和透明度
        shadow.setOffset(0, 0)  # 零偏移量确保阴影均匀分布在四周
        
        # 应用阴影效果
        self.main_widget.setContentsMargins(25, 25, 25, 25)  # 四周均匀的边距
        self.main_widget.setGraphicsEffect(shadow)

    def set_title(self, name):
        self.title_label.setText(name)
    
    def set_message(self, message):
        self.message_label.setText(message)
    
    def set_message_text(self, message):
        self.message_text_label.setText(message)
        
    def on_download(self):
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

