from PySide6.QtWidgets import QSlider, QStyle, QStyleOptionSlider
from PySide6.QtCore import Qt
from PySide6.QtGui import QMouseEvent


class StepSlider(QSlider):
    """强制步长移动的滑块（修复版本）"""
    
    def __init__(self, step=512, *args, **kwargs):
        """
        初始化滑块
        
        :param step: 步长值
        """
        super().__init__(*args, **kwargs)
        self.setCursor(Qt.PointingHandCursor)   
        self.setStyleSheet("""
            QSlider {
                background: transparent;
            }
            QSlider::groove:horizontal {
                height: 3px;
                background: rgba(94, 93, 104, 0.8);
            }
            QSlider::handle:horizontal {
                width: 11px;
                margin: -5px 0;
                border-radius: 6px;
                background: rgba(116, 146, 246, 0.8);
                border: 1px solid rgba(255, 255, 255, 0.9);
            }
            QSlider::sub-page:horizontal {
                border-radius: 2px;
                background: rgba(116, 146, 246, 0.7);
            }
        """)
        self.step = step
        self.setTickPosition(QSlider.TicksBelow)
        self.setTickInterval(512)  # 每512MB一个刻度
        self.setSingleStep(256)  # 步长256MB
        # self.setPageStep(1024)  # 页步长1GB
        self.setSingleStep(step)  # 设置单步步长
        self.setPageStep(step)    # 设置页步步长
    
    def mousePressEvent(self, event: QMouseEvent):
        """鼠标点击事件处理"""
        if event.button() == Qt.LeftButton:
            # 计算点击位置对应的值
            pos = event.position().toPoint()
            value = self._value_from_position(pos)
            
            # 调整到最近的步长倍数
            adjusted_value = self._adjust_to_step(value)
            
            # 设置滑块值
            self.setValue(adjusted_value)
            event.accept()
            return
        
        super().mousePressEvent(event)
    
    def mouseMoveEvent(self, event: QMouseEvent):
        """鼠标移动事件处理（拖动时）"""
        if event.buttons() & Qt.LeftButton:
            # 计算当前位置对应的值
            pos = event.position().toPoint()
            value = self._value_from_position(pos)
            
            # 调整到最近的步长倍数
            adjusted_value = self._adjust_to_step(value)
            
            # 设置滑块值
            self.setValue(adjusted_value)
            event.accept()
            return
        
        super().mouseMoveEvent(event)
    
    def _value_from_position(self, pos):
        """根据鼠标位置计算滑块值"""
        # 创建样式选项
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        
        # 获取滑块轨道几何信息
        groove_rect = self.style().subControlRect(
            QStyle.CC_Slider, 
            opt, 
            QStyle.SC_SliderGroove, 
            self
        )
        
        # 获取滑块手柄几何信息
        handle_rect = self.style().subControlRect(
            QStyle.CC_Slider, 
            opt, 
            QStyle.SC_SliderHandle, 
            self
        )
        
        # 计算值范围
        min_val = self.minimum()
        max_val = self.maximum()
        range_val = max_val - min_val
        
        # 计算位置对应的值
        if self.orientation() == Qt.Horizontal:
            # 计算有效宽度（减去手柄宽度）
            span = groove_rect.width() - handle_rect.width()
            if span <= 0:
                return min_val
                
            # 计算相对位置
            relative_pos = pos.x() - groove_rect.x() - handle_rect.width() / 2
            relative_pos = max(0, min(relative_pos, span))
            
            # 计算值
            value = min_val + (relative_pos / span) * range_val
        else:
            # 垂直滑块
            # 计算有效高度（减去手柄高度）
            span = groove_rect.height() - handle_rect.height()
            if span <= 0:
                return min_val
                
            # 计算相对位置
            relative_pos = pos.y() - groove_rect.y() - handle_rect.height() / 2
            relative_pos = max(0, min(relative_pos, span))
            
            # 计算值（垂直滑块通常是从上到下值减小）
            value = min_val + (1 - relative_pos / span) * range_val
        
        return value
    
    def _adjust_to_step(self, value):
        """将值调整到最近的步长倍数"""
        # 计算最近的步长倍数
        step = self.step
        min_val = self.minimum()
        max_val = self.maximum()
        
        # 计算步长倍数
        steps = round((value - min_val) / step)
        adjusted_value = min_val + steps * step
        
        # 确保在范围内
        return max(min_val, min(max_val, adjusted_value))

    def set_disabled(self, disabled):
        if disabled:
            self.setStyleSheet("""
                QSlider {
                    background: transparent;
                }
                QSlider::groove:horizontal {
                    height: 3px;
                    background: rgba(94, 93, 104, 0.8);
                }
                QSlider::handle:horizontal {
                    width: 11px;
                    margin: -5px 0;
                    border-radius: 6px;
                    background: rgba(116, 146, 246, 0.8);
                    border: 1px solid rgba(255, 255, 255, 0.9);
                }
                QSlider::sub-page:horizontal {
                    border-radius: 2px;
                    background: rgba(116, 146, 246, 0.7);
                }
            """)
        else:
            self.setStyleSheet("""
                QSlider {
                    background: transparent;
                }
                QSlider::groove:horizontal {
                    height: 3px;
                    background: rgba(94, 93, 104, 0.8);
                }
                QSlider::handle:horizontal {
                    width: 11px;
                    margin: -5px 0;
                    border-radius: 6px;
                    background: rgba(148, 147, 158, 0.5);
                    border: 1px solid rgba(255, 255, 255, 0.9);
                }
                QSlider::sub-page:horizontal {
                    border-radius: 2px;
                    background: rgba(148, 147, 158, 0.6);
                }
            """)
        self.setDisabled(not disabled)
        self.update()
