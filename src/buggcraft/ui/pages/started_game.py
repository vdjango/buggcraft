# StartGamePage 类
import os

from PySide6.QtWidgets import (
    QWidget, QLabel, QLineEdit, QVBoxLayout, QHBoxLayout, QFrame
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QFont, QPixmap, QColor, QPainter

from core.auth.microsoft import Authenticator, MinecraftSignals
from ui.widgets.buttons import QMStartButton
from ui.dialog.LoginDialog import LoginWaitDialog
from config.settings import get_settings_manager
from core.launcher import MinecraftLibLauncher
from utils.helpers import get_physical_resolution

import logging
logger = logging.getLogger(__name__)


class StartGamePage(QWidget):
    """用户面板 - 可折叠"""
    
    started_changed = Signal()  # 游戏开始信号
    login_success = Signal(dict, str)  # 用户名, 登录类型
    

    def __init__(self, parent, resource_path, cache_path):
        super().__init__(parent)
        self.parent = parent
        self.cache_path = cache_path
        self.resource_path = resource_path
        self.login_index = 0  # 第几次登录
        self.current_login_mode = "正版登录"  # 当前登录模式：正版登录/离线登录
        self.background_color = QColor(0, 0, 0, 0)  # 透明背景
        
        # 创建并启动游戏线程
        self.launcher = MinecraftLibLauncher(config_path=self.parent.config_path)
        self.launcher.signals.started.connect(self.minecraft_handle_started)
        self.launcher.signals.stopped.connect(self.minecraft_handle_stopped)
        self.launcher.signals.error.connect(self.minecraft_handle_error)
        self.current_client = False  # 游戏是否启动

        self.signals = MinecraftSignals()
        self.login_dialog = LoginWaitDialog(self.resource_path, self.cache_path)
        self.login_dialog.cancel_signal.connect(lambda: self.handle_auth_failure('取消登录'))

        # 初始化设置管理器
        self.settings_manager = get_settings_manager()

        # 创建认证管理器
        self.auth_manager = Authenticator()
        
        # 连接认证信号
        self.auth.signals.success.connect(self.handle_auth_success)
        self.auth.signals.failure.connect(self.handle_auth_failure)
        self.auth.signals.progress.connect(self.handle_auth_progress)

        self.auth_manager.signals.success.connect(self.handle_auth_success)
        self.auth_manager.signals.failure.connect(self.handle_auth_failure)
        self.auth_manager.signals.progress.connect(self.handle_auth_progress)
        
        # 初始化UI
        self.init_ui()
        self.auth_manager.load(self.cache_path)

    def started_game(self):
        """启动游戏"""
        print('self.auth_manager.is_authenticated()', self.auth_manager.is_authenticated(), self.auth_manager.current.username)
        if not self.auth_manager.is_authenticated():
            self.launch_btn.set_texts(f"请先设置角色", self.launcher.version)
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
                w, h = str(int(physical_width)), str(int(physical_height))
            elif size == '最大化':
                fullscreen=True

            self.launcher.set_options(
                uuid=self.auth_manager.current.uuid,
                username=self.auth_manager.current.username,
                token=self.auth_manager.current.token,
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

    @property
    def auth(self):
        return self.login_dialog.auth
    
    def init_ui(self):
        """初始化用户界面"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 创建选项卡容器
        self.tab_container = QWidget()
        tab_container_layout = QHBoxLayout(self.tab_container)
        tab_container_layout.setContentsMargins(15, 0, 15, 0)
        
        # 创建选项卡按钮区域
        self.tab_buttons_widget = self.create_tab_buttons()
        # self.tab_buttons_widget.setStyleSheet("background-color: #225500;")
        
        # 创建选项卡内容区域
        self.tab_content = QWidget()
        self.tab_content.setFixedWidth(926 - 178 - 62)
        self.tab_content.setContentsMargins(25, 0, 25, 0)
        # self.tab_content.setStyleSheet("background-color: #552299;")

        tab_content_layout = QVBoxLayout(self.tab_content)
        tab_content_layout.setContentsMargins(0, 0, 0, 0)
        tab_content_layout.addStretch()

        # MINECRAFT图片
        minecraft_logo = QLabel()
        minecraft_logo.setAlignment(Qt.AlignCenter)
        minecraft_logo_path = os.path.abspath(os.path.join(self.resource_path, 'images', 'user', 'MINECRAFT.png'))
        if os.path.exists(minecraft_logo_path):
            minecraft_pixmap = QPixmap(minecraft_logo_path)
            if not minecraft_pixmap.isNull():
                minecraft_logo.setPixmap(minecraft_pixmap)
                minecraft_logo.setFixedSize(minecraft_pixmap.size())
                logger.info(f"MINECRAFT图片加载成功: {minecraft_logo_path}")
            else:
                logger.error(f"MINECRAFT图片加载失败: {minecraft_logo_path}")
        else:
            logger.error(f"MINECRAFT图片文件不存在: {minecraft_logo_path}")
        tab_content_layout.addSpacing(20)
        tab_content_layout.addWidget(minecraft_logo, 0, Qt.AlignCenter)
        tab_content_layout.addSpacing(20)  # MINECRAFT图片与头像间距

        # 头像
        self.avatar = QLabel()
        self.avatar.setAlignment(Qt.AlignCenter)
        self.avatar.setFixedSize(80, 80)
        self.avatar.setStyleSheet("background-color: #2b2b2b; border: none;")
        self.set_default_avatar()
        tab_content_layout.addWidget(self.avatar, 0, Qt.AlignCenter)

        # 用户名标签
        self.username_label = QLabel("未登录")
        self.username_label.setFont(QFont("Source Han Sans CN Heavy", 8))
        self.username_label.setAlignment(Qt.AlignCenter)
        self.username_label.setStyleSheet("color: #f8f8f8;")
        tab_content_layout.addWidget(self.username_label, 0, Qt.AlignCenter)
        tab_content_layout.addSpacing(20)

        # 创建正版登录内容
        self.external_content = self.create_external_content()
        tab_content_layout.addWidget(self.external_content)

        # 创建离线登录内容
        self.offline_content = self.create_offline_content()
        self.offline_content.hide()
        tab_content_layout.addWidget(self.offline_content)
        tab_content_layout.addSpacing(40)
        
        # 创建启动游戏按钮 
        self.launch_btn = QMStartButton(resource_path=self.resource_path)
        self.launch_btn.set_texts('启动游戏', f"{self.launcher.version}" if self.launcher.version else "未找到对应游戏")
        self.launch_btn.clicked.connect(self.started_changed.emit)
        tab_content_layout.addWidget(self.launch_btn, 0, Qt.AlignCenter)

        # 创建进入联机大厅按钮
        self.multiplayer_lobby_btn = QLabel("进入联机大厅")
        self.multiplayer_lobby_btn.setFont(QFont("Source Han Sans CN Heavy", 8))
        self.multiplayer_lobby_btn.setAlignment(Qt.AlignCenter)
        self.multiplayer_lobby_btn.setStyleSheet("""
            QLabel {
                color: #4A5666;
                background-color: transparent;
                text-decoration: underline;
                font-weight: bold;
            }
            QLabel:hover {
                color: #7859FF;
            }
        """)
        # self.multiplayer_lobby_btn.mousePressEvent = lambda event: self.show_multiplayer_dialog()
        self.multiplayer_lobby_btn.setCursor(Qt.PointingHandCursor)
        tab_content_layout.addWidget(self.multiplayer_lobby_btn)
        tab_content_layout.addStretch(1)

        tab_container_layout.addWidget(self.tab_buttons_widget)
        tab_container_layout.addSpacing(23)
        tab_container_layout.addWidget(self.tab_content)

        main_layout.addWidget(self.tab_container)
        
        # 设置初始状态
        self.update_ui_state('未登录')

    def create_tab_buttons(self):
        """创建选项卡按钮区域"""
        tab_buttons_widget = QWidget()
        tab_buttons_widget.setFixedWidth(178)
        tab_buttons_widget.setContentsMargins(0, 0, 0, 0)   
        tab_buttons_layout = QVBoxLayout(tab_buttons_widget)
        tab_buttons_layout.setContentsMargins(0, 0, 0, 0)
        tab_buttons_layout.addSpacing(20)   

        # 离线选项卡按钮
        self.offline_tab_btn = self.create_tab_button(
            "离线登录",
            self.offline_tab_btn_clicked,
            size=(155, 44), font_size=10
        )
        tab_buttons_layout.addWidget(self.offline_tab_btn, 0, Qt.AlignCenter)
        
        # 正版选项卡按钮
        self.external_tab_btn = self.create_tab_button(
            "正版登录",
            self.external_tab_btn_clicked,
            size=(155, 44), font_size=10
        )
        tab_buttons_layout.addWidget(self.external_tab_btn, 0, Qt.AlignCenter)
        tab_buttons_layout.addStretch()
        
        # 设置初始状态：正版登录默认选中
        self.update_tab_button_style("正版登录", True)
        self.update_tab_button_style("离线登录", False)
        
        return tab_buttons_widget

    def create_tab_button(self, text, click_handler, size=(155, 44), font_size=12):
        """创建选项卡按钮"""
        button = QLabel()
        button.mousePressEvent = lambda event: click_handler()
        button.setFixedSize(*size)
        button.setStyleSheet("background-color: transparent;")
        
        # 添加文本
        text_label = QLabel(text, button)
        text_label.setFont(QFont("Source Han Sans CN Heavy", font_size))
        text_label.setAlignment(Qt.AlignCenter)  
        text_label.setStyleSheet("color: white; background-color: transparent;")
        text_label.setGeometry(0, 0, *size)   
        
        return button

    def create_external_content(self):
        """创建正版登录内容"""
        content = QWidget()
        content.setContentsMargins(0, 0, 0, 0)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.setAlignment(Qt.AlignCenter)
        
        # 正版登录按钮
        self.legal_login_btn = self.create_image_button(
            "正版登录", 
            os.path.join(self.resource_path, 'images', 'user', 'legal_login_btn.png'),
            self.authorized_online_login,
            235, 40,
            font_size=10
        )
        
        # 正版切换账号按钮
        switch_icon_path = os.path.join(self.resource_path, 'images', 'user', 'switch.png')
        self.legal_switch_account_btn = self.create_switch_account_button(
            "切换账号", 
            switch_icon_path, 
            self.switch_to_login_mode
        )
        self.legal_switch_account_btn.hide()
        
        # 添加组件到布局
        layout.addWidget(self.legal_login_btn, 0, Qt.AlignCenter)
        layout.addWidget(self.legal_switch_account_btn, 0, Qt.AlignCenter)

        return content

    def create_offline_content(self):
        """创建离线登录内容"""
        content = QWidget()
        content.setContentsMargins(0, 0, 0, 0)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.setAlignment(Qt.AlignCenter)
        
        # 用户名输入框
        username_layout = QHBoxLayout()
        username_layout.setContentsMargins(0, 0, 0, 0)
        username_layout.setSpacing(0)
        self.offline_username_input = QLineEdit()
        self.offline_username_input.setPlaceholderText("请输入用户名")
        self.offline_username_input.setFont(QFont("Source Han Sans CN Heavy", 10))
        self.offline_username_input.setFixedSize(192, 40)
        self.offline_username_input.setStyleSheet("""
            QLineEdit {
                background-color: #2A2C3E;
                color: #FFFFFF;
                border: 1px solid #000000;
                border-radius: 0px;
                padding: 8px;
                font-weight: bold;
            }
            QLineEdit::placeholder {
                color: rgba(255, 255, 255, 0.7);
            }
        """)
        
        # 离线登录按钮
        self.offline_login_btn = QLabel("确认")
        self.offline_login_btn.setFont(QFont("Source Han Sans CN Heavy", 10))
        self.offline_login_btn.setAlignment(Qt.AlignCenter)
        self.offline_login_btn.setFixedSize(50, 40)
        self.offline_login_btn.setStyleSheet("""
            QLabel {
                color: #FFFFFF;
                font-weight: bold;
                background: #7959FF;
                border: 1px solid #000000;
                opacity: 0.8;
                border-radius: 0px;
            }
            QLabel:hover {
                opacity: 1.0;
            }
        """)

        self.offline_login_btn.mousePressEvent = lambda event: self.authorized_login()
        self.offline_login_btn.setCursor(Qt.PointingHandCursor)
        
        # 离线切换账号按钮
        switch_icon_path = os.path.join(self.resource_path, 'images', 'user', 'switch.png')
        self.offline_switch_account_btn = self.create_switch_account_button(
            "切换账号",
            switch_icon_path,
            self.switch_account_offline
        )
        self.offline_switch_account_btn.hide()
        
        # 添加组件到布局
        username_layout.addWidget(self.offline_username_input)
        username_layout.addWidget(self.offline_login_btn)
        
        layout.addLayout(username_layout)
        layout.addWidget(self.offline_switch_account_btn)

        return content

    def create_switch_account_button(self, text, icon_path, click_handler):
        """创建带图标的切换账号按钮"""
        container = QWidget()
        container.setFixedSize(162, 40)
        container.setStyleSheet("""
            QWidget {
                color: #FFFFFF;
                font-weight: bold;
                background: rgba(184, 185, 255, 0.3);
                border: 1px solid #000000;
                opacity: 0.8;
                border-radius: 0px;
            }
            QWidget:hover {
                opacity: 1.0;
            }
        """)
        container.setCursor(Qt.PointingHandCursor)
        
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addStretch()
        
        # 图标标签
        icon_label = QLabel()
        if os.path.exists(icon_path):
            pixmap = QPixmap(icon_path)
            if not pixmap.isNull():
                scaled_pixmap = pixmap.scaled(12, 12, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                icon_label.setPixmap(scaled_pixmap)
        
        icon_label.setStyleSheet("background: transparent; border: none;")
        layout.addWidget(icon_label)
        
        text_label = QLabel(text)
        text_label.setFont(QFont("Source Han Sans CN Heavy", 10))
        text_label.setStyleSheet("background: transparent; border: none; color: #FFFFFF;")
        layout.addWidget(text_label)
        
        layout.addStretch()
        container.mousePressEvent = lambda event: click_handler()
        
        return container

    def create_image_button(self, text, image_path, click_handler, width, height, font_size=11):
        """创建图片按钮"""
        button = QLabel()
        button.mousePressEvent = lambda event: click_handler()
        button.setCursor(Qt.PointingHandCursor)
        button.setFixedSize(width, height)
        
        if image_path and os.path.exists(image_path):
            pixmap = QPixmap(image_path)
            if not pixmap.isNull():
                button.setPixmap(pixmap.scaled(width, height, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
        
        text_label = QLabel(text, button)
        text_label.setFont(QFont("Source Han Sans CN Heavy", font_size))
        text_label.setAlignment(Qt.AlignCenter)
        text_label.setStyleSheet("color: #f2f2f2; background-color: transparent;")
        text_label.setGeometry(0, 0, width, height)
        
        return button

    def set_default_avatar(self):
        """设置默认头像"""
        self.avatar.setStyleSheet("background-color: #2b2b2b; border: none;")
        default_avatar_path = os.path.join(self.resource_path, 'images', 'user', 'unlogged_avatar.png')
        if os.path.exists(default_avatar_path):
            pixmap = QPixmap(default_avatar_path)
            if not pixmap.isNull():
                self.avatar.setPixmap(pixmap.scaled(80, 80, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))

    def external_tab_btn_clicked(self):
        """正版登录按钮点击事件"""
        self.external_content.show()
        self.offline_content.hide()
        self.auth_manager.current_mode = 'online'
        self.update_tab_button_style("正版登录", True)
        self.update_tab_button_style("离线登录", False)
        self.current_login_mode = "正版登录"
        self.update_ui_state()
        self.restore_login_state()

    def offline_tab_btn_clicked(self):
        """离线登录按钮点击事件"""
        self.external_content.hide()
        self.offline_content.show()
        self.auth_manager.current_mode = 'offline'
        self.update_tab_button_style("正版登录", False)
        self.update_tab_button_style("离线登录", True)
        self.current_login_mode = "离线登录"
        self.update_ui_state()
        self.restore_login_state()

    def update_tab_button_style(self, tab_name, is_active):
        """更新选项卡按钮样式"""
        if tab_name == "正版登录":
            btn = self.external_tab_btn
            active_image = os.path.join(self.resource_path, 'images', 'user', 'external_tab_btn_active.png')
        else:
            btn = self.offline_tab_btn
            active_image = os.path.join(self.resource_path, 'images', 'user', 'external_tab_btn_active.png')
        
        if is_active and os.path.exists(active_image):
            btn.setPixmap(QPixmap(active_image).scaled(155, 44, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
        else:
            btn.clear()
            btn.setStyleSheet("background-color: transparent;")

    def update_ui_state(self, state="未登录"):
        """根据当前状态更新UI"""
        if state == "未登录":
            self.update_unlogged_state()
        elif state == "正版登录":
            self.update_online_logged_in_state()
        elif state == "离线登录":
            self.update_offline_logged_in_state()

    def update_unlogged_state(self):
        """更新未登录状态UI"""
        self.set_default_avatar()
        self.username_label.setText("未登录")
        
        if self.current_login_mode == "离线登录":
            self.offline_username_input.show()
            self.offline_login_btn.show()
            self.offline_switch_account_btn.hide()
            self.legal_login_btn.hide()
            self.legal_switch_account_btn.hide()
        else:
            self.offline_username_input.hide()
            self.offline_login_btn.hide()
            self.offline_switch_account_btn.hide()
            self.legal_login_btn.show()
            self.legal_switch_account_btn.hide()

    def update_online_logged_in_state(self):
        """更新正版登录状态UI"""
        # 设置头像
        self.auth_manager.current_mode = 'online'
        # if self.auth_manager.current.avatar and os.path.exists(self.auth_manager.current.avatar):
        #     pixmap = QPixmap(self.auth_manager.current.avatar)
        #     if not pixmap.isNull():
        #         self.avatar.setPixmap(pixmap.scaled(80, 80, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
        
        self.avatar.setStyleSheet(f"""
            QLabel {{
                background-color: #2b2b2b;
                border-radius: 0px;
                border: 2px solid #7859FF;
            }}
        """)

        # 设置用户名
        # print('self.auth_manager.current.username', self.auth_manager.current.username)
        # self.username_label.setText(self.auth_manager.current.username)
        
        # 更新按钮状态
        self.offline_username_input.hide()
        self.offline_login_btn.hide()
        self.offline_switch_account_btn.hide()
        self.legal_login_btn.hide()
        self.legal_switch_account_btn.show()

    def update_offline_logged_in_state(self):
        """更新离线登录状态UI"""
        # 设置头像
        self.auth_manager.current_mode = 'offline'
        if self.auth_manager.current.avatar and os.path.exists(self.auth_manager.current.avatar):
            pixmap = QPixmap(self.auth_manager.current.avatar)
            if not pixmap.isNull():
                self.avatar.setPixmap(pixmap.scaled(80, 80, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))

        # 更新头像
        self.avatar.setStyleSheet(f"""
            QLabel {{
                background-color: #2b2b2b;
                border-radius: 0px;
                border: 2px solid #7859FF;
            }}
        """)

        # 设置用户名
        print('self.auth_manager.current.username', self.auth_manager.current.username)
        self.username_label.setText(self.auth_manager.current.username)
        
        # 更新按钮状态
        self.offline_username_input.hide()
        self.offline_login_btn.hide()
        self.offline_switch_account_btn.show()
        self.legal_login_btn.hide()
        self.legal_switch_account_btn.hide()

    def switch_account_offline(self):
        """离线模式下的切换账号功能"""
        self.auth_manager.offline.clear()
        self.auth_manager.save(self.cache_path)
        self.update_ui_state('未登录')

    def authorized_login(self):
        """离线登录"""
        username = self.offline_username_input.text().strip()
        if not username:
            self.username_label.setText("请输入用户名")
            self.username_label.setStyleSheet("color: #F44336;")
            return
        self.username_label.setStyleSheet("color: #f8f8f8;")

        self.auth_manager.offline.username = username
        self.update_ui_state('离线登录')
        self.handle_auth_success(username=username, data={
            'type': 'offline'
        })

    def authorized_online_login(self):
        """正版登录"""
        self.login_dialog.start_login_process()
        self.login_dialog.exec()
    
    def switch_to_login_mode(self):
        """切换账号功能 - 从已登录状态切换回登录界面"""
        self.auth_manager.online.clear()
        self.auth_manager.save(self.cache_path)
        self.update_ui_state('未登录')

    def restore_login_state(self):
        """恢复登录状态"""
        
        if not self.auth_manager.current.username:
            return
        
        self.username_label.setText(self.auth_manager.current.username)
        self.username_label.setStyleSheet("color: #f8f8f8;")

        current = {'online': '正版登录', 'offline': '离线登录'}
        print('self.auth_manager.current_mode', self.auth_manager.current_mode)
        self.update_ui_state(current.get(self.auth_manager.current_mode, '未登录'))

        if not (self.auth_manager.current.avatar and os.path.exists(self.auth_manager.current.avatar)):
            # 头像不存在或下载失败时使用默认头像
            self.set_default_avatar()
        else:
            # 更新头像 - 优先使用登录获取的头像，否则使用默认头像
            self.avatar.setPixmap(QPixmap(self.auth_manager.current.avatar).scaled(80, 80, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))

    def paintEvent(self, event):
        """重绘事件 - 透明背景"""
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.background_color)    
        super().paintEvent(event)

    def handle_auth_success(self, username, data):
        """处理登录成功"""
        skin_avatar = data.get('skin', None)
        self.signals.output.emit(f"欢迎 {username}! 认证成功")

        self.username_label.setText(username)
        self.username_label.setStyleSheet("color: #f8f8f8;")

        if not (skin_avatar and os.path.exists(skin_avatar)):
            # 头像不存在或下载失败时使用默认头像
            skin_avatar = os.path.abspath(os.path.join(self.resource_path, 'images', 'user', 'offline_login.png'))
            logger.info(f"使用默认头像: {skin_avatar}")
            if not os.path.exists(skin_avatar):
                logger.error(f"默认头像文件不存在: {skin_avatar}")
   
        # 更新头像 - 优先使用登录获取的头像，否则使用默认头像
        self.avatar.setPixmap(QPixmap(skin_avatar).scaled(80, 80, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))

        state = '未登录'
        if data.get('type', None) == "online":  # 正版登录成功
            state = "正版登录"
            self.auth_manager.current_mode = 'online'
            self.auth_manager.online.uuid = data.get('uuid', None)
            self.auth_manager.online.username = username
            self.auth_manager.online.avatar = skin_avatar
            self.auth_manager.online.token = data.get('token', None)
            self.auth_manager.online.refresh_token = data.get('refresh_token', None)
            self.auth_manager.online.expires_at = data.get('expires_at', None)
            self.external_tab_btn_clicked()

            QTimer.singleShot(5000, lambda: self.is_expired_token())  # 正版时 定时验证token有效性
        elif data.get('type', None) == "offline":  # 离线登录成功
            state = "离线登录"
            self.auth_manager.current_mode = 'offline'
            self.auth_manager.offline.username = username
            self.auth_manager.offline.avatar = skin_avatar
            self.offline_tab_btn_clicked()
        
        self.update_ui_state(state)

        # 保存认证信息
        self.auth_manager.save(self.cache_path)

        logger.info(f"欢迎 {username}, {data.get('type', None)} !")
        self.login_success.emit({'uuid': data.get('uuid', None), 'username': username, 'token': data.get('token', None)}, data.get('type', None))

        # 登录成功后进入联机大厅按钮保持显示（包括离线登录）

    def setBackgroundColor(self, color):
        """设置新的背景颜色并更新界面"""
        if isinstance(color, str):
            self.backgroundColor = QColor(color)
        else:
            self.backgroundColor = color
        self.update()

    def create_tab_button(self, text, click_handler, size=(155, 44), font_size=12):
        """创建选项卡按钮"""
        button = QLabel()
        button.mousePressEvent = lambda event: click_handler()
        button.setFixedSize(*size)
        
        # 初始状态 保持透明
        button.setStyleSheet("background-color: transparent;")
        
        # 添加文本
        text_label = QLabel(text, button)
        text_label.setFont(QFont("Source Han Sans CN Heavy", font_size))
        text_label.setAlignment(Qt.AlignCenter)  
        text_label.setStyleSheet("color: white; background-color: transparent;")
        text_label.setGeometry(0, 0, *size)   
        
        return button
    
    def resizeEvent(self, event):
        """窗口大小变化事件 - 确保布局自适应"""
        super().resizeEvent(event)

    def moveEvent(self, event):
        """重写 moveEvent 以跟踪位置变化"""
        super().moveEvent(event)

    def is_expired_token(self):
        # 定时验证token有效性
        is_expired = self.auth.decoder.is_expired()
        if is_expired and is_expired is None:
            # token 过期
            self.avatar.clear()
            self.avatar.setStyleSheet(f"""
                QLabel {{
                    background-color: #2b2b2b;
                    border: 2px solid #ffffff;
                }}
            """)
            self.auth_manager.online.clear()
            self.auth_manager.save(self.cache_path)
            self.username_label.setText("正版授权已到有效期，需重新授权登录")  # TODO
            self.username_label.setStyleSheet(f"font-weight: bold; color: #f8f8f8;")

    def handle_auth_progress(self, progress):
        pass
    
    def handle_auth_failure(self, message):
        """处理登录失败"""
        self.signals.error.emit(f"登录失败: {message}")
