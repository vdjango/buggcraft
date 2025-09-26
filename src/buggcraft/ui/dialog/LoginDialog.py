import threading
import time
import sys
import os

from PySide6.QtWidgets import (
    QDialog, QLabel, QVBoxLayout, QHBoxLayout, QPushButton, 
    QWidget, QApplication, QFrame, QGraphicsDropShadowEffect
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPalette, QMouseEvent, QPixmap

from core.auth.microsoft import MicrosoftAuthenticator, MinecraftSignals


class LoginWaitDialog(QDialog):

    cancel_signal = Signal()  # 取消
    reopen_signal = Signal()  # 重新打开浏览器

    def __init__(self, resource_path, cache_path, parent=None):
        super().__init__(parent)
        self._parent = parent
        self.resource_path = resource_path
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(650, 300)
        
        self.auth = MicrosoftAuthenticator(skins_cache_path=cache_path)
        self.auth.signals.success.connect(self.close_reject)
        
        # 设置窗口背景色 RGBA(39, 41, 55, 1)
        palette = self.palette()
        palette.setColor(QPalette.Window, QColor(39, 41, 55))
        self.setPalette(palette)
        
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
        
        # 添加Minecraft图标
        self.minecraft_icon = QLabel()
        minecraft_icon_path = os.path.abspath(os.path.join(self.resource_path, 'images', 'user', 'logo_minecraft.png'))
        minecraft_pixmap = QPixmap(minecraft_icon_path)
        if not minecraft_pixmap.isNull():
            self.minecraft_icon.setPixmap(minecraft_pixmap.scaled(
                13, 16,
                Qt.IgnoreAspectRatio,
                Qt.SmoothTransformation
            ))
        self.minecraft_icon.setStyleSheet("background-color: transparent;")
        self.minecraft_icon.setAlignment(Qt.AlignCenter)

        self.title_label = QLabel("登录到 Minecraft")
        self.title_label.setStyleSheet("""
            color: rgba(220, 220, 220, 1);
            font-size: 21px;
            font-weight: bold;
        """)
        title_layout.addWidget(self.minecraft_icon)
        title_layout.addSpacing(10)
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
        self.info_label = QLabel("嘿！正在为您打开登录页面~")
        self.info_label.setWordWrap(True)
        self.info_label.setStyleSheet("""
            color: #e0e0e0;
            font-size: 16px;
            font-weight: bold;
        """)
        info2_label = QLabel("请在浏览器中完成Microsoft账户登录操作，完成后将自动返回主界面。 如果身份验证成功未返回主界面，请手动回到我这里哦！")
        info2_label.setWordWrap(True)
        info2_label.setContentsMargins(0, 20, 0, 15)
        info2_label.setStyleSheet("""
            color: #c0c0c0;
            font-size: 14px;
            font-weight: medium;
        """)
        info3_label = QLabel("如果发现问题，欢迎反馈，QQ群：849362477")
        info3_label.setWordWrap(True)
        info3_label.setStyleSheet("""
            color: #c0c0c0;
            font-size: 13px;
            font-weight: medium;
        """)
        content_layout.addWidget(self.info_label)
        content_layout.addWidget(info2_label)
        content_layout.addWidget(info3_label)
        content_layout.addStretch()
        
        # 按钮区域
        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(0, 10, 0, 10)
        button_layout.setSpacing(20)
        button_layout.addStretch()
        
        # 重新打开按钮  TODO 待加载背景图
        self.reopen_button = QPushButton("重新登录")
        self.reopen_button.setFixedSize(100, 35)
        self.reopen_button.setStyleSheet("""
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
        self.reopen_button.clicked.connect(self.reopen_browser)
        button_layout.addWidget(self.reopen_button)
        
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
        self.cancel_button.clicked.connect(self.cancel_reject)
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
    
    def set_messages(self, mess):
        """设置提示信息"""
        self.info_label.setText(mess)

    def start_login_process(self):
        """开始登录流程"""
        self.auth.signals.failure.connect(self.set_messages)
        self.auth.signals.progress.connect(self.set_messages)
        self.reopen_signal.emit()
        QTimer.singleShot(500, self.auth.start_login)
        
    def reopen_browser(self):
        """重新打开浏览器"""
        self.auth.signals.failure.disconnect(self.set_messages)
        self.auth.signals.progress.disconnect(self.set_messages)
        self.auth.cancel_authentication()
        self.start_login_process()

    def cancel_reject(self):
        """取消"""
        self.auth.cancel_authentication()
        self.close_reject()

    def close_reject(self):
        """关闭窗口"""
        self.set_messages("嘿！正在为您打开登录页面~")
        self.auth.signals.failure.disconnect(self.set_messages)
        self.auth.signals.progress.disconnect(self.set_messages)
        self.cancel_signal.emit()
        self.reject()

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


# 示例使用
if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # 模拟点击"正版登录"按钮
    def start_login():
        dialog = LoginWaitDialog()
        result = dialog.exec()
        if result == QDialog.Accepted:
            print("登录完成，继续后续操作")
        else:
            print("登录取消")
        
        sys.exit()
    
    start_login()
    
    sys.exit(app.exec())
