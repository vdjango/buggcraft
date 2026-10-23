class VisibilitySettings:
    """启动器可见性选项常量"""
    KEEP_VISIBLE = "游戏启动后保持不变"
    MINIMIZE = "游戏启动后最小化"
    HIDE = "游戏启动后隐藏，游戏退出后重新打开"
    CLOSE = "游戏启动后隐藏，游戏退出后关闭启动器"
    LEGACY_CLOSE = "游戏启动后立即关闭"


class LauncherVisibilityManager:
    """启动器可见性管理器"""
    def __init__(self, main_window):
        self.main_window = main_window
        self.current_setting = VisibilitySettings.KEEP_VISIBLE
        self.previous_state = None  # 保存窗口之前的状态
    
    def apply_setting(self, setting):
        """应用可见性设置"""
        if setting == VisibilitySettings.LEGACY_CLOSE:
            setting = VisibilitySettings.CLOSE
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
            # Automatic hiding is not the user's explicit close request.
            # Keep multiplayer alive for the game, then close on game exit.
            self.main_window._close_after_game = True
            self.main_window.hide()
            page = getattr(self.main_window, 'started_page', None)
            lobby = getattr(page, '_multiplayer_dialog', None)
            if lobby is not None:
                lobby.hide()
            debug = getattr(self.main_window, '_debug_dialog', None)
            if debug is not None:
                debug.hide()
    
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
