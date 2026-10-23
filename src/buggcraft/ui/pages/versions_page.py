"""QML instance page navigation."""
from ui.pages.qml_navigation import NavigationPage
from ui.pages.version import VersionsPage, SettingsPage


class VersionsPages(NavigationPage):
    def __init__(self, parent, resource_path, cache_path):
        super().__init__(parent, resource_path)
        self.cache_path = cache_path
        self.launcher = parent.launcher
        self.tab_names = ['版本列表', '版本设置']
        self.versions_page = VersionsPage(self)
        self.settings_page = SettingsPage(self)
        self.version_stack = self.stack
        self.stack.addWidget(self.versions_page)
        self.stack.addWidget(self.settings_page)
        self.set_entries(self.tab_names)

    @property
    def signals(self):
        return self.versions_page.signals

    def on_settings_clicked(self):
        self.navigation.activate(1)

    def on_versions_clicked(self):
        self.navigation.activate(0)

    def switch_pages(self, name):
        if name in self.tab_names:
            self.navigation.activate(self.tab_names.index(name))
