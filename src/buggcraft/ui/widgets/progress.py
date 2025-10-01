from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QPainter, QColor
from PySide6.QtCore import Qt, QRectF, QSize

class MemoryProgressBar(QWidget):
    """进度条，支持三种状态：总内存、系统已占用内存和用户设置的游戏内存"""
    
    def __init__(self, parent=None):
        """
        初始化进度条
        :param total_color: 总内存颜色 (支持 rgba 或 hex 格式)
        :param used_color: 系统已占用内存颜色 (支持 rgba 或 hex 格式)
        :param allocated_color: 用户设置的游戏内存颜色 (支持 rgba 或 hex 格式)
        """
        super().__init__(parent)
        self.total_memory = 0  # 总内存 (MB)
        self.used_memory = 0   # 系统已占用内存 (MB)
        self.allocated_memory = 0  # 用户设置的游戏内存 (MB)
        
        # 颜色设置
        self.total_color = self.parse_color("rgba(75, 82, 107, 1)")
        self.used_color = self.parse_color("rgba(103, 138, 255, 1)")
        self.allocated_color = self.parse_color("rgba(255, 200, 100, 1)")
        
        self.setMinimumHeight(8)  # 设置最小高度
    
    def parse_color(self, color_str):
        """解析颜色字符串为 QColor 对象"""
        # 处理 rgba 格式
        if color_str.startswith("rgba"):
            # 提取 rgba 值
            values = color_str[5:-1].split(',')
            if len(values) == 4:
                r = int(values[0].strip())
                g = int(values[1].strip())
                b = int(values[2].strip())
                a = float(values[3].strip()) * 255  # 转换为 0-255 范围
                return QColor(r, g, b, int(a))
        
        # 处理 hex 格式
        elif color_str.startswith("#"):
            # 处理 #RRGGBB 或 #RRGGBBAA 格式
            if len(color_str) == 7:  # #RRGGBB
                return QColor(color_str)
            elif len(color_str) == 9:  # #RRGGBBAA
                return QColor(color_str)
        
        # 默认颜色
        return QColor(75, 82, 107, 255)  # 默认总内存颜色
    
    def set_total_memory(self, total_memory):
        """设置总内存 (MB)"""
        if total_memory < 0:
            total_memory = 0
        self.total_memory = total_memory
        self.update()
    
    def set_used_memory(self, used_memory):
        """设置系统已占用内存 (MB)"""
        if used_memory < 0:
            used_memory = 0
        self.used_memory = used_memory
        self.update()
    
    def set_allocated_memory(self, allocated_memory):
        """设置用户分配的游戏内存 (MB)"""
        if allocated_memory < 0:
            allocated_memory = 0
        self.allocated_memory = allocated_memory
        self.update()
    
    def set_memory_values(self, total_memory, used_memory, allocated_memory):
        """同时设置所有内存值"""
        self.set_total_memory(total_memory)
        self.set_used_memory(used_memory)
        self.set_allocated_memory(allocated_memory)
    
    def set_colors(self, total_color, used_color, allocated_color):
        """设置所有颜色"""
        self.total_color = self.parse_color(total_color)
        self.used_color = self.parse_color(used_color)
        self.allocated_color = self.parse_color(allocated_color)
        self.update()
    
    def set_disabled(self, disabled):
        if disabled:
            self.total_color = self.parse_color("rgba(75, 82, 107, 1)")
            self.used_color = self.parse_color("rgba(103, 138, 255, 1)")
            self.allocated_color = self.parse_color("rgba(255, 200, 100, 1)")
        else:
            self.total_color = self.parse_color("rgba(75, 75, 75, 1)")
            self.used_color = self.parse_color("rgba(138, 138, 138, 1)")
            self.allocated_color = self.parse_color("rgba(170, 170, 170, 1)")

        self.setDisabled(not disabled)
        self.update()

    def paintEvent(self, event):
        """绘制进度条 - 显示三种状态"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 确保内存值有效
        if self.total_memory <= 0:
            # 绘制整个背景为总内存颜色
            painter.fillRect(self.rect(), self.total_color)
            return
        
        # 计算比例
        used_ratio = min(self.used_memory / self.total_memory, 1.0)
        allocated_ratio = min(self.allocated_memory / self.total_memory, 1.0 - used_ratio)
        
        # 计算宽度
        used_width = self.width() * used_ratio
        allocated_width = self.width() * allocated_ratio
        remaining_width = self.width() - used_width - allocated_width
        
        # 绘制系统已占用内存
        if used_width > 0:
            used_rect = QRectF(0, 0, used_width, self.height())
            painter.fillRect(used_rect, self.used_color)
        
        # 绘制用户分配的游戏内存
        if allocated_width > 0:
            allocated_rect = QRectF(used_width, 0, allocated_width, self.height())
            painter.fillRect(allocated_rect, self.allocated_color)
        
        # 绘制剩余内存
        if remaining_width > 0:
            remaining_rect = QRectF(used_width + allocated_width, 0, remaining_width, self.height())
            painter.fillRect(remaining_rect, self.total_color)
    
    def sizeHint(self):
        """返回建议大小"""
        return QSize(200, 8)
