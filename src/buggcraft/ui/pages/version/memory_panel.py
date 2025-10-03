import os
import psutil
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QRadioButton, 
    QPushButton, QGroupBox, QFileDialog, QScrollArea, QFormLayout, QSlider
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QFont, QPixmap, QColor, QPainter, QBrush, QLinearGradient
from ui.widgets.radio import QMRadioButton, QMRadioGroup
from ui.widgets.slider import StepSlider
from ui.widgets.progress import MemoryProgressBar
from config.settings import get_settings_manager
from core.memory import AdvancedMemoryRecommender


class MemorySettingsPanel(QWidget):
    """游戏内存设置面板"""
    
    memory = Signal(int)  # 滑块设置的内存
    auto_memory_changed = Signal(bool)  # 开启关闭自动分配内存
    
    def __init__(self, parent=None):
        """
        游戏内存设置面板
        """
        super().__init__(parent)
        self.resource_path = parent.resource_path
        self.background_color = "rgba(190, 183, 255, 0.3)"
        self.settings_manager = get_settings_manager()
        self.memory_recommender = AdvancedMemoryRecommender(self.settings_manager)
        self.is_disabled = True
        self.init_ui()
        self.load_default()
        
        # 初始化内存值
        self.update_memory_values()
        
        # 设置定时器定期更新内存信息
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_memory_values)
        self.timer.start(10000)  # 每秒更新一次

    def init_ui(self):
        """初始化 UI"""
        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 容器
        self.container = QWidget()
        self.container.setContentsMargins(0, 0, 0, 0)
        self.container.setStyleSheet(f"background-color: {self.background_color};")
        container_layout = QVBoxLayout(self.container)
        container_layout.setContentsMargins(15, 15, 15, 15)
        container_layout.setSpacing(0)

        # 自动分配内存选项
        self.auto_isolation = QMRadioButton(self, '自动分配内存', None)
        self.auto_isolation.selected.connect(self.on_auto_memory_changed)
        container_layout.addWidget(self.auto_isolation)

        # 内存分配容器
        self.memory_container = QWidget()
        self.memory_container.setContentsMargins(0, 0, 0, 0)
        self.memory_container.setStyleSheet("background-color: transparent;")
        memory_layout = QHBoxLayout(self.memory_container)
        memory_layout.setContentsMargins(10, 10, 10, 10)
        memory_layout.setSpacing(20)

        # 内存分配标签
        memory_label = QLabel("游戏内存分配")
        memory_label.setFont(QFont("Source Han Sans CN Normal", 10, QFont.Weight.Normal))
        memory_label.setAlignment(Qt.AlignVCenter)
        memory_label.setStyleSheet("color: rgba(255, 255, 255, 1);")
        memory_layout.addWidget(memory_label)

        # 内存滑块
        self.memory_slider = StepSlider(step=512, orientation=Qt.Horizontal)
        self.memory_slider.setMinimum(512)  # 最小512MB
        memory_layout.addWidget(self.memory_slider)

        # 自定义内存显示
        self.custom_memory_widget, self.custom_memory_label = self.create_custom_memory()
        memory_layout.addWidget(self.custom_memory_widget)
        container_layout.addWidget(self.memory_container)

        # 内存进度条
        self.memory_progress = MemoryProgressBar()
        self.memory_progress.setFixedHeight(12)
        progress_container = QWidget()
        progress_container.setContentsMargins(0, 0, 0, 0)
        progress_container.setStyleSheet("background-color: transparent;")
        progress_layout = QVBoxLayout(progress_container)
        progress_layout.setContentsMargins(10, 5, 10, 5)
        progress_layout.setSpacing(0)
        progress_layout.addWidget(self.memory_progress)
        container_layout.addWidget(progress_container)

        # 内存信息容器
        info_container = QWidget()
        info_container.setContentsMargins(0, 0, 0, 0)
        info_container.setStyleSheet("background-color: transparent;")
        info_layout = QHBoxLayout(info_container)
        info_layout.setContentsMargins(10, 0, 10, 0)
        info_layout.setSpacing(0)

        # 设备已使用内存
        used_label = QLabel("设备中已使用 ")
        used_label.setFont(QFont("Source Han Sans CN Normal", 9, QFont.Weight.Normal))
        used_label.setAlignment(Qt.AlignVCenter)
        used_label.setStyleSheet("color: rgba(255, 255, 255, 1);")
        info_layout.addWidget(used_label)
        
        self.used_value = QLabel("0 MB")
        self.used_value.setFont(QFont("Source Han Sans CN Normal", 9, QFont.Weight.Normal))
        self.used_value.setAlignment(Qt.AlignVCenter)
        self.used_value.setStyleSheet("color: rgba(255, 255, 255, 1);")
        info_layout.addWidget(self.used_value)

        # 分割线
        separator = QLabel(" | ")
        separator.setFont(QFont("Source Han Sans CN Normal", 9, QFont.Weight.Normal))
        separator.setAlignment(Qt.AlignVCenter)
        separator.setStyleSheet("color: rgba(255, 255, 255, 1);")
        info_layout.addWidget(separator)

        # 设备总内存
        total_label = QLabel("设备总内存 ")
        total_label.setFont(QFont("Source Han Sans CN Normal", 9, QFont.Weight.Normal))
        total_label.setAlignment(Qt.AlignVCenter)
        total_label.setStyleSheet("color: rgba(255, 255, 255, 1);")
        info_layout.addWidget(total_label)
        
        self.total_value = QLabel("0 MB")
        self.total_value.setFont(QFont("Source Han Sans CN Normal", 9, QFont.Weight.Normal))
        self.total_value.setAlignment(Qt.AlignVCenter)
        self.total_value.setStyleSheet("color: rgba(255, 255, 255, 1);")
        info_layout.addWidget(self.total_value)
        
        info_layout.addStretch()

        # 可用内存
        available_label = QLabel("可用内存 ")
        available_label.setFont(QFont("Source Han Sans CN Normal", 9, QFont.Weight.Normal))
        available_label.setAlignment(Qt.AlignVCenter)
        available_label.setStyleSheet("color: rgba(255, 255, 255, 1);")
        info_layout.addWidget(available_label)
        
        self.available_value = QLabel("0 MB")
        self.available_value.setFont(QFont("Source Han Sans CN Normal", 9, QFont.Weight.Normal))
        self.available_value.setAlignment(Qt.AlignVCenter)
        self.available_value.setStyleSheet("color: rgba(255, 255, 255, 1);")
        info_layout.addWidget(self.available_value)

        container_layout.addWidget(info_container)
        main_layout.addWidget(self.container, 1)
        
        # 连接信号
        self.memory_slider.valueChanged.connect(self.on_memory_slider_changed)
        
        # 设置初始值
        self.set_initial_values()

    def create_custom_memory(self):
        """创建自定义内存显示组件"""
        container = QWidget()
        container.setFixedHeight(27)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(20)

        # 内存值标签
        memory_label = QLabel('0')
        memory_label.setContentsMargins(20, 0, 20, 0)
        memory_label.setFixedHeight(27)
        memory_label.setFont(QFont("Source Han Sans CN Normal", 10, QFont.Weight.Normal))
        memory_label.setStyleSheet("color: rgba(255, 255, 255, 0.7); background-color: rgba(0, 0, 0, 0.3);")
        memory_label.setAlignment(Qt.AlignVCenter)
        layout.addWidget(memory_label)
        
        # 单位标签
        unit_label = QLabel('MB')
        unit_label.setFont(QFont("Source Han Sans CN Normal", 10, QFont.Weight.Normal))
        unit_label.setStyleSheet("color: rgba(255, 255, 255, 0.7); background-color: transparent;")
        unit_label.setAlignment(Qt.AlignVCenter)
        layout.addWidget(unit_label)
        
        return container, memory_label

    def set_initial_values(self):
        """设置初始值"""
        # 获取系统内存信息
        mem = psutil.virtual_memory()
        total_memory = mem.total // (1024 * 1024)  # 转换为MB
        used_memory = mem.used // (1024 * 1024)
        free_memory = mem.free // (1024 * 1024)
        available_memory = mem.available // (1024 * 1024)
        
        # 获取设置中的内存分配值/更新内存显示
        allocated_memory = self.settings_manager.get_version_setting("memory.allocation", 2048)
        self.update_memory_display(allocated_memory, used_memory, total_memory, available_memory)

        # 设置滑块范围/滑块值/更新进度条
        self.memory_slider.setMaximum(free_memory)
        self.memory_slider.setValue(allocated_memory)
        self.memory_progress.set_memory_values(
            total_memory=total_memory,
            used_memory=used_memory,
            allocated_memory=allocated_memory
        )

    def update_memory_values(self):
        """更新内存值"""
        # 获取系统内存信息
        mem = psutil.virtual_memory()
        total_memory = mem.total // (1024 * 1024)  # 转换为MB
        used_memory = mem.used // (1024 * 1024)
        available_memory = mem.available // (1024 * 1024)
        
        # 获取当前滑块值
        allocated_memory = self.memory_slider.value()
        
        # 更新内存显示/更新进度条
        self.update_memory_display(allocated_memory, used_memory, total_memory, available_memory)
        self.memory_progress.set_used_memory(used_memory)
        self.memory_progress.set_allocated_memory(allocated_memory)

    def update_memory_display(self, allocated, used, total, available):
        """更新内存显示"""
        self.custom_memory_label.setText(str(allocated))
        self.used_value.setText(f"{used/1024:.2f} GB")
        self.total_value.setText(f"{int(total/1024+0.5):.2f} GB")
        self.available_value.setText(f"{available/1024:.2f} GB")

    def on_memory_slider_changed(self, value):
        """处理内存滑块值改变"""
        self.memory.emit(value)
        
        # 更新进度条/保存设置
        self.memory_progress.set_allocated_memory(value)
        self.settings_manager.set_version_setting("memory.allocation", value)
        self.settings_manager.save_settings()
        
        # 更新内存显示
        self.update_memory_values()

    def on_auto_memory_changed(self, enabled):
        """开启关闭自动分配内存"""
        self.auto_memory_changed.emit(enabled)
        
        # 禁用或启用内存设置组件
        self.memory_container.setEnabled(not enabled)
        self.settings_manager.set_version_setting("minecraft.auto_allocate_memory", enabled)

        # 如果是自动分配，计算并设置内存值
        if enabled:
            # 计算推荐内存
            recommended_memory, _ = self.memory_recommender.calculate()
            self.memory_slider.setValue(recommended_memory)
            self.memory_progress.set_allocated_memory(recommended_memory)
            self.settings_manager.set_version_setting("memory.allocation", recommended_memory)
        
        self.settings_manager.save_settings()

    def set_disabled(self, disabled):
        if disabled:
            self.container.setStyleSheet(f"""
                QWidget {{
                    background-color: {self.background_color};
                }}
            """)
        else:
            self.container.setStyleSheet(f"""
                QWidget {{
                    background-color: rgba(148, 147, 158, 0.4);
                }}
            """)
        self.memory_slider.set_disabled(disabled)
        self.memory_progress.set_disabled(disabled)
        self.setDisabled(not disabled)
        self.update()
    
    def load_default(self):
        """从配置文件加载设置"""
        self.auto_isolation.set_selected(
            self.settings_manager.get_version_setting("minecraft.auto_allocate_memory", True)
        )
        self.set_initial_values()
