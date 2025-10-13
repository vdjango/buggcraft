import os
from PySide6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout, QScrollArea, QFrame, QApplication
)
from PySide6.QtCore import Qt, Signal, QPropertyAnimation, QEasingCurve, QRect, QPoint
from PySide6.QtGui import QFont, QPixmap, QMouseEvent, QPalette, QColor, QPainter, QBrush


class DiamondWidget(QWidget):
    """绘制菱形图案的自定义组件"""
    def __init__(self):
        super().__init__()
        self.setFixedSize(10, 10)  # 设置固定大小为10x10像素
    
    def paintEvent(self, event):
        """绘制菱形图案"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 设置画刷为#8CA7FF颜色
        painter.setBrush(QBrush(QColor("#8CA7FF")))
        painter.setPen(Qt.NoPen)
        
        # 绘制菱形（正方形旋转45度）
        # 在10x10的容器中居中绘制
        center_x, center_y = 5, 5
        size = 3  # 半径为3，形成更大的菱形
        
        # 菱形的四个顶点
        points = [
            QPoint(center_x, center_y - size),  # 上
            QPoint(center_x + size, center_y),  # 右
            QPoint(center_x, center_y + size),  # 下
            QPoint(center_x - size, center_y)   # 左
        ]
        
        painter.drawPolygon(points)


class VersionItem(QWidget):
    """版本项组件 - 按组显示（版本号+描述为一组）"""
    clicked = Signal(str)  # 发送版本号信号
    
    def __init__(self, version_id, description_lines, resource_path, icon_path=None, parent=None):
        """
        初始化版本项目
        :param version_id: 版本号
        :param description_lines: 描述文字列表 
        :param resource_path: 资源路径
        :param icon_path: 右侧图标路径
        :param parent: 父组件
        """
        super().__init__(parent)
        self.version_id = version_id
        self.description_lines = description_lines
        self.resource_path = resource_path
        self.icon_path = icon_path
        self.is_hovered = False
        self.is_selected = False
        self.init_ui()
        
    def init_ui(self):
        """初始化UI"""
        self.setFixedHeight(59)  # 设置固定高度 
        
        # 主布局
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(5, 6, 10, 6)  # 左边距5px，右边距10px
        main_layout.setSpacing(8)
        
        # 左侧菱形图案
        diamond_widget = DiamondWidget()
        main_layout.addWidget(diamond_widget)
        
        # 中间文字区域
        text_widget = QWidget()
        text_layout = QVBoxLayout(text_widget)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)  # 减少垂直间距
        
        # 添加上方弹性空间
        text_layout.addStretch()
        
        # 版本号标签（第一行）
        version_label = QLabel(f"版本号：{self.version_id}")
        version_label.setStyleSheet("""
            QLabel {
                color: white;
                font-size: 8px;
                font-weight: bold;
                background: transparent;
                border: none;
                padding: 0px;
                margin: 0px;
            }
        """)
        version_label.setAlignment(Qt.AlignLeft)
        text_layout.addWidget(version_label)
        
        # 描述行（第二行和第三行）
        # 显示两行描述，如果不足则用空行补充
        desc_lines = self.description_lines[:2] if len(self.description_lines) >= 2 else self.description_lines + [""] * (2 - len(self.description_lines))
        
        for line in desc_lines:
            desc_label = QLabel(line if line.strip() else "")
            desc_label.setStyleSheet("""
                QLabel {
                    color: white;
                    font-size: 7px;
                    background: transparent;
                    border: none;
                    padding: 0px;
                    margin: 0px;
                }
            """)
            desc_label.setAlignment(Qt.AlignLeft)
            text_layout.addWidget(desc_label)
        
        # 添加下方弹性空间使文字垂直居中
        text_layout.addStretch()
        
        # 将文字区域添加到主布局，并设置为可扩展
        main_layout.addWidget(text_widget, 1)  # stretch factor = 1，占据剩余空间
        
        # 右侧设置图标
        icon_label = QLabel()
        version_selection_path = os.path.join(self.resource_path, 'settings', 'VersionSelection.png')
        if os.path.exists(version_selection_path):
            pixmap = QPixmap(version_selection_path)
            scaled_pixmap = pixmap.scaled(16, 16, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            icon_label.setPixmap(scaled_pixmap)
        icon_label.setAlignment(Qt.AlignCenter | Qt.AlignVCenter)
        icon_label.setStyleSheet("""
            QLabel {
                background: transparent;
                border: none;
            }
        """)
        main_layout.addWidget(icon_label)
        
        # 设置样式
        self.setStyleSheet("""
            QWidget {
                background-color: transparent;
                border: none;
                border-radius: 4px;
            }
        """)
        
        # 设置鼠标悬浮效果
        self.setCursor(Qt.PointingHandCursor)
        
    def enterEvent(self, event):
        """鼠标进入事件 - 整个组悬浮效果"""
        self.is_hovered = True
        # 悬浮时显示背景颜色 
        self.setStyleSheet("""
            QWidget {
                background-color: #3D3A53 !important;
                border: none;
                border-radius: 4px;
            }
        """)
        # 同时使用QPalette设置背景色
        palette = self.palette()
        palette.setColor(QPalette.Window, QColor("#3D3A53"))
        self.setPalette(palette)
        self.setAutoFillBackground(True)
        super().enterEvent(event)
    
    def leaveEvent(self, event):
        """鼠标离开事件"""
        self.is_hovered = False
        # 离开时根据选中状态决定背景颜色
        palette = self.palette()
        if self.is_selected:
            # 如果已选中，保持选中背景颜色
            self.setStyleSheet("""
                QWidget {
                    background-color: #3D3A53 !important;
                    border: none;
                    border-radius: 4px;
                }
            """)
            palette.setColor(QPalette.Window, QColor("#3D3A53"))
            self.setPalette(palette)
            self.setAutoFillBackground(True)
        else:
            # 如果未选中，恢复透明背景
            self.setStyleSheet("""
                QWidget {
                    background-color: transparent !important;
                    border: none;
                    border-radius: 4px;
                }
            """)
            palette.setColor(QPalette.Window, QColor("transparent"))
            self.setPalette(palette)
            self.setAutoFillBackground(False)
        super().leaveEvent(event)
        
    def mousePressEvent(self, event: QMouseEvent):
        """处理鼠标点击事件"""
        if event.button() == Qt.LeftButton:
            # 设置选中状态和背景颜色
            self.is_selected = True
            self.setStyleSheet("""
                QWidget {
                    background-color: #3D3A53 !important;
                    border: none;
                    border-radius: 4px;
                }
            """)
            # 同时使用QPalette设置背景色
            palette = self.palette()
            palette.setColor(QPalette.Window, QColor("#3D3A53"))
            self.setPalette(palette)
            self.setAutoFillBackground(True)
            self.clicked.emit(self.version_id)
        super().mousePressEvent(event)


class VersionPopup(QWidget):
    """版本选择弹出框组件"""
    version_selected = Signal(str)  # 版本选择信号
    popup_closed = Signal()  # 弹出框关闭信号
    
    def __init__(self, trigger_widget, resource_path, parent=None):
        """
        初始化版本弹出框
        :param trigger_widget: 触发弹出框的组件
        :param resource_path: 资源路径
        :param parent: 父组件
        """
        super().__init__(parent)
        self.trigger_widget = trigger_widget
        self.resource_path = resource_path
        self.version_items = []
        self.is_visible = False
        
         
        self.init_ui()
        self.setup_animation()
        
    def init_ui(self):
        """初始化UI"""
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        # 获取触发组件的宽度
        trigger_width = self.trigger_widget.width()
        self.setFixedWidth(trigger_width)
        
        # 主容器 - 正方形矩形 
        main_frame = QFrame(self)
        main_frame.setStyleSheet("""
            QFrame {
                background-color: #1D1C28;
                border: 1px solid #7455FF;
                border-radius: 0px;
            }
        """)
        
        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(main_frame)
        
        # 内容布局
        content_layout = QVBoxLayout(main_frame)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        
        # 滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setStyleSheet("""
            QScrollArea {
                background-color: transparent;
                border: none;
                border-radius: 0px;
            }
            QScrollBar:vertical {
                background-color: #2A2A3A;
                width: 8px;
                border-radius: 0px;
            }
            QScrollBar::handle:vertical {
                background-color: #7455FF;
                border-radius: 0px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #8A6AFF;
            }
        """)
        
        # 版本列表容器
        self.versions_container = QWidget()
        self.versions_container.setStyleSheet("background-color: transparent;")
        self.versions_layout = QVBoxLayout(self.versions_container)
        self.versions_layout.setContentsMargins(0, 0, 0, 0)
        self.versions_layout.setSpacing(0)  # 版本项之间无间距
        
        scroll_area.setWidget(self.versions_container)
        content_layout.addWidget(scroll_area)
        
        # 初始隐藏
        self.hide()
        
    def setup_animation(self):
        """设置动画效果"""
        self.animation = QPropertyAnimation(self, b"geometry")
        self.animation.setDuration(200)
        self.animation.setEasingCurve(QEasingCurve.OutCubic)
        
    def add_version_item(self, version_id, description_lines, icon_path=None):
        """
        添加版本项目
        :param version_id: 版本号
        :param description_lines: 描述文字列表
        :param icon_path: 图标路径
        """
        version_item = VersionItem(version_id, description_lines, self.resource_path, icon_path)
        version_item.clicked.connect(self.on_version_selected)
        self.version_items.append(version_item)
        self.versions_layout.addWidget(version_item)
        
        # 更新弹出框高度
        self.update_popup_height()
        
    def update_popup_height(self):
        """更新弹出框高度"""
        item_count = len(self.version_items)
        if item_count == 0:
            return
            
        total_height = 256 + 2  
        self.setFixedHeight(total_height)
        
    def show_popup(self):
        """显示弹出框"""
        if self.is_visible or not self.version_items:
            return
            
        # 计算位置
        trigger_pos = self.trigger_widget.mapToGlobal(self.trigger_widget.rect().bottomLeft())
        popup_x = trigger_pos.x()
        popup_y = trigger_pos.y() + 2  # 小间距
        
        # 设置初始位置和大小
        start_rect = QRect(popup_x, popup_y, self.width(), 0)
        end_rect = QRect(popup_x, popup_y, self.width(), self.height())
        
        # 设置动画
        self.animation.setStartValue(start_rect)
        self.animation.setEndValue(end_rect)
        
        # 显示并开始动画
        self.setGeometry(start_rect)
        self.show()
        self.animation.start()
        self.is_visible = True
                
    def hide_popup(self):
        """隐藏弹出框"""
        if not self.is_visible:
            return
                        
        # 获取当前位置
        current_rect = self.geometry()
        end_rect = QRect(current_rect.x(), current_rect.y(), current_rect.width(), 0)
        
        # 设置动画
        self.animation.setStartValue(current_rect)
        self.animation.setEndValue(end_rect)
        
        # 动画完成后隐藏并更新状态
        self.animation.finished.connect(self.on_hide_animation_finished)
        self.animation.start()
        
    def on_hide_animation_finished(self):
        """隐藏动画完成后的处理"""
        self.hide()
        self.is_visible = False
        # 断开信号连接，避免重复连接
        self.animation.finished.disconnect()
    
    def toggle_popup(self):
        """切换弹出框显示状态"""
        if self.is_visible:
            self.hide_popup()
        else:
            self.show_popup()
            
    def on_version_selected(self, version_id):
        """处理版本选择事件"""
        # 清除所有版本项的选中状态
        for item in self.version_items:
            if item.version_id != version_id:
                item.is_selected = False
                # 恢复未选中项的透明背景
                item.setStyleSheet("""
                    QWidget {
                        background-color: transparent !important;
                        border: none;
                        border-radius: 4px;
                    }
                """)
        
        self.version_selected.emit(version_id)
        self.hide_popup()
        
    def clear_versions(self):
        """清空所有版本项目"""
        for item in self.version_items:
            item.deleteLater()
        self.version_items.clear()
                
    def keyPressEvent(self, event):
        """处理键盘事件"""
        if event.key() == Qt.Key_Escape:
            self.hide_popup()
            self.popup_closed.emit()
        super().keyPressEvent(event)
        
