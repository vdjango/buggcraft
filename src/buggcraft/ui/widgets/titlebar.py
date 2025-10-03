import os
from PySide6.QtWidgets import (
    QWidget, QLabel, QHBoxLayout
)
from PySide6.QtGui import QFont, QPixmap, QMouseEvent
from PySide6.QtCore import Qt, QPoint, Signal


class TitleBar(QWidget):
    """标题栏 - 保留原有样式和功能"""
    
    tab_switch_clicked = Signal(str)
    menu_toggle_signal = Signal(bool)
    
    def __init__(self, parent, resource_path):
        super().__init__(parent)
        self.parent = parent
        self.setObjectName("TitleBar")
        
        self.resource_path = resource_path
        self.dragging = False
        self.drag_position = QPoint()
        
        self.menu_collapsed = False
        self.is_animating = False
        
        self.tab_names = ["开始", "下载", "设置"]  # 标签页配置
        # 版本 没有添加，因为版本 是下拉选项 不是单独页面
        self.tab_version_names = ["实例"]
        self.active_tab = 0
        
        # 设置高度
        self.setFixedHeight(50)
        
        # 创建布局
        self.init_ui()
    
    def init_ui(self):
        """初始化 UI - 使用正常布局"""
        # 主水平布局
        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(215, 0, 11, 0)
        self.main_layout.setSpacing(0)
        
        # 创建标签按钮容器
        tab_container = QWidget()
        tab_container.setContentsMargins(0, 0, 0, 0)
        tab_container.setStyleSheet("background: transparent;")
        tab_layout = QHBoxLayout(tab_container)
        tab_layout.setContentsMargins(0, 0, 0, 6)
        tab_layout.setSpacing(0)
        
        # 折叠按钮
        toggle_button, self.icon_toggle = self.create_toggle_button()
        tab_layout.addWidget(toggle_button, 0, Qt.AlignCenter)
        tab_layout.addSpacing(15)
        
        # 创建标签按钮
        self.tab_buttons = []
        for name in self.tab_names:
            tab_button, icon_label = self.create_image_button(name)
            self.tab_buttons.append((tab_button, None, icon_label))
            tab_layout.addWidget(tab_button, 0, Qt.AlignCenter)
        
        tab_layout.addStretch()
        
        # 将容器添加到主布局
        self.main_layout.addWidget(tab_container)
        self.main_layout.addStretch(1)
        
        container = QWidget()
        container.setStyleSheet("background: transparent;")
        container_layout = QHBoxLayout(container)
        container_layout.setContentsMargins(0, 7, 0, 0)
        container_layout.setSpacing(0)

        # 创建版本选择按钮
        version_selection_btn= self.create_version_selection_button("版本", 125)
        container_layout.addWidget(version_selection_btn, 0, Qt.AlignCenter)
        container_layout.addSpacing(5)
        
        # 创建版本设置按钮
        version_settings_btn, (content_container, icon_label) = self.create_version_settings_button("实例", 110)
        container_layout.addWidget(version_settings_btn, 0, Qt.AlignCenter)
        container_layout.addSpacing(5)
        self.tab_buttons.append((version_settings_btn, content_container, icon_label))
        
        # 创建最小化按钮
        minimize_btn = self.create_control_button("最小化", "min.png")
        minimize_btn.mousePressEvent = lambda e: self.parent.showMinimized()
        container_layout.addWidget(minimize_btn)
        container_layout.addSpacing(5)
        
        # 创建关闭按钮
        close_btn = self.create_control_button("关闭", "close.png")
        close_btn.mousePressEvent = lambda e: self.parent.close()
        container_layout.addWidget(close_btn)

        self.main_layout.addWidget(container)
        # 设置初始选中状态
        self.set_active_tab('开始')

    def get_image_path(self, image_name):
        """获取图片绝对路径"""
        return os.path.abspath(os.path.join(
            self.resource_path, 'images', 'bar', image_name
        ))
    
    def get_version_image_path(self, image_name):
        """获取版本图片绝对路径"""
        return os.path.abspath(os.path.join(
            self.resource_path, 'images', 'version', image_name
        ))

    def create_toggle_button(self, width=40, height=45, icon_size=20):
        """
        创建带图标和文本的图片按钮
        :param text: 按钮文本
        :param width: 按钮宽度
        :param height: 按钮高度
        :param font_size: 字体大小
        :param icon_size: 图标大小
        """
        # 设置背景图片
        icon_path = self.get_image_path('ic.png')

        # 创建内容容器
        content = QWidget()
        content.setFixedHeight(height)
        content.setContentsMargins(0, 0, 0, 0)

        # 创建图标布局
        layout = QHBoxLayout(content)
        layout.setContentsMargins(0, 15, 0, 0)
        layout.setSpacing(0)
        
        # 添加图标
        icon_label = QLabel()
        icon_label.setCursor(Qt.PointingHandCursor)
        icon_pixmap = QPixmap(icon_path).scaled(icon_size, icon_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        # icon_label.setPixmap(icon_pixmap)
        icon_label.setStyleSheet('background-color: rgba(0, 137, 77, 0.6);')  # rgba(169, 137, 77, 1)
        icon_label.setFixedSize(40, 30)  # 40, 21
        icon_label.mousePressEvent = lambda e: self.toggle_menu()
        layout.addWidget(icon_label,)
        
        return content, icon_label

    def create_image_button(self, text, width=100, height=40, font_size=11, icon_size=20):
        """
        创建带图标和文本的图片按钮
        :param text: 按钮文本
        :param width: 按钮宽度
        :param height: 按钮高度
        :param font_size: 字体大小
        :param icon_size: 图标大小
        """
        # 设置背景图片
        image_path = self.get_image_path('no-menu.png')
        icon_path = self.get_image_path('no-ic.png')

        # 创建按钮容器
        button = QLabel()
        button.setCursor(Qt.PointingHandCursor)
        button.setFixedSize(width, height)
        button.mousePressEvent = lambda e: self.on_tab_clicked(text)
        button.setPixmap(QPixmap(image_path).scaled(width, height, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
        
        # 创建内容容器
        content_container = QWidget(button)
        content_container.setGeometry(0, 0, width, height)
        
        # 创建图标布局
        layout = QHBoxLayout(content_container)
        layout.setContentsMargins(0, 8, 15, 0)
        layout.setSpacing(0)
        
        # 添加图标
        icon_label = QLabel(content_container)
        icon_pixmap = QPixmap(icon_path).scaled(icon_size, icon_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        icon_label.setPixmap(icon_pixmap)
        icon_label.setAlignment(Qt.AlignCenter)
        
        # 添加文本
        text_label = QLabel(text, content_container)
        text_label.setFont(QFont("Source Han Sans CN Normal", font_size, QFont.Weight.Bold))
        text_label.setStyleSheet("color: #f2f2f2; background-color: transparent;")
        text_label.setAlignment(Qt.AlignCenter)
        text_label.setContentsMargins(0, 0, 0, 0)
        
        # 根据图标位置添加部件
        layout.addStretch()
        layout.addWidget(icon_label)
        layout.addWidget(text_label)
        layout.addStretch()

        return button, icon_label

    def create_version_settings_button(self, text, width=128, height=32, font_size=11, icon_size=20):
        """
        创建版本设置按钮
        :param text: 按钮文本
        :param width: 按钮宽度
        :param height: 按钮高度
        :param font_size: 字体大小
        :param icon_size: 图标大小
        """
        # 设置背景图片
        image_path = self.get_image_path('version_settings_background.png')
        icon_path = self.get_image_path('no-ic.png')

        # 创建按钮容器
        button = QLabel()
        button.setCursor(Qt.PointingHandCursor)
        button.setFixedSize(width, height)
        button.mousePressEvent = lambda e: self.on_tab_clicked(text)
        button.setPixmap(QPixmap(image_path).scaled(width, height, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
        
        # 创建内容容器
        content_container = QWidget(button)
        content_container.setContentsMargins(0, 0, 0, 0)
        content_container.setStyleSheet('background-color: transparent;')  # rgba(110, 99, 255, 0.5)
        content_container.setGeometry(5, 5, width-10, height-13)
        
        # 创建图标布局
        layout = QHBoxLayout(content_container)
        layout.setContentsMargins(0, 0, 17, 0)
        layout.setSpacing(0)
        
        # 添加图标
        icon_label = QLabel(content_container)
        icon_label.setStyleSheet('background-color: transparent;')
        icon_pixmap = QPixmap(icon_path).scaled(icon_size, icon_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        icon_label.setPixmap(icon_pixmap)
        icon_label.setAlignment(Qt.AlignCenter)
        
        # 添加文本
        text_label = QLabel(text, content_container)
        text_label.setFont(QFont("Source Han Sans CN Normal", font_size, QFont.Weight.Bold))
        text_label.setStyleSheet("color: #f2f2f2; background-color: transparent;")
        text_label.setAlignment(Qt.AlignCenter)
        text_label.setContentsMargins(0, 0, 0, 0)
        
        # 根据图标位置添加部件
        layout.addStretch()
        layout.addWidget(icon_label)
        layout.addWidget(text_label)
        layout.addStretch()

        return button, (content_container, icon_label)
    
    def create_version_selection_button(self, text, width=128, height=32, font_size=11, icon_size=12):
        """
        创建版本选择按钮 - 带下拉箭头
        :param text: 按钮文本
        :param width: 按钮宽度
        :param height: 按钮高度
        :param font_size: 字体大小
        :param icon_size: 图标大小
        """
        # 设置背景图片
        image_path = self.get_image_path('version_settings_background.png')
        icon_path = self.get_version_image_path('expand.png')

        # 创建按钮容器
        button = QLabel()
        button.setCursor(Qt.PointingHandCursor)
        button.setFixedSize(width, height)
        # button.mousePressEvent = lambda e: self.on_tab_clicked(text)
        button.setPixmap(QPixmap(image_path).scaled(width, height, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
        
        # 创建内容容器
        content_container = QWidget(button)
        content_container.setContentsMargins(0, 0, 0, 0)
        content_container.setStyleSheet('background-color: transparent;')  # rgba(110, 99, 255, 0.5)
        content_container.setGeometry(5, 5, width-10, height-13)
        
        # 创建图标布局
        layout = QHBoxLayout(content_container)
        layout.setContentsMargins(20, 0, 0, 0)
        layout.setSpacing(10)
        
        # 添加图标
        icon_label = QLabel(content_container)
        icon_label.setStyleSheet('background-color: transparent;')
        icon_pixmap = QPixmap(icon_path).scaled(icon_size, icon_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        icon_label.setPixmap(icon_pixmap)
        icon_label.setAlignment(Qt.AlignCenter)
        
        # 添加文本
        text_label = QLabel(text, content_container)
        text_label.setFont(QFont("Source Han Sans CN Normal", font_size, QFont.Weight.Bold))
        text_label.setStyleSheet("color: #f2f2f2; background-color: transparent;")
        text_label.setAlignment(Qt.AlignCenter)
        text_label.setContentsMargins(0, 0, 0, 0)
        
        # 根据图标位置添加部件
        layout.addStretch()
        layout.addWidget(text_label)
        layout.addWidget(icon_label)
        layout.addStretch()

        return button
    
    def create_control_button(self, name, bg_image):
        """创建控制按钮 - 使用 QLabel 和背景图片"""
        # 获取背景图片路径
        bg_path = self.get_image_path(bg_image)
        
        # 创建按钮
        control_btn = QLabel()
        control_btn.setFixedSize(30, 30)
        control_btn.setCursor(Qt.PointingHandCursor)
        
        # 设置背景图片
        pixmap = QPixmap(bg_path).scaled(30, 30, Qt.IgnoreAspectRatio, Qt.SmoothTransformation) 
        control_btn.setPixmap(pixmap)
        return control_btn
    
    def set_active_tab(self, name):
        """设置活动标签页"""
        index = [*self.tab_names, *self.tab_version_names].index(name)
        self.active_tab = index
        
        # 获取图片路径
        active_bg_path = self.get_image_path('menu.png')
        inactive_bg_path = self.get_image_path('no-menu.png')
        active_icon_path = self.get_image_path('ic.png')
        inactive_icon_path = self.get_image_path('no-ic.png')
        
        # 版本按钮背景
        inactive_bg2_path = self.get_image_path('version_Settings_background.png')
        active_icon2_path = self.get_image_path('ic.png')
        inactive_icon2_path = self.get_image_path('no-ic.png')
        
        for i, ((tab_button, tab_bg, icon_label), n) in enumerate(zip(self.tab_buttons, [*self.tab_names, *self.tab_version_names])):
            
            if n in self.tab_version_names:
                """版本实例"""
                active_bg = inactive_bg2_path
                active_icon = active_icon2_path

                if i != index:
                    active_icon = inactive_icon2_path
                    tab_bg.setStyleSheet('background-color: transparent;')
                else:
                    tab_bg.setStyleSheet('background-color: rgba(110, 99, 255, 0.5);')
                
                tab_button.setPixmap(QPixmap(active_bg).scaled(110, 32, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
                icon_label.setPixmap(QPixmap(active_icon).scaled(18, 18, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
            else:
                active_bg = active_bg_path
                active_icon = active_icon_path

                if i != index:
                    active_bg = inactive_bg_path
                    active_icon = inactive_icon_path

                tab_button.setPixmap(QPixmap(active_bg).scaled(128, 40, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
                icon_label.setPixmap(QPixmap(active_icon).scaled(20, 20, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))

    def on_tab_clicked(self, name):
        """标签点击事件处理"""
        self.set_active_tab(name)
        self.tab_switch_clicked.emit(name)
    
    def toggle_menu(self, n=0):
        """左侧菜单折叠"""
        if self.is_animating:
            return
        
        self.is_animating = True
        self.icon_toggle.setEnabled(False)
        
        self.menu_collapsed = not self.menu_collapsed
        if self.menu_collapsed:
            self.main_layout.setContentsMargins(10, 0, 11, 0)
            self.icon_toggle.setStyleSheet('background-color: rgba(128, 0, 77, 0.6);')  # rgba(169, 137, 77, 1)
        else:
            self.main_layout.setContentsMargins(215, 0, 11, 0)
            self.icon_toggle.setStyleSheet('background-color: rgba(0, 137, 77, 0.6);')  # rgba(169, 137, 77, 1)
            
        self.menu_toggle_signal.emit(self.menu_collapsed)
        # 延迟后重新启用交互
        from PySide6.QtCore import QTimer
        QTimer.singleShot(100, self.enable_interaction)

    def enable_interaction(self):
        self.is_animating = False
        self.icon_toggle.setEnabled(True)
        
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
