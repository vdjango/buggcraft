from PySide6.QtWidgets import (
    QLabel, QSizePolicy
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics, QFont


class SmartLabel(QLabel):
    """智能文本标签 - 自动截断长文本并显示工具提示"""
    
    def __init__(self, text="", font_size=10, font_weight=QFont.Weight.Normal, min_widht=50, max_heiht=300, parent=None):
        super().__init__(text, parent)
        self.full_text = text
        self.setFont(QFont("Source Han Sans CN Normal", font_size, font_weight))
        self.setWordWrap(False)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setMinimumWidth(min_widht)  # 最小宽度
        self.setMaximumWidth(max_heiht)  # 最大宽度
        self.update_text()
    
    def setText(self, text):
        """设置文本"""
        self.full_text = text
        self.update_text()
    
    def update_text(self):
        """更新显示文本"""
        # 调用父类设置文本
        super().setText(self.get_elided_text())
        
        # 设置工具提示
        if self.text_requires_tooltip():
            self.setToolTip(self.full_text)
        else:
            self.setToolTip("")
    
    def get_elided_text(self):
        """获取截断后的文本"""
        # 获取字体度量
        metrics = QFontMetrics(self.font())
        
        # 计算可用宽度
        available_width = self.width() - self.contentsMargins().left() - self.contentsMargins().right()
        
        # 如果文本宽度小于可用宽度，返回原文本
        if metrics.horizontalAdvance(self.full_text) <= available_width:
            return self.full_text
        
        # 截断文本并添加省略号
        return metrics.elidedText(self.full_text, Qt.ElideRight, available_width)
    
    def text_requires_tooltip(self):
        """检查文本是否需要工具提示"""
        # 获取字体度量
        metrics = QFontMetrics(self.font())
        
        # 计算文本宽度
        text_width = metrics.horizontalAdvance(self.full_text)
        
        # 计算可用宽度
        available_width = self.width() - self.contentsMargins().left() - self.contentsMargins().right()
        
        # 如果文本宽度大于可用宽度，需要工具提示
        return text_width > available_width
    
    def resizeEvent(self, event):
        """窗口大小变化时更新文本"""
        super().resizeEvent(event)
        self.update_text()

