# 折叠面板
import os

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QRadioButton, 
    QPushButton, QGroupBox, QFileDialog
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QPixmap
from ui.widgets.radio import QMRadioButton, QMRadioGroup


class CollapsePanel(QWidget):
    """可折叠的面板"""
    
    collapse_changed = Signal(bool)  # 折叠面板折叠展开的信号
    
    def __init__(self, parent, text, messages=None, text_font_size=10, messages_font_size=9, slot_header=None, slot_content=None):
        super().__init__(parent)
        self.text = text
        self.messages = messages
        self.text_font_size = text_font_size
        self.messages_font_size = messages_font_size
        self.slot_header = slot_header
        self.slot_content = slot_content

        self.resource_path = parent.resource_path
        self.is_expanded = False  # 初始状态为折叠
        self.current_java_path = ""  # 当前 Java 路径
        self.available_versions = []  # 可用的 Java 版本
        self.init_ui()
        
    def init_ui(self):
        """初始化 UI"""
        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 标题栏
        self.header = self.create_header()
        main_layout.addWidget(self.header)
        
        # 内容区域
        self.content = self.create_content()
        main_layout.addWidget(self.content)
        self.content.hide()  # 初始隐藏内容区域
        
    def create_header(self):
        """创建标题栏"""
        header = QWidget()
        header.setFixedHeight(58)
        header.setStyleSheet("""
            QWidget {
                background-color: rgba(190, 183, 255, 0.3);
            }
        """)
        header.setCursor(Qt.PointingHandCursor)
        header.mousePressEvent = self.toggle_expand  # 点击切换展开/折叠
        
        # 布局
        layout = QHBoxLayout(header)
        layout.setContentsMargins(15, 10, 15, 10)
        
        # 标题
        if self.slot_header:
            layout.addWidget(self.slot_header)
        else:
            create_content = QWidget()
            create_content.setStyleSheet("color: #FFFFFF; background-color: transparent;")
            create_layout = QVBoxLayout(create_content)
            create_layout.setContentsMargins(0, 3, 0, 3)
            create_layout.setSpacing(0)
            layout.addWidget(create_content)
            title_label = QLabel(self.text)
            title_label.setFont(QFont("Source Han Sans CN Heavy", self.text_font_size))
            title_label.setStyleSheet("color: #FFFFFF; background-color: transparent;")
            create_layout.addWidget(title_label)
            
            if self.messages:
                self.messages_label = QLabel(self.messages)
                self.messages_label.setFont(QFont("Source Han Sans CN", self.messages_font_size))
                self.messages_label.setStyleSheet("color: #AAAAAA; background-color: transparent;")
                self.messages_label.setAlignment(Qt.AlignVCenter)
                create_layout.addWidget(self.messages_label, 1)
            
        # 展开/折叠图标
        self.expand_icon = QLabel()
        self.expand_icon.setFixedSize(16, 16)
        self.expand_icon.setStyleSheet("color: #AAAAAA; background-color: transparent;")
        self.update_expand_icon()
        layout.addWidget(self.expand_icon)
        
        return header
    
    def create_content(self):
        """创建内容区域"""
        content = QWidget()
        content.setStyleSheet("background-color: rgba(190, 183, 255, 0.2);")
        
        # 布局
        layout = QVBoxLayout(content)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(5)

        if self.slot_content:
            layout.addWidget(self.slot_content)
            return content
        
        # 自动选择选项
        # 创建按钮组
        self.button_group = QMRadioGroup()
        self.button_group.button_selected.connect(self.on_auto_clicked)

        # 创建自动选择按钮
        auto_button = QMRadioButton(
            self,
            "使用推荐的 Java 版本",
            "系统将自动选择最适合的 Java 版本",
            text_font_size=10,
            messages_font_size=9
        )
        layout.addWidget(auto_button)
        self.button_group.add_button(auto_button)

        # 创建版本按钮
        self.available_versions = [
            {"version": "21.0.7", "path": "C:\\Program Files\\Java\\jdk-21.0.7"},
            {"version": "17.0.10", "path": "C:\\Program Files\\Java\\jdk-17.0.10"},
            {"version": "11.0.22", "path": "C:\\Program Files\\Java\\jdk-11.0.22"},
            {"version": "8.0.402", "path": "C:\\Program Files\\Java\\jdk-8.0.402"}
        ]
        for java in self.available_versions:
            version_button = QMRadioButton(
                self,
                java.get('version'),
                java.get('path'),
                text_font_size=10,
                messages_font_size=9
            )
            layout.addWidget(version_button)
            self.button_group.add_button(version_button)

        # 创建自定义按钮
        # 定义插槽
        desc = QWidget()
        desc_layout = QHBoxLayout(desc)
        desc_layout.setContentsMargins(0, 0, 0, 0)
        desc_layout.setSpacing(0)

        # 创建描述内容容器
        desc_content = QWidget()
        desc_content.setStyleSheet('background-color: rgba(0, 0, 0, 0.3);')
        desc_content.setFixedHeight(27)

        # 创建内部布局 - 确保文本居中
        inner_layout = QHBoxLayout(desc_content)
        inner_layout.setContentsMargins(5, 0, 5, 0)  # 左右留出边距
        inner_layout.setAlignment(Qt.AlignCenter)  # 关键：设置布局居中对齐

        # 创建文本标签
        desc_text = QLabel('C:\\Program Files\\Java\\jdk-21.0.7')
        desc_text.setStyleSheet("color: rgba(255, 255, 255, 0.7); background-color: transparent;")
        desc_text.setAlignment(Qt.AlignCenter)  # 文本在标签内居中

        # 添加到内部布局
        inner_layout.addWidget(desc_text)
        inner_layout.addStretch()

        # 添加到主布局
        desc_layout.addWidget(desc_content)

        desc_icon = QLabel()
        desc_icon.setFixedSize(25, 25)
        desc_icon.setAlignment(Qt.AlignCenter)  # 关键：设置居中对齐
        desc_icon.setPixmap(QPixmap(
            os.path.join(self.resource_path, 'images', 'version', 'folder.png')
        ).scaled(12, 12, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        desc_icon.setStyleSheet('background-color: rgba(190, 183, 255, 0.19); border: 1px solid rgba(139, 133, 218, 1);')
        desc_layout.addWidget(desc_icon)

        custom_button = QMRadioButton(
            self,
            "自定义 Java 路径",
            "使用自定义 Java 安装路径",
            text_font_size=10,
            messages_font_size=9,
            slot_desc=desc
        )
        layout.addWidget(custom_button)
        self.button_group.add_button(custom_button)

        # 设置默认选中
        auto_button.set_selected(True)
        return content

    def on_auto_clicked(self, proprty: tuple):
        """处理自动选择标签点击事件"""
        print(proprty)

    def toggle_expand(self, event):
        """切换展开/折叠状态"""
        self.is_expanded = not self.is_expanded
        self.content.setVisible(self.is_expanded)
        self.update_expand_icon()
        
    def update_expand_icon(self):
        """更新展开/折叠图标"""
        import os
        self.collapse_changed.emit(self.is_expanded)
        icon_name = "fold-up.png" if self.is_expanded else "expand.png"
        # 这里假设有图标资源，实际使用时替换为您的图标路径
        self.expand_icon.setPixmap(QPixmap(
            os.path.join(self.resource_path, 'images', 'version', icon_name)
        ).scaled(16, 16, Qt.KeepAspectRatio, Qt.SmoothTransformation))
