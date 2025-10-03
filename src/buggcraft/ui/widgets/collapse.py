import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QApplication
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QPixmap


class CollapsePanel(QWidget):
    """优化的可折叠面板 - 高度可复用"""
    
    collapse_changed = Signal(bool)  # 折叠面板折叠展开的信号
    
    def __init__(self,
        parent,
        title,
        messages=None,
        expanded = False,
        content=None, 
        header_height=60,
        content_height=None,
        is_collaspe=True,
        expand_icon_size=16,
        text_font_size=10,
        messages_font_size=9,
        custom_button=None
    ):
        """
        初始化可折叠面板
        :param parent: 父组件
        :param title: 面板标题
        :param messages: 面板desc信息
        :param expanded: 面板默认是否展开
        :param is_collaspe: 是否开启折叠面板功能
        :param content: 内容组件 (可选)
        :param header_height: 标题栏高度
        :param content_height: 内容区域高度 (可选)
        :param header_bg_color: 标题栏背景颜色
        :param content_bg_color: 内容区域背景颜色
        :param expand_icon_size: 展开/折叠图标大小
        :param text_font_size: 标题字体大小
        :param messages_font_size: 描述字体大小
        :param custom_button: 自定义按钮 (可选)
        """
        super().__init__(parent)
        self.title = title
        self.messages = messages
        self.content = content
        self.is_collaspe = is_collaspe
        self.header_height = header_height
        self.content_height = content_height
        self.header_bg_color = "rgba(190, 183, 255, 0.3)"
        self.content_bg_color = "rgba(190, 183, 255, 0.2)"
        self.expand_icon_size = expand_icon_size
        self.text_font_size = text_font_size
        self.messages_font_size = messages_font_size
        self.custom_button = custom_button
        
        self.resource_path = parent.resource_path
        self.is_expanded = False  # 初始状态为折叠
        self.init_ui()

        if expanded and self.is_collaspe:
            self.toggle_expand(False)
        
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
        self.content = self.create_content_area()
        main_layout.addWidget(self.content)
        if self.is_collaspe:
            self.content.hide()  # 初始隐藏内容区域
        
    def create_header(self):
        """创建标题栏"""
        header = QWidget()
        header.setFixedHeight(self.header_height)
        header.setStyleSheet(f"""
            QWidget {{
                background-color: {self.header_bg_color};
            }}
        """)
        if self.is_collaspe:
            header.setCursor(Qt.PointingHandCursor)
            header.mousePressEvent = self.toggle_expand  # 点击切换展开/折叠
        
        # 布局
        layout = QHBoxLayout(header)
        layout.setContentsMargins(25, 10, 25, 10)
        
        # 标题容器
        title_container = QWidget()
        title_container.setStyleSheet("background-color: transparent;")
        title_layout = QVBoxLayout(title_container)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(0)
        
        # 标题
        self.title_label = QLabel(self.title)
        self.title_label.setFont(QFont("Source Han Sans CN Normal", self.text_font_size, QFont.Weight.Bold)) 
        self.title_label.setStyleSheet("color: #FFFFFF; background-color: transparent;")
        title_layout.addWidget(self.title_label)

        if self.messages:
            self.messages_label = QLabel(self.messages)
            self.messages_label.setFont(QFont("Source Han Sans CN Normal", self.messages_font_size, QFont.Weight.Normal))
            self.messages_label.setStyleSheet("color: #AAAAAA; background-color: transparent;")
            self.messages_label.setAlignment(Qt.AlignVCenter)
            title_layout.addWidget(self.messages_label)
        
        # 添加标题容器到布局
        layout.addWidget(title_container, 1)
        
        # 添加自定义按钮
        if self.custom_button:
            layout.addWidget(self.custom_button)
        
        # 展开/折叠图标
        if self.is_collaspe:
            self.expand_icon = QLabel()
            self.expand_icon.setFixedSize(self.expand_icon_size, self.expand_icon_size)
            self.expand_icon.setStyleSheet("color: #AAAAAA; background-color: transparent;")
            self.update_expand_icon()
            layout.addWidget(self.expand_icon)
        
        return header
    
    def create_content_area(self):
        """创建内容区域"""
        # 创建容器
        container = QWidget()
        container.setStyleSheet(f"background-color: {self.content_bg_color};")
        
        # 设置高度（如果指定）
        if self.content_height:
            container.setFixedHeight(self.content_height)
        
        # 创建布局
        layout = QVBoxLayout(container)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(5)
        
        # 添加内容组件
        if self.content:
            layout.addWidget(self.content)
        
        return container
    
    def set_title(self, name):
        self.title_label.setText(name)
        self.update()
        QApplication.processEvents()

    def set_messages(self, message):
        self.messages_label.setText(message)
        self.update()

    def set_content(self, content):
        """设置内容组件"""
        # 清除现有内容
        layout = self.content.layout()
        for i in reversed(range(layout.count())):
            # 移除所有子部件
            item = layout.itemAt(i)
            if item.widget():
                item.widget().setParent(None)
            layout.removeItem(item)

        # 添加新内容
        layout.addWidget(content)
    
    def set_disabled(self, disabled):
        if disabled:
            self.header.setStyleSheet(f"""
                QWidget {{
                    background-color: {self.header_bg_color};
                }}
            """)
            self.content.setStyleSheet(f"background-color: {self.content_bg_color};")
        else:
            self.header.setStyleSheet(f"""
                QWidget {{
                    background-color: rgba(148, 147, 158, 0.4);
                }}
            """)
            self.content.setStyleSheet(f"background-color: rgba(148, 147, 158, 0.3);")
    
        self.setDisabled(not disabled)
        self.update()

    def toggle_expand(self, event):
        """切换展开/折叠状态"""
        self.is_expanded = not self.is_expanded
        self.content.setVisible(self.is_expanded)
        self.update_expand_icon()
        self.collapse_changed.emit(self.is_expanded)
        
    def update_expand_icon(self):
        """更新展开/折叠图标"""
        icon_name = "fold-up.png" if self.is_expanded else "expand.png"
        icon_path = os.path.join(self.resource_path, 'images', 'version', icon_name)
        
        if os.path.exists(icon_path):
            pixmap = QPixmap(icon_path)
            if not pixmap.isNull():
                self.expand_icon.setPixmap(pixmap.scaled(
                    self.expand_icon_size, self.expand_icon_size, 
                    Qt.KeepAspectRatio, Qt.SmoothTransformation
                ))
        else:
            # 如果图标不存在，使用默认样式
            if self.is_expanded:
                self.expand_icon.setStyleSheet("""
                    background-color: #7959FF;
                    border-radius: 8px;
                """)
            else:
                self.expand_icon.setStyleSheet("""
                    background-color: transparent;
                    border-radius: 8px;
                    border: 2px solid #888888;
                """)
    
    def set_expanded(self, expanded):
        """设置展开/折叠状态"""
        if expanded != self.is_expanded:
            self.toggle_expand(None)
            print('toggle_expand', expanded)
    
    # @property
    # def is_expanded(self):
    #     """返回当前是否展开"""
    #     return self.is_expanded
