"""Independent instance preferences rendered by QML."""
from ui.pages.qml_settings import QmlSettingsPage


class SettingsPage(QmlSettingsPage):
    def __init__(self, parent):
        super().__init__(parent, 'instance')
