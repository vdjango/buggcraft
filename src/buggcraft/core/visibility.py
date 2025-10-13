from PySide6.QtWidgets import QComboBox, QWidget, QVBoxLayout, QLabel
from PySide6.QtCore import Qt, Signal

class VisibilitySettings:
    """启动器可见性选项常量"""
    KEEP_VISIBLE = "游戏启动后保持不变"
    MINIMIZE = "游戏启动后最小化"
    HIDE = "游戏启动后隐藏，游戏退出后重新打开"
    CLOSE = "游戏启动后立即关闭"


class LauncherVisibilityManager:
    """启动器可见性管理器"""
    def __init__(self, main_window):
        self.main_window = main_window
        self.current_setting = VisibilitySettings.KEEP_VISIBLE
        self.previous_state = None  # 保存窗口之前的状态
    
    def apply_setting(self, setting):
        """应用可见性设置"""
        # 保存当前窗口状态
        self.previous_state = {
            "geometry": self.main_window.geometry(),
            "is_maximized": self.main_window.isMaximized(),
            "is_minimized": self.main_window.isMinimized()
        }
        
        self.current_setting = setting
        
        # 根据设置执行相应操作
        if setting == VisibilitySettings.MINIMIZE:
            self.main_window.showMinimized()
        elif setting == VisibilitySettings.HIDE:
            self.main_window.hide()
        elif setting == VisibilitySettings.CLOSE:
            self.main_window.close()
    
    def restore_if_needed(self):
        """游戏退出后恢复启动器（如果需要）"""
        if self.current_setting in [VisibilitySettings.MINIMIZE, VisibilitySettings.HIDE]:
            # 恢复窗口
            if self.current_setting == VisibilitySettings.HIDE:
                self.main_window.show()
            
            # 恢复之前的状态
            if self.previous_state:
                if self.previous_state["is_maximized"]:
                    self.main_window.showMaximized()
                elif self.previous_state["is_minimized"]:
                    self.main_window.showMinimized()
                else:
                    self.main_window.showNormal()
                    self.main_window.setGeometry(self.previous_state["geometry"])
            
            # 激活窗口并置于前台
            self.main_window.activateWindow()
            self.main_window.raise_()



class VisibilitySettingsWidget(QWidget):
    """启动器可见性设置UI组件"""
    setting_changed = Signal(str)  # 设置改变信号
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()
    
    def init_ui(self):
        """初始化UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # 标题
        title = QLabel("启动器可见性设置")
        title.setStyleSheet("font-weight: bold;")
        layout.addWidget(title)
        
        # 可见性选项下拉框
        self.visibility_combo = QComboBox()
        self.visibility_combo.addItems([
            VisibilitySettings.KEEP_VISIBLE,
            VisibilitySettings.MINIMIZE,
            VisibilitySettings.HIDE,
            VisibilitySettings.CLOSE
        ])
        self.visibility_combo.currentTextChanged.connect(self.on_setting_changed)
        
        # 设置下拉框样式
        self.visibility_combo.setStyleSheet("""
            QComboBox {
                background-color: #1A1923;
                color: #FFFFFF;
                border: 1px solid #555555;
                border-radius: 4px;
                padding: 2px 8px;
                font-size: 11px;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 4px solid #FFFFFF;
                margin-right: 5px;
            }
            QComboBox QAbstractItemView {
                background-color: #565564;
                color: #FFFFFF;
                border: 1px solid #555555;
                font-size: 11px;
            }
            QComboBox QListView {
                background-color: #565564;
                color: #FFFFFF;
                border: 1px solid #555555;
                font-size: 11px;
            }
            QComboBox QAbstractItemView::item {
                background-color: #565564;
            }
            QComboBox QListView::item {
                background-color: #565564;
                color: #FFFFFF;
            }
            QComboBox QAbstractItemView::item:hover {
                background-color: #7455FF !important;
                color: #FFFFFF !important;
            }
            QComboBox QListView::item:hover {
                background-color: #7455FF !important;
                color: #FFFFFF !important;
            }
            QComboBox QAbstractItemView::item:selected {
                background-color: #7455FF !important;
                color: #FFFFFF !important;
            }
            QComboBox QListView::item:selected {
                background-color: #7455FF !important;
                color: #FFFFFF !important;
            }
        """)
        
        layout.addWidget(self.visibility_combo)
    
    def on_setting_changed(self, text):
        """处理设置改变"""
        self.setting_changed.emit(text)
    
    def set_current_setting(self, setting):
        """设置当前选中的选项"""
        index = self.visibility_combo.findText(setting)
        if index >= 0:
            self.visibility_combo.setCurrentIndex(index)
