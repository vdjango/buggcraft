"""QML side navigation and native hosts with the original page widths."""
from pathlib import Path

from PySide6.QtCore import QObject, Property, QUrl, Signal, Slot
from PySide6.QtWidgets import QWidget, QHBoxLayout, QStackedWidget

from ui.pages.qml_host import QmlPage


class NavigationController(QObject):
    changed = Signal()
    selected = Signal(int)

    def __init__(self, parent, resources):
        super().__init__(parent)
        self.entries = []
        self.index = 0
        self.resources = QUrl.fromLocalFile(str(Path(resources).resolve()) + '/').toString()

    @Property('QVariantMap', notify=changed)
    def view(self):
        return dict(entries=self.entries, currentIndex=self.index, resources=self.resources)

    @Slot(int)
    def activate(self, index):
        if 0 <= index < len(self.entries):
            self.index = index
            self.changed.emit()
            self.selected.emit(index)


class NavigationPage(QWidget):
    def __init__(self, parent, resource_path):
        super().__init__(parent)
        self.parent = parent
        self.resource_path = resource_path
        self.navigation = NavigationController(self, resource_path)
        self.tab_buttons_widget = QmlPage(self, resource_path, 'SidebarView.qml', 'navigation', self.navigation)
        self.tab_buttons_widget.setFixedWidth(199)
        self.stack = QStackedWidget(self)
        self.stack.setFixedWidth(686)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(15, 0, 15, 0)
        layout.setSpacing(6)
        layout.addWidget(self.tab_buttons_widget)
        layout.addWidget(self.stack)
        self.navigation.selected.connect(self.on_navigation)

    def set_entries(self, entries):
        self.navigation.entries = entries
        self.navigation.changed.emit()

    def on_navigation(self, index):
        self.activate_index(index)

    def activate_index(self, index):
        old = self.stack.currentWidget()
        if old is not None and hasattr(old, 'on_page_deactivate'):
            old.on_page_deactivate()
        self.stack.setCurrentIndex(index)
        page = self.stack.currentWidget()
        if hasattr(page, 'on_page_activate'):
            page.on_page_activate()

    def on_page_activate(self):
        page = self.stack.currentWidget()
        if page is not None and hasattr(page, 'on_page_activate'):
            page.on_page_activate()

    def on_page_deactivate(self):
        page = self.stack.currentWidget()
        if page is not None and hasattr(page, 'on_page_deactivate'):
            page.on_page_deactivate()

    def toggle_menu(self, menu_collapsed=False):
        self.tab_buttons_widget.setVisible(not menu_collapsed)
