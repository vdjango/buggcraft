# 单机页面

# src/buggcraft/ui/pages/singleplayer_page.py
from PySide6.QtWidgets import QWidget, QVBoxLayout
from PySide6.QtCore import Qt, Signal
from ..widgets.buttons import QMStartButton
from .base_page import BasePage
from utils.helpers import get_physical_resolution
from core.launcher import MinecraftLibLauncher

import logging
logger = logging.getLogger(__name__)


class SinglePlayerPage(BasePage):
    """单机游戏页面"""
    started_changed = Signal()  # 设置改变信号，参数为设置键和值

    def __init__(self, parent=None, config_path=None, resource_path=None, scale_ratio=1.0):
        super().__init__(parent, config_path, resource_path, scale_ratio)
        # self.minecraft_directory = self.parent.minecraft_directory

        # 创建并启动游戏线程
        self.launcher = MinecraftLibLauncher(config_path=self.parent.config_path)
        self.launcher.signals.started.connect(self.minecraft_handle_started)
        self.launcher.signals.stopped.connect(self.minecraft_handle_stopped)
        self.launcher.signals.error.connect(self.minecraft_handle_error)
        self.current_client = False  # 游戏是否启动

        self.launch_btn = None
        self.init_ui()
        
    def init_ui(self):
        """初始化UI"""
        # 背景由主窗口统一处理，页面设置为透明
        self.setStyleSheet("background: transparent;")
        self.setContentsMargins(0, 20, 0, 0)
        
        # 创建主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        # 创建一个垂直布局容器，用于放置内容
        content_container = QWidget()
        content_layout = QVBoxLayout(content_container)
        content_layout.setContentsMargins(20, 20, 20, 20)
        
        # 添加一个弹簧将内容推到底部
        content_layout.addStretch(1)
        
        # 创建启动按钮
        self.launch_btn = QMStartButton(resource_path=self.resource_path)
        version_text = f"{self.launcher.version}" if self.launcher.version else "未找到对应游戏"
        self.launch_btn.set_texts('启动游戏', version_text)
        self.launch_btn.clicked.connect(self.started_changed.emit)
        
        # 添加半透明遮罩层，使文字更易读
        overlay = QWidget()
        overlay_layout = QVBoxLayout(overlay)
        overlay_layout.setContentsMargins(20, 20, 20, 20)
        
        content_layout.addWidget(overlay)
        
        # 将内容容器添加到主布局
        main_layout.addWidget(content_container)
    
    def started_game(self):
        """启动游戏"""
        if not self.parent.user.minecraft_username:
            self.launch_btn.set_texts(f"请先设置角色", self.launcher.version)
            # self.parent.user_panel.login_status.setText("<font color='#F44800'>请先设置游戏角色</font>")
            return
        
        if not self.current_client:
            # 游戏未启动 - 启动过程
            self.launch_btn.setEnabled(False)
            self.launch_btn.set_texts(f"启动中...", self.launcher.version)
            self.launcher.set_language('简体中文')
            size = self.parent.settings_manager.get_setting("launcher.window_size", "默认")

            # ["默认", "与启动器一致", "最大化"]
            fullscreen = False
            w, h = None, None
            if size == '默认':
                w, h = 854, 480
            elif size == '与启动器一致':
                # 转换为物理分辨率
                physical_width, physical_height = get_physical_resolution(self.width(), self.height())
                w, h = str(int(physical_width)), str(int(physical_height - 48 * self.scale_ratio))
            elif size == '最大化':
                fullscreen=True

            self.launcher.set_options(
                uuid=self.parent.user.minecraft_uuid,
                username=self.parent.user.minecraft_username,
                token=self.parent.user.minecraft_token,
                server=None,
                version=self.launcher.version,
                # minecraft_directory=self.minecraft_directory,
                memory=1024,
                width=w,
                height=h,
                fullscreen=fullscreen
            )

            # 启动线程
            self.launcher.start()
        else:
            # 游戏已启动 - 停止过程
            from PySide6.QtWidgets import QApplication
            self.launch_btn.set_texts(f"正在停止游戏...", self.launcher.version)
            QApplication.processEvents()
            self.launcher.stop()

    def set_minecraft_version(self, version):
        """设置Minecraft版本"""
        self.launcher.version = version
        if self.launch_btn:
            version_text = f"{version}" if version else "未找到对应游戏"
            self.launch_btn.set_texts('启动游戏', version_text)
    
    def minecraft_handle_started(self):
        """游戏启动处理"""
        from PySide6.QtCore import QTimer

        def handle_status():
            self.launch_btn.set_texts(f"停止游戏", self.launcher.version)
            self.launch_btn.set_start_style()
            self.launch_btn.setEnabled(True)
            self.current_client = True  # 游戏启动状态：已启动

        logger.info('minecraft_handle_started 游戏已启动')
        QTimer.singleShot(1000, lambda: handle_status())
    
    def minecraft_handle_stopped(self, exit_code):
        """游戏停止处理"""
        from PySide6.QtCore import QTimer

        def handle_status(code):
            self.launch_btn.set_texts("启动游戏", self.launcher.version)
            self.launch_btn.set_start_style()
            self.launch_btn.setEnabled(True)
            self.current_client = False  # 游戏启动状态：未启动

        logger.info(f"minecraft_handle_stopped 游戏已退出，代码: {exit_code}")
        QTimer.singleShot(1000, lambda: handle_status(exit_code))

    
    def minecraft_handle_error(self, message):
        """错误处理"""
        logger.info(f'minecraft_handle_error {message}')
        self.minecraft_handle_stopped(1)
