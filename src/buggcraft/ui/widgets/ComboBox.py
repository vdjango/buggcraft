import os
import sys
from PySide6.QtWidgets import (
    QLabel, QComboBox, QStyledItemDelegate, QStyle
)
from PySide6.QtCore import Qt, QPoint, QEvent
from PySide6.QtGui import QPixmap, QColor, QPainter, QPolygon, QPalette

from .CustomStyle import CustomComboBoxStyle

import logging
logger = logging.getLogger(__name__)


class CustomComboBoxDelegate(QStyledItemDelegate):    
    def paint(self, painter, option, index):
        """重写绘制方法，设置悬浮背景颜色"""
        # 检查是否为悬浮状态
        if option.state & QStyle.State_MouseOver:
            painter.fillRect(option.rect, QColor("#7455FF"))
            painter.setPen(QColor("#FFFFFF"))
        elif option.state & QStyle.State_Selected:
            painter.fillRect(option.rect, QColor("#7455FF"))
            painter.setPen(QColor("#FFFFFF"))
        else:
            painter.fillRect(option.rect, QColor("#565564"))
            painter.setPen(QColor("#FFFFFF"))
        
        text = index.data()
        if text:
            painter.drawText(option.rect.adjusted(10, 0, -10, 0), Qt.AlignLeft | Qt.AlignVCenter, text)


class QMComboBox(QComboBox):
    """自定义下拉框"""
    
    def __init__(self, parent, height=None):
        super().__init__(parent)
        self.resource_path = parent.resource_path
        self.is_expanded = False
        self.expanded_icon = None
        self.collapsed_icon = None
        self.icon_label = None
        self.custom_height = height  # 存储自定义高度
        self.init_ui()
    
    def init_ui(self):
        """初始化 UI"""
        # 应用自定义样式来解决边框问题
        custom_style = CustomComboBoxStyle()
        self.setStyle(custom_style)
        
        # 设置样式 - 根据高度动态调整
        style_sheet = """
            QComboBox {
                background-color: #1A1923;
                color: rgba(255, 255, 255, 1);
                border: none;
                border-radius: 0px;
                padding: 5px;
                padding-left: 10px;
                padding-right: 30px;  /* 为图标留出空间 */
        """
        
        # 如果设置了自定义高度，添加到样式表中
        if self.custom_height:
            style_sheet += f"min-height: {self.custom_height}px; height: {self.custom_height}px;"
        else:
            style_sheet += "min-height: 30px;"
        
        style_sheet += """
            }
            
            QComboBox:hover {
                background-color: #1A1923;
            }
            
            QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: center right;
                width: 30px;  /* 增加宽度 */
                border-left: none;  /* 移除左边框 */
        """
        
        # 根据高度调整下拉按钮的高度
        if self.custom_height:
            style_sheet += f"height: {self.custom_height}px;"
        else:
            style_sheet += "height: 30px;"
        
        style_sheet += """
            }
            
            QComboBox::down-arrow {
                image: none;  /* 禁用默认箭头 */
            }
            
            QComboBox QAbstractItemView {
                background-color: #565564;
                color: rgba(255, 255, 255, 1);
                border: none;
                border-radius: 0px;
                outline: none;
                padding: 0px;
                margin: 0px;
                min-height: 100%;
                selection-background-color: #7455FF;
            }
            
            QComboBox QAbstractItemView::viewport {
                background-color: #565564;
                border: none;
                margin: 0px;
                padding: 0px;
            }
            
            QComboBox QAbstractItemView::item {
                padding: 8px 10px;
                border-bottom: 1px solid rgba(60, 60, 70, 0.5);
                background-color: transparent;
        """
        
        # 根据高度调整下拉项的高度
        if self.custom_height:
            style_sheet += f"height: {self.custom_height}px;"
        else:
            style_sheet += "height: 30px;"
        
        style_sheet += """
            }
            
            QComboBox QAbstractItemView::item:last {
                border-bottom: none;
            }
            
            QComboBox QAbstractItemView::item:hover {
                background-color: #7455FF !important;
                color: rgba(255, 255, 255, 1) !important;
            }
            
            QComboBox QAbstractItemView::item:selected {
                background-color: #7455FF !important;
                color: rgba(255, 255, 255, 1) !important;
            }
        """
        
        self.setStyleSheet(style_sheet)
        
        # 如果设置了自定义高度，应用它
        if self.custom_height:
            self.setFixedHeight(self.custom_height)
        
        # 加载图标
        self.load_icons()
        
        # 创建图标标签
        self.icon_label = QLabel(self)
        self.icon_label.setFixedSize(16, 16)
        self.icon_label.setStyleSheet("background-color: transparent;")
        
        # 设置手型光标
        self.setCursor(Qt.PointingHandCursor)
        self.icon_label.setCursor(Qt.PointingHandCursor)
        
        # 更新图标
        self.update_icon()
        
        # 解决QComboBoxPrivateContainer系统原生边框问题
        # 设置下拉框父容器的窗口属性
        view = self.view()
        parent_widget = view.parentWidget()
        if parent_widget:
            # 设置窗口标志，移除原生边框
            parent_widget.setWindowFlags(parent_widget.windowFlags() | Qt.FramelessWindowHint)
            # 设置背景色
            parent_palette = parent_widget.palette()
            parent_palette.setColor(parent_widget.backgroundRole(), QColor(86, 85, 100))  # #565564
            parent_widget.setPalette(parent_palette)
            parent_widget.setAutoFillBackground(True)
        
        # 安装事件过滤器
        view.installEventFilter(self)
        
        self.custom_delegate = CustomComboBoxDelegate()
        self.view().setItemDelegate(self.custom_delegate)
        
        # 直接设置视图属性来解决白边问题
        view = self.view()
        view.setContentsMargins(0, 0, 0, 0)
        view.setSpacing(0)
        if hasattr(view, 'setFrameStyle'):
            view.setFrameStyle(0)  # 移除边框
        if hasattr(view, 'setLineWidth'):
            view.setLineWidth(0)
        if hasattr(view, 'setMidLineWidth'):
            view.setMidLineWidth(0)
        
        # 设置视口属性
        viewport = view.viewport()
        if viewport:
            viewport.setContentsMargins(0, 0, 0, 0)
            viewport.setAutoFillBackground(True)
            # 设置背景色
            palette = viewport.palette()
            palette.setColor(viewport.backgroundRole(), QColor(86, 85, 100))  # #565564
            viewport.setPalette(palette)
    
    def setHeight(self, height):
        """设置自定义高度"""
        self.custom_height = height
        
        # 重新应用自定义样式来解决边框问题
        custom_style = CustomComboBoxStyle()
        self.setStyle(custom_style)
        
        # 重新应用样式
        style_sheet = """
            QComboBox {
                background-color: #1A1923;
                color: rgba(255, 255, 255, 1);
                border: none;
                border-radius: 0px;
                padding: 5px;
                padding-left: 10px;
                padding-right: 30px;
                min-height: %dpx;
                height: %dpx;
            }
            
            QComboBox:hover {
                background-color: #1A1923;
            }
            
            QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: center right;
                width: 30px;
                height: %dpx;
                border-left: none;
            }
            
            QComboBox::down-arrow {
                image: none;
            }
            
            QComboBox QAbstractItemView {
                background-color: #565564;
                color: rgba(255, 255, 255, 1);
                border: none;
                border-radius: 0px;
                outline: none;
                padding: 0px;
                margin: 0px;
                min-height: 100%;
                selection-background-color: #7455FF;
            }
            
            QComboBox QListView {
                background-color: #565564;
                color: rgba(255, 255, 255, 1);
                border: none;
                border-radius: 0px;
                outline: none;
                padding: 0px;
                margin: 0px;
                min-height: 100%;
                selection-background-color: #7455FF;
            }
            
            QComboBox QAbstractItemView::viewport {
                background-color: #565564;
                border: none;
                margin: 0px;
                padding: 0px;
            }
            
            QComboBox QListView::viewport {
                background-color: #565564;
                border: none;
                margin: 0px;
                padding: 0px;
            }
            
            QComboBox QAbstractItemView::item {
                height: %dpx;
                padding: 8px 10px;
                border-bottom: 1px solid rgba(60, 60, 70, 0.5);
                background-color: #565564;
            }
            
            QComboBox QListView::item {
                height: %dpx;
                padding: 8px 10px;
                border-bottom: 1px solid rgba(60, 60, 70, 0.5);
                background-color: #565564;
                color: rgba(255, 255, 255, 1);
            }
            
            QComboBox QAbstractItemView::item:last {
                border-bottom: none;
            }
            
            QComboBox QListView::item:last {
                border-bottom: none;
            }
            
            QComboBox QAbstractItemView::item:hover {
                background-color: #7455FF !important;
                color: rgba(255, 255, 255, 1) !important;
            }
            
            QComboBox QListView::item:hover {
                background-color: #7455FF !important;
                color: rgba(255, 255, 255, 1) !important;
            }
            
            QComboBox QAbstractItemView::item:selected {
                background-color: #7455FF !important;
                color: rgba(255, 255, 255, 1) !important;
            }
            
            QComboBox QListView::item:selected {
                background-color: #7455FF !important;
                color: rgba(255, 255, 255, 1) !important;
            }
        """ % (height, height, height, height)
        
        self.setStyleSheet(style_sheet)
        self.setFixedHeight(height)
        
        # 直接设置视图属性来解决白边问题
        view = self.view()
        view.setContentsMargins(0, 0, 0, 0)
        view.setSpacing(0)
        if hasattr(view, 'setFrameStyle'):
            view.setFrameStyle(0)  # 移除边框
        if hasattr(view, 'setLineWidth'):
            view.setLineWidth(0)
        if hasattr(view, 'setMidLineWidth'):
            view.setMidLineWidth(0)
        
        # 设置视口属性
        viewport = view.viewport()
        if viewport:
            viewport.setContentsMargins(0, 0, 0, 0)
            viewport.setAutoFillBackground(True)
            # 设置背景色
            palette = viewport.palette()
            palette.setColor(viewport.backgroundRole(), QColor(86, 85, 100))  # #565564
            viewport.setPalette(palette)
        
        # 设置下拉框父容器的窗口属性
        parent_widget = view.parentWidget()
        if parent_widget:
            # 设置窗口标志，移除原生边框
            parent_widget.setWindowFlags(parent_widget.windowFlags() | Qt.FramelessWindowHint)
            # 设置背景色
            parent_palette = parent_widget.palette()
            parent_palette.setColor(parent_widget.backgroundRole(), QColor(86, 85, 100))  # #565564
            parent_widget.setPalette(parent_palette)
            parent_widget.setAutoFillBackground(True)
        
        # 更新图标位置
        self.update_icon_position()
    
    def load_icons(self):
        """加载图标文件 - 带详细日志"""
        # 加载收起状态图标
        collapsed_path = os.path.join(self.resource_path, 'images', 'version', "fold-up.png")
        print(f"尝试加载收起状态图标: {collapsed_path}")
        
        if os.path.exists(collapsed_path):
            self.collapsed_icon = QPixmap(collapsed_path)
            if self.collapsed_icon.isNull():
                print(f"图标加载失败: {collapsed_path}")
                self.collapsed_icon = self.create_default_collapsed_icon()
            else:
                print(f"图标加载成功: {collapsed_path}")
                self.collapsed_icon = self.collapsed_icon.scaled(16, 16, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        else:
            print(f"图标文件不存在: {collapsed_path}")
            self.collapsed_icon = self.create_default_collapsed_icon()
        
        # 加载展开状态图标
        expanded_path = os.path.join(self.resource_path, 'images', 'version', "expand.png")
        print(f"尝试加载展开状态图标: {expanded_path}")
        
        if os.path.exists(expanded_path):
            self.expanded_icon = QPixmap(expanded_path)
            if self.expanded_icon.isNull():
                print(f"图标加载失败: {expanded_path}")
                self.expanded_icon = self.create_default_expanded_icon()
            else:
                print(f"图标加载成功: {expanded_path}")
                self.expanded_icon = self.expanded_icon.scaled(16, 16, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        else:
            print(f"图标文件不存在: {expanded_path}")
            self.expanded_icon = self.create_default_expanded_icon()
    
    def create_default_collapsed_icon(self):
        """创建默认收起状态图标"""
        pixmap = QPixmap(16, 16)
        pixmap.fill(Qt.transparent)
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 绘制向下箭头
        center_x = pixmap.width() // 2
        center_y = pixmap.height() // 2
        
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255))
        
        points = [
            QPoint(center_x - 4, center_y - 2),  # 左上点
            QPoint(center_x + 4, center_y - 2),   # 右上点
            QPoint(center_x, center_y + 4)        # 下顶点
        ]
        
        painter.drawPolygon(QPolygon(points))
        painter.end()
        
        return pixmap
    
    def create_default_expanded_icon(self):
        """创建默认展开状态图标"""
        pixmap = QPixmap(16, 16)
        pixmap.fill(Qt.transparent)
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 绘制向上箭头
        center_x = pixmap.width() // 2
        center_y = pixmap.height() // 2
        
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255))
        
        points = [
            QPoint(center_x, center_y - 4),  # 上顶点
            QPoint(center_x - 4, center_y + 2),  # 左下点
            QPoint(center_x + 4, center_y + 2)   # 右下点
        ]
        
        painter.drawPolygon(QPolygon(points))
        painter.end()
        
        return pixmap
    
    def eventFilter(self, obj, event):
        """事件过滤器 - 检测下拉列表的显示和隐藏"""
        if obj == self.view() and event.type() == QEvent.Show:
            self.is_expanded = True
            self.update_icon()
        elif obj == self.view() and event.type() == QEvent.Hide:
            self.is_expanded = False
            self.update_icon()
        return super().eventFilter(obj, event)
    
    def update_icon(self):
        """更新图标状态"""
        if self.is_expanded:
            # 展开状态图标
            if not self.expanded_icon.isNull():
                self.icon_label.setPixmap(self.expanded_icon)
            else:
                self.icon_label.setPixmap(self.create_default_expanded_icon())
        else:
            # 收起状态图标
            if not self.collapsed_icon.isNull():
                self.icon_label.setPixmap(self.collapsed_icon)
            else:
                self.icon_label.setPixmap(self.create_default_collapsed_icon())
    
    def resizeEvent(self, event):
        """调整大小事件 - 更新图标位置"""
        super().resizeEvent(event)
        self.update_icon_position()
    
    def update_icon_position(self):
        """更新图标位置"""
        padding = 10
        x = self.width() - self.icon_label.width() - padding
        y = (self.height() - self.icon_label.height()) // 2
        self.icon_label.move(x, y)