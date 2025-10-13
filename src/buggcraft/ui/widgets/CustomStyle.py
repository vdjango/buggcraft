"""
自定义样式类用于解决QComboBox下拉框边框问题
"""
from PySide6.QtWidgets import QProxyStyle, QStyle
from PySide6.QtCore import QRect
from PySide6.QtGui import QPainter, QColor


class CustomComboBoxStyle(QProxyStyle):
    """
    """
    
    def __init__(self, base_style=None):
        """
        初始化自定义样式
        
        Args:
            base_style: 基础样式如果为None则使用默认样式
        """
        super().__init__(base_style)
    
    def drawComplexControl(self, control, option, painter, widget=None):
        """
        重写复杂控件绘制方法特别处理QComboBox
        
        Args:
            control: 控件类型
            option: 样式选项
            painter: 绘制器
            widget: 控件实例
        """
        if control == QStyle.ComplexControl.CC_ComboBox:
            # 对于QComboBox，我们需要特殊处理
            if widget and hasattr(widget, '__class__') and 'QMComboBox' in str(widget.__class__):
                # 这是我们的自定义ComboBox，应用特殊样式
                self._drawCustomComboBox(option, painter, widget)
                return
        
        # 对于其他控件，使用默认绘制
        super().drawComplexControl(control, option, painter, widget)
    
    def _drawCustomComboBox(self, option, painter, widget):
        """
        绘制自定义ComboBox移除边框
        
        Args:
            option: 样式选项
            painter: 绘制器
            widget: 控件实例
        """
        # 保存画笔状态
        painter.save()
        
        # 设置背景色
        background_color = QColor(86, 85, 100)  # #565564
        painter.fillRect(option.rect, background_color)
        
        # 绘制文本区域（不绘制边框）
        text_rect = self.subControlRect(QStyle.ComplexControl.CC_ComboBox, 
                                       option, 
                                       QStyle.SubControl.SC_ComboBoxEditField, 
                                       widget)
        
        # 绘制下拉箭头区域
        arrow_rect = self.subControlRect(QStyle.ComplexControl.CC_ComboBox, 
                                        option, 
                                        QStyle.SubControl.SC_ComboBoxArrow, 
                                        widget)
        
        # 恢复画笔状态
        painter.restore()
        
        # 调用基类方法绘制其他部分（文本、箭头等），但跳过边框
        # 我们只绘制文本和箭头，不绘制边框
        super().drawComplexControl(QStyle.ComplexControl.CC_ComboBox, option, painter, widget)
    
    def subControlRect(self, control, option, sub_control, widget=None):
        """
        重写子控件矩形计算调整ComboBox的子控件位置
        
        Args:
            control: 控件类型
            option: 样式选项
            sub_control: 子控件类型
            widget: 控件实例
            
        Returns:
            QRect: 子控件的矩形区域
        """
        if control == QStyle.ComplexControl.CC_ComboBox:
            if widget and hasattr(widget, '__class__') and 'QMComboBox' in str(widget.__class__):
                # 对于我们的自定义ComboBox，调整子控件位置以移除边框空间
                rect = super().subControlRect(control, option, sub_control, widget)
                
                if sub_control == QStyle.SubControl.SC_ComboBoxEditField:
                    # 文本区域，移除左边距
                    rect.setLeft(rect.left() + 2)
                    rect.setRight(rect.right() - 20)  # 为箭头留出空间
                elif sub_control == QStyle.SubControl.SC_ComboBoxArrow:
                    # 箭头区域，调整位置
                    rect.setLeft(rect.right() - 18)
                
                return rect
        
        return super().subControlRect(control, option, sub_control, widget)
    
    def pixelMetric(self, metric, option=None, widget=None):
        """
        重写像素度量调整ComboBox的边框宽度
        
        Args:
            metric: 度量类型
            option: 样式选项
            widget: 控件实例
            
        Returns:
            int: 像素值
        """
        if metric == QStyle.PixelMetric.PM_ComboBoxFrameWidth:
            if widget and hasattr(widget, '__class__') and 'QMComboBox' in str(widget.__class__):
                return 0
        
        return super().pixelMetric(metric, option, widget)