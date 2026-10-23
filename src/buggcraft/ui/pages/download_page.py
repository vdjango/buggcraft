"""QML download navigation and shared background task service."""
from ui.pages.qml_navigation import NavigationPage
from ui.pages.download import GamesPage, TasksPage
from ui.pages.download.content_browser import ContentBrowserPage


class DownloadPages(NavigationPage):
    def __init__(self, parent, resource_path, cache_path):
        super().__init__(parent, resource_path)
        self.cache_path = cache_path
        self.launcher = parent.launcher
        self.tab_names = ['游戏下载', '下载记录', '内容下载']
        self.games_page = GamesPage(self)
        self.tasks_page = TasksPage(self)
        self.content_page = ContentBrowserPage(self)
        parent.title_bar.version_changed.connect(self.content_page.controller.refreshContext)
        self.games_page.quick.rootContext().setContextProperty('contentController', self.content_page.controller)
        self.version_stack = self.stack
        for page in (self.games_page, self.tasks_page, self.content_page):
            self.stack.addWidget(page)
        self.set_entries(['游戏下载', '下载记录'])
        self.content_page.controller.pageRequested.connect(
            lambda page: self.on_progress_clicked() if page == 'tasks' else
            self.return_from_import() if page == 'browse' else None)
        self.tasks_page.installed.connect(lambda version, directory: self.games_page.signals.complete.emit(version))

    @property
    def signals(self):
        return self.games_page.signals

    def on_page_activate(self):
        self.content_page.controller.refreshContext()
        super().on_page_activate()
        if self.games_page.controller.category != 'game':
            self.content_page.controller.refresh()
        else:
            self.games_page.controller.refresh()

    def on_navigation(self, index):
        if index in (0, 1):
            if index == 0 and self.content_page.controller.view == 'import':
                self.content_page.controller.view = 'browse'
                self.content_page.controller.changed.emit()
            self.activate_index(index)

    def return_from_import(self):
        self.navigation.index = 0
        self.navigation.changed.emit()
        self.activate_index(0)

    def on_progress_clicked(self):
        self.parent.switch_pages('下载')
        self.navigation.index = 1
        self.navigation.changed.emit()
        self.activate_index(1)

    def on_download_clicked(self):
        self.parent.switch_pages('下载')
        self.navigation.index = 0
        self.navigation.changed.emit()
        self.games_page.controller.openContent('game')
        self.activate_index(0)

    def open_content(self, kind='mod', view='browse'):
        self.parent.switch_pages('下载')
        self.navigation.index = 0
        self.navigation.changed.emit()
        if view == 'browse':
            self.games_page.controller.openContent(kind)
            self.activate_index(0)
        else:
            if view != 'import':
                self.content_page.controller.setKind(kind)
            self.content_page.controller.setView(view)
            self.activate_index(2)

    def switch_pages(self, name):
        if name in self.tab_names:
            self.activate_index(self.tab_names.index(name))

    def shutdown(self):
        content = self.content_page.controller.shutdown()
        catalogue = self.games_page.shutdown()
        tasks = self.tasks_page.shutdown()
        return content and catalogue and tasks
