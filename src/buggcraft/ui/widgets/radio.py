# 折叠面板
import os

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel
)
from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtGui import QFont, QPixmap


class QMRadioGroup(QObject):
    """管理一组 QMCheckBoxButton，实现单选行为"""
    
    button_selected = Signal(bool, tuple)  # 按钮被选中时发出信号，参数为按钮文本
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.buttons = []  # 存储所有管理的按钮
        self.selected_button = None  # 当前选中的按钮
    
    def add_button(self, button):
        """添加按钮到组中"""
        if button not in self.buttons:
            self.buttons.append(button)
            button.selected.connect(lambda checked, proprty, btn=button: self.on_button_selected(btn, checked, proprty))
    
    def remove_button(self, button):
        """从组中移除按钮"""
        if button in self.buttons:
            self.buttons.remove(button)
            button.selected.disconnect()
            
            # 如果移除的是当前选中的按钮，更新选中状态
            if button == self.selected_button:
                self.selected_button = None
    
    def on_button_selected(self, button, selected, proprty):
        """处理按钮选中事件"""
        if selected:
            # 取消其他按钮的选中状态
            for btn in self.buttons:
                if btn != button and btn.auto_radio_selected:
                    btn.set_selected(False)
            
            # 更新当前选中的按钮
            self.selected_button = button
            self.button_selected.emit(selected, proprty)
        else:
            # 如果取消选中当前按钮，更新状态
            if button == self.selected_button:
                self.selected_button = None
    
    def set_selected_button(self, button):
        """设置选中的按钮"""
        if button in self.buttons:
            button.set_selected(True)
    
    def get_selected_button(self):
        """获取当前选中的按钮"""
        return self.selected_button
    
    def get_selected_text(self):
        """获取当前选中的按钮文本"""
        return self.selected_button.text if self.selected_button else None
    
    def clear_selection(self):
        """清除所有选中状态"""
        for button in self.buttons:
            button.set_selected(False)
        self.selected_button = None


class QMRadioButton(QWidget):
    """"""
    selected = Signal(bool, tuple)  # 选中状态改变时发出信号

    def __init__(self, parent, text, messages=None, text_font_size=10, messages_font_size=9, slot_desc=None):
        super().__init__(parent)
        self.text = text
        self.messages = messages
        self.slot_desc = slot_desc
        self.text_font_size = text_font_size
        self.messages_font_size = messages_font_size
        self.resource_path = parent.resource_path
        self.auto_radio_selected = False  # 当前选项状态
        self.init_ui()
        self.setProperty('text', self.text)
        self.setProperty('messages', self.messages)

    def init_ui(self):
        """初始化 UI"""
        # 主布局
        self.setStyleSheet("background-color: transparent;")
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(15, 0, 15, 0)
        main_layout.setSpacing(10)
        
        # 图标容器
        icon_container = QWidget()
        icon_container.setFixedSize(30, 30)
        icon_layout = QVBoxLayout(icon_container)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        icon_layout.setAlignment(Qt.AlignCenter)
        
        # 创建图标标签
        self.auto_icon = QLabel()
        self.auto_icon.setFixedSize(20, 20)
        self.update_icon(self.auto_radio_selected)  # 初始状态
        icon_layout.addWidget(self.auto_icon)
        
        main_layout.addWidget(icon_container)
        
        # 自动选择选项 - 使用 QLabel
        self.auto_label = QLabel(self.text)
        self.auto_label.setFont(QFont("Source Han Sans CN", self.text_font_size))
        self.auto_label.setStyleSheet("color: #FFFFFF;")
        self.auto_label.setCursor(Qt.PointingHandCursor)  # 设置手型光标
        
        # 添加点击事件
        self.auto_label.mousePressEvent = lambda e: self.toggle_selection()
        
        main_layout.addWidget(self.auto_label)
        
        # 描述
        if self.slot_desc:
            main_layout.addWidget(self.slot_desc, 1)
        elif self.messages:
            desc_label = QLabel(self.messages)
            desc_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            desc_label.setFont(QFont("Source Han Sans CN", self.messages_font_size))
            desc_label.setStyleSheet("color: #888888;")
            main_layout.addWidget(desc_label, 1)
        
        main_layout.addStretch()

    def toggle_selection(self):
        """切换选中状态"""
        self.set_selected(not self.auto_radio_selected)
    
    def set_selected(self, selected):
        """设置选中状态"""
        if selected != self.auto_radio_selected:
            self.auto_radio_selected = selected
            self.update_icon(selected)
            self.selected.emit(selected, (self.text, self.messages))
    
    def update_icon(self, selected):
        """更新图标"""
        icon_name = "selected1.png" if selected else "not-selected1.png"
        icon_path = os.path.join(self.resource_path, 'images', 'version', icon_name)
        
        if os.path.exists(icon_path):
            pixmap = QPixmap(icon_path)
            if not pixmap.isNull():
                self.auto_icon.setPixmap(pixmap.scaled(20, 20, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            # 如果图标不存在，使用默认样式
            if selected:
                self.auto_icon.setStyleSheet("""
                    background-color: #7959FF;
                    border-radius: 10px;
                    border: 2px solid #FFFFFF;
                """)
            else:
                self.auto_icon.setStyleSheet("""
                    background-color: transparent;
                    border-radius: 10px;
                    border: 2px solid #888888;
                """)
    
    def is_selected(self):
        """返回当前是否选中"""
        return self.auto_radio_selected
    
    def set_text(self, text):
        """设置按钮文本"""
        self.text = text
        self.auto_label.setText(text)
    
    def set_messages(self, messages):
        """设置描述文本"""
        self.messages = messages

    def on_auto_clicked(self, selected):
        """处理自动选择标签点击事件"""
        if selected is not None:
            self.auto_radio_selected = selected
        else:
            if self.auto_radio_selected:
                self.auto_radio_selected = False
            else:
                self.auto_radio_selected = True
        
        self.selected.emit(self.auto_radio_selected, (self.text, self.messages))
        
        # 更新图标
        icon_name = "selected1.png" if self.auto_radio_selected else "not-selected1.png"
        icon_path = os.path.join(self.resource_path, 'images', 'version', icon_name)
        self.auto_icon.setPixmap(QPixmap(icon_path).scaled(20, 20, Qt.KeepAspectRatio, Qt.SmoothTransformation))

