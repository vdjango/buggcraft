"""QML settings navigation; every content page is rendered by Qt Quick."""
from PySide6.QtCore import Signal
from ui.pages.qml_navigation import NavigationPage
from ui.pages.settings.general import GeneralSettingsPages
from ui.pages.settings.java import JavaManagementPage
from ui.pages.settings.about import AboutPage
from ui.pages.settings.version_settings import GlobalVersionSettingsPage


class SettingsPage(NavigationPage):
    settings_changed = Signal(str, object)

    def __init__(self, parent=None, config_path=None, resource_path=None, scale_ratio=1.0):
        super().__init__(parent, resource_path)
        self.cache_path = parent.cache_path
        self.config_path = config_path
        self.general_page = GeneralSettingsPages(self)
        self.java_page = JavaManagementPage(self)
        self.global_version_page = GlobalVersionSettingsPage(self)
        self.about_page = AboutPage(self)
        self.settings_stack = self.stack
        for page in (self.general_page, self.java_page, self.global_version_page, self.about_page):
            self.stack.addWidget(page)
        self.set_entries(['通用设置', '全局设置', 'Java管理', '关于'])

    def on_navigation(self, index):
        self.activate_index((0, 2, 1, 3)[index])

    def general_tab_btn_clicked(self):
        self.navigation.activate(0)

    def global_tab_btn_clicked(self):
        self.navigation.activate(1)

    def java_tab_btn_clicked(self):
        self.navigation.activate(2)

    def about_tab_btn_clicked(self):
        self.navigation.activate(3)
