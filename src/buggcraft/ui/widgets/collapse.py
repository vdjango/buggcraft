# 折叠面板
import os

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QRadioButton, 
    QPushButton, QGroupBox, QFileDialog
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QPixmap
from ui.widgets.radio import QMRadioButton, QMRadioGroup


class JavaSettingsPanel(QWidget):
    """可折叠的 Java 设置面板"""
    
    java_path_changed = Signal(str)  # Java 路径改变信号
    
    def __init__(self, resource_path, parent=None):
        super().__init__(parent)
        self.resource_path = resource_path
        self.is_expanded = False  # 初始状态为折叠
        self.current_java_path = ""  # 当前 Java 路径
        self.available_versions = []  # 可用的 Java 版本
        self.init_ui()
        self.scan_java_versions()  # 扫描 Java 版本
        
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
        create_content = QWidget()
        create_content.setStyleSheet("color: #FFFFFF; background-color: transparent;")
        create_layout = QVBoxLayout(create_content)
        create_layout.setContentsMargins(0, 3, 0, 3)
        create_layout.setSpacing(0)
        layout.addWidget(create_content)
        title_label = QLabel("游戏Java")
        title_label.setFont(QFont("Source Han Sans CN Heavy", 10))
        title_label.setStyleSheet("color: #FFFFFF; background-color: transparent;")
        create_layout.addWidget(title_label)
        
        # 当前 Java 路径
        self.path_label = QLabel("未设置")
        self.path_label.setFont(QFont("Source Han Sans CN", 9))
        self.path_label.setStyleSheet("color: #AAAAAA; background-color: transparent;")
        self.path_label.setAlignment(Qt.AlignVCenter)  # Qt.AlignRight | 
        create_layout.addWidget(self.path_label, 1)
        
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
        desc_layout = QVBoxLayout(desc)

        desc_icon = QLabel()
        desc_icon.setFixedSize(25, 25)
        desc_icon.setAlignment(Qt.AlignCenter)  # 关键：设置居中对齐
        desc_icon.setPixmap(QPixmap(
            os.path.join(self.resource_path, 'images', 'version', 'folder.png')
        ).scaled(16, 16, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        # desc_folder = QLabel(desc_icon)
        # desc_folder.setFixedSize(24, 24)
        desc_icon.setStyleSheet('background-color: rgba(190, 183, 255, 0.19); border: 1px solid rgba(139, 133, 218, 1);')

        desc_layout.addWidget(desc_icon)

        custom_button = QMRadioButton(
            self,
            "自定义 Java 路径",
            "使用自定义 Java 安装路径",
            text_font_size=10,
            messages_font_size=9,
            slot_desc=desc_icon
        )
        layout.addWidget(custom_button)
        self.button_group.add_button(custom_button)

        # 设置默认选中
        auto_button.set_selected(True)

        # auto_group = QMRadioButton(self, '使用推荐的 Java 版本', '(系统将自动选择最适合的 Java 版本)')
        # auto_group.selected.connect(self.on_auto_clicked)
        # # 自动选择选项
        # self.auto_radio = QRadioButton("使用推荐的 Java 版本")
        # self.auto_radio.setFont(QFont("Source Han Sans CN", 10))
        # self.auto_radio.setStyleSheet("color: #FFFFFF;")
        # self.auto_radio.toggled.connect(self.on_auto_selected)

        # layout.addWidget(auto_group)
        
        # # 已安装版本选项
        # versions_group = self.create_versions_group()
        # layout.addWidget(versions_group)
        
        # # 自定义选项
        # custom_group = self.create_custom_group()
        # layout.addWidget(custom_group)
        
        return content

    
    def on_auto_clicked(self, proprty: tuple):
        """处理自动选择标签点击事件"""
        print(proprty)

    def set_version_selected(self, selected):
        """设置版本选项状态"""
        # 遍历所有版本选项，取消选中状态
        for i in range(self.versions_container.layout().count()):
            widget = self.versions_container.layout().itemAt(i).widget()
            if widget:
                # 找到版本标签
                version_label = widget.findChild(QLabel, "version_label")
                if version_label:
                    if selected:
                        version_label.setStyleSheet("color: #7959FF; font-weight: bold;")
                    else:
                        version_label.setStyleSheet("color: #FFFFFF; font-weight: normal;")
                
                # 找到版本图标
                version_icon = widget.findChild(QLabel, "version_icon")
                if version_icon:
                    self.update_version_icon(version_icon, selected)

    def set_custom_selected(self, selected):
        """设置自定义选项状态"""
        if selected:
            self.custom_label.setStyleSheet("color: #7959FF; font-weight: bold;")
        else:
            self.custom_label.setStyleSheet("color: #FFFFFF; font-weight: normal;")
        
        self.update_custom_icon(selected)



    def create_versions_group(self):
        """创建已安装版本组"""
        group = QGroupBox("已安装版本")
        group.setStyleSheet("""
            QGroupBox {
                color: #AAAAAA;
                font: bold 10px;
                border: 1px solid #3A3C4E;
                border-radius: 4px;
                margin-top: 10px;
                padding-top: 15px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 5px;
            }
        """)
        
        layout = QVBoxLayout(group)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)
        
        # 版本选项容器
        self.versions_container = QWidget()
        versions_layout = QVBoxLayout(self.versions_container)
        versions_layout.setContentsMargins(0, 0, 0, 0)
        versions_layout.setSpacing(8)
        
        # 添加版本选项
        self.add_java_versions()
        
        layout.addWidget(self.versions_container)
        
        return group
    
    def create_custom_group(self):
        """创建自定义选项组"""
        group = QGroupBox("自定义")
        group.setStyleSheet("""
            QGroupBox {
                color: #AAAAAA;
                font: bold 10px;
                border: 1px solid #3A3C4E;
                border-radius: 4px;
                margin-top: 10px;
                padding-top: 15px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 5px;
            }
        """)
        
        layout = QVBoxLayout(group)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)
        
        # 自定义选项
        self.custom_radio = QRadioButton("使用自定义 Java 路径")
        self.custom_radio.setFont(QFont("Source Han Sans CN", 9))
        self.custom_radio.setStyleSheet("color: #FFFFFF;")
        self.custom_radio.toggled.connect(self.on_custom_selected)
        layout.addWidget(self.custom_radio)
        
        # 路径选择和显示
        path_layout = QHBoxLayout()
        path_layout.setContentsMargins(20, 0, 0, 0)
        path_layout.setSpacing(10)
        
        self.custom_path_label = QLabel("未选择")
        self.custom_path_label.setFont(QFont("Source Han Sans CN", 8))
        self.custom_path_label.setStyleSheet("color: #888888;")
        self.custom_path_label.setMinimumWidth(200)
        path_layout.addWidget(self.custom_path_label, 1)
        
        browse_button = QPushButton("浏览...")
        browse_button.setFont(QFont("Source Han Sans CN", 8))
        browse_button.setFixedSize(80, 25)
        browse_button.setStyleSheet("""
            QPushButton {
                background-color: #3A3C4E;
                color: #FFFFFF;
                border: 1px solid #4A4C5E;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #4A4C5E;
            }
        """)
        browse_button.clicked.connect(self.browse_java_path)
        path_layout.addWidget(browse_button)
        
        layout.addLayout(path_layout)
        
        return group
    
    def toggle_expand(self, event):
        """切换展开/折叠状态"""
        self.is_expanded = not self.is_expanded
        self.content.setVisible(self.is_expanded)
        self.update_expand_icon()
        
    def update_expand_icon(self):
        """更新展开/折叠图标"""
        import os
        icon_name = "fold-up.png" if self.is_expanded else "expand.png"
        # 这里假设有图标资源，实际使用时替换为您的图标路径
        self.expand_icon.setPixmap(QPixmap(
            os.path.join(self.resource_path, 'images', 'version', icon_name)
        ).scaled(16, 16, Qt.KeepAspectRatio, Qt.SmoothTransformation))
    
    def scan_java_versions(self):
        """扫描系统上的 Java 版本"""
        # 这里简化处理，实际应用中需要实现扫描逻辑
        self.available_versions = [
            {"version": "21.0.7", "path": "C:\\Program Files\\Java\\jdk-21.0.7"},
            {"version": "17.0.10", "path": "C:\\Program Files\\Java\\jdk-17.0.10"},
            {"version": "11.0.22", "path": "C:\\Program Files\\Java\\jdk-11.0.22"},
            {"version": "8.0.402", "path": "C:\\Program Files\\Java\\jdk-8.0.402"}
        ]
        
        # 更新 UI
        # self.add_java_versions()
        
        # 设置默认选择
        if self.available_versions:
            self.set_java_path(self.available_versions[0]["path"])
    
    def add_java_versions(self):
        """添加 Java 版本选项"""
        # 清除现有选项
        layout = self.versions_container.layout()
        for i in reversed(range(layout.count())):
            widget = layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)
        
        # 添加新选项
        for java in self.available_versions:
            version_radio = QRadioButton(f"Java {java['version']}")
            version_radio.setFont(QFont("Source Han Sans CN", 9))
            version_radio.setStyleSheet("color: #FFFFFF;")
            version_radio.setProperty("java_path", java["path"])
            version_radio.toggled.connect(lambda checked, path=java["path"]: self.on_version_selected(checked, path))
            layout.addWidget(version_radio)
    
    def set_java_path(self, path):
        """设置 Java 路径"""
        self.current_java_path = path
        self.path_label.setText(path)
        self.java_path_changed.emit(path)
    
    def on_auto_selected(self, checked):
        """自动选择选项被选中"""
        if checked:
            # 实现自动选择逻辑
            # 这里简化处理，实际应用中需要实现自动选择算法
            if self.available_versions:
                self.set_java_path(self.available_versions[0]["path"])
    
    def on_version_selected(self, checked, path):
        """版本选项被选中"""
        if checked:
            self.set_java_path(path)
    
    def on_custom_selected(self, checked):
        """自定义选项被选中"""
        if checked:
            # 如果自定义路径已设置，使用它
            if self.custom_path_label.text() != "未选择":
                self.set_java_path(self.custom_path_label.text())
            else:
                # 否则打开文件选择对话框
                self.browse_java_path()
    
    def browse_java_path(self):
        """浏览 Java 路径"""
        # 打开文件选择对话框
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择 Java 可执行文件",
            "",
            "Java 可执行文件 (java java.exe javaw.exe)"
        )
        
        if path:
            self.custom_path_label.setText(path)
            self.custom_radio.setChecked(True)
            self.set_java_path(path)
