"""无可用版本弹出框"""

import os
from PySide6.QtWidgets import (
    QDialog, QLabel, QVBoxLayout, QHBoxLayout, QPushButton, 
    QWidget, QFrame, QApplication
)
from PySide6.QtCore import Qt, Signal, QPoint
from PySide6.QtGui import QColor, QPalette, QFont, QMouseEvent


class NoVersionDialog(QDialog):
    """无可用版本弹出框 - 独立窗口"""
    
    download_signal = Signal()  # 下载游戏信号

    def __init__(self, resource_path, parent=None):
        """初始化无可用版本弹出框"""
        # 不传递parent，使其成为独立窗口
        super().__init__(None)
        self._parent = parent
        self.resource_path = resource_path
        
        # 拖拽相关变量
        self._dragging = False
        self._drag_position = QPoint()

        # 设置窗口属性 - 独立窗口
        self.setWindowFlags(
            Qt.Window |  # 独立窗口
            Qt.FramelessWindowHint |  # 无边框
            Qt.WindowStaysOnTopHint  # 保持在最前
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(370, 188)  # 用户指定的尺寸
        
        # 设置窗口背景色
        palette = self.palette()
        palette.setColor(QPalette.Window, QColor(39, 41, 55))
        self.setPalette(palette)
        
        self.init_ui()
        self.center_on_screen()  # 在屏幕中央显示
        
    def init_ui(self):
        """初始化用户界面"""
        # 创建主布局，直接设置到对话框上
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 创建主容器widget
        container = QWidget()
        container.setFixedSize(370, 188)
        container.setStyleSheet("background-color: rgba(39, 41, 55, 1);")
        
        # 容器内部布局
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(10, 8, 10, 8)
        container_layout.setSpacing(0)
        
        # 标题文本 - "无可用版本"
        self.title_label = QLabel("无可用版本")
        self.title_label.setFont(QFont("Microsoft YaHei", 12, QFont.Weight.Medium))
        self.title_label.setStyleSheet("""
            color: #FFFFFF;
            font-size: 12px;
            font-weight: 500;
            background-color: transparent;
        """)
        self.title_label.setAlignment(Qt.AlignCenter)
        container_layout.addWidget(self.title_label)
        
        # 标题下方间距8px
        container_layout.addSpacing(8)
        
        # 分割线 - 高度2px
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFixedHeight(2)
        separator.setStyleSheet("background-color: rgba(139, 133, 218, 1); border: none;")
        container_layout.addWidget(separator)
        
        # 分割线下方间距30px
        container_layout.addSpacing(30)
        
        # 说明文本区域 - 水平居中
        text_container = QWidget()
        text_container.setStyleSheet("background-color: transparent;")
        text_layout = QHBoxLayout(text_container)
        text_layout.setContentsMargins(0, 0, 0, 0)
        
        # 添加弹性空间使文本居中
        text_layout.addStretch()
        
        self.description_label = QLabel(
            "未找到任何版本的游戏，请先下载任意版本的游戏\n"
            "若有已存在的游戏，请在左边的列表中选择添加文件夹，选\n"
            "择.minecraft文件夹将其导入。"
        )
        self.description_label.setFixedSize(300, 60)  # 增加高度以适应新的行间距
        self.description_label.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Medium))
        self.description_label.setStyleSheet("""
            color: #FFFFFF;
            font-size: 10px;
            font-weight: 500;
            line-height: 15px;
            background-color: transparent;
        """)
        self.description_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)  # 文字内部左对齐
        self.description_label.setWordWrap(True)
        
        text_layout.addWidget(self.description_label)
        text_layout.addStretch()
        
        container_layout.addWidget(text_container)
        
        # 添加弹性空间，将按钮推到底部
        container_layout.addStretch()
        
        # 下载按钮区域 - 168x35px，水平居中
        button_container = QWidget()
        button_container.setStyleSheet("background-color: transparent;")
        button_layout = QHBoxLayout(button_container)
        button_layout.setContentsMargins(0, 0, 0, 0)
        
        # 添加弹性空间使按钮居中
        button_layout.addStretch()
        
        self.download_button = QPushButton("下载游戏")
        self.download_button.setFixedSize(168, 35)  
        self.download_button.setFont(QFont("Microsoft YaHei", 12, QFont.Weight.Medium))
        
        # 构建图片路径
        download_image_path = os.path.join(self.resource_path, "images", "Install", "DownloadGame.png")
        # 将路径中的反斜杠替换为正斜杠，避免CSS解析问题
        download_image_path = download_image_path.replace("\\", "/")
        
        self.download_button.setStyleSheet(f"""
            QPushButton {{
                background-image: url({download_image_path});
                background-repeat: no-repeat;
                background-position: center;
                color: #FFFFFF;
                font-size: 12px;
                font-weight: 500;
                border: none;
                border-radius: 0px;
            }}
            QPushButton:hover {{
                background-image: url({download_image_path});
                opacity: 0.8;
            }}
            QPushButton:pressed {{
                background-image: url({download_image_path});
                opacity: 0.6;
            }}
        """)
        
        # 连接按钮信号
        self.download_button.clicked.connect(self.on_download_clicked)
        
        button_layout.addWidget(self.download_button)
        button_layout.addStretch()
        
        container_layout.addWidget(button_container)
        
        # 将容器添加到主布局
        main_layout.addWidget(container, 0, Qt.AlignCenter)
        
    def on_download_clicked(self):
        """处理下载按钮点击事件"""
        self.download_signal.emit()
        self.accept()  # 关闭对话框
        
    def center_on_screen(self):
        """将对话框居中显示在屏幕上"""
        screen = QApplication.primaryScreen()
        screen_geometry = screen.availableGeometry()
        x = (screen_geometry.width() - self.width()) // 2
        y = (screen_geometry.height() - self.height()) // 2
        self.move(x, y)
        
    def center_on_parent(self):
        """将对话框居中显示在父窗口上（保留兼容性）"""
        # 现在总是在屏幕中央显示，因为是独立窗口
        self.center_on_screen()
        
    def mousePressEvent(self, event: QMouseEvent):
        """鼠标按下事件 - 开始拖拽"""
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._drag_position = event.globalPosition().toPoint() - self.pos()
            event.accept()
        else:
            super().mousePressEvent(event)
            
    def mouseMoveEvent(self, event: QMouseEvent):
        """鼠标移动事件 - 执行拖拽"""
        if self._dragging and event.buttons() == Qt.LeftButton:
            new_pos = event.globalPosition().toPoint() - self._drag_position
            self.move(new_pos)
            event.accept()
        else:
            super().mouseMoveEvent(event)
            
    def mouseReleaseEvent(self, event: QMouseEvent):
        """鼠标释放事件 - 结束拖拽"""
        if event.button() == Qt.LeftButton:
            self._dragging = False
            event.accept()
        else:
            super().mouseReleaseEvent(event)
    
    def showEvent(self, event):
        """重写showEvent确保每次显示时都居中"""
        super().showEvent(event)
        self.center_on_screen()