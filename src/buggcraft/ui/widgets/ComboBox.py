import os

from PySide6.QtWidgets import (
    QLabel, QComboBox
)
from PySide6.QtCore import Qt, QPoint, QEvent
from PySide6.QtGui import QPixmap, QColor, QPainter, QPolygon


import logging
logger = logging.getLogger(__name__)


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
        # 设置样式 - 根据高度动态调整
        style_sheet = """
            QComboBox {
                background-color: rgba(0, 0, 0, 0.3);
                color: rgba(255, 255, 255, 1);
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
                background-color: rgba(0, 0, 0, 0.2);
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
                background-color: rgba(0, 0, 0, 0.3);
                color: rgba(255, 255, 255, 1);
                border: 1px solid rgba(120, 89, 255, 0.5);
                selection-background-color: rgba(120, 89, 255, 0.9);
                selection-color: rgba(255, 255, 255, 1);
                outline: none;
                padding: 5px;
            }
            
            QComboBox QAbstractItemView::item {
                padding: 5px 10px;
                border-bottom: 1px solid rgba(60, 60, 70, 0.5);
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
                background-color: rgba(120, 89, 255, 0.3);
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
        
        # 更新图标
        self.update_icon()
        
        # 安装事件过滤器
        self.view().installEventFilter(self)
    
    def setHeight(self, height):
        """设置自定义高度"""
        self.custom_height = height
        
        # 重新应用样式
        style_sheet = """
            QComboBox {
                background-color: rgba(0, 0, 0, 0.3);
                color: rgba(255, 255, 255, 1);
                border-radius: 0px;
                padding: 5px;
                padding-left: 10px;
                padding-right: 30px;
                min-height: %dpx;
                height: %dpx;
            }
            
            QComboBox:hover {
                background-color: rgba(0, 0, 0, 0.2);
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
                background-color: rgba(0, 0, 0, 0.3);
                color: rgba(255, 255, 255, 1);
                border: 1px solid rgba(120, 89, 255, 0.5);
                selection-background-color: rgba(120, 89, 255, 0.9);
                selection-color: rgba(255, 255, 255, 1);
                outline: none;
                padding: 5px;
            }
            
            QComboBox QAbstractItemView::item {
                height: %dpx;
                padding: 5px 10px;
                border-bottom: 1px solid rgba(60, 60, 70, 0.5);
            }
            
            QComboBox QAbstractItemView::item:last {
                border-bottom: none;
            }
            
            QComboBox QAbstractItemView::item:hover {
                background-color: rgba(120, 89, 255, 0.3);
            }
        """ % (height, height, height, height)
        
        self.setStyleSheet(style_sheet)
        self.setFixedHeight(height)
        
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