"""Global game preferences rendered by QML."""
from ui.pages.qml_settings import QmlSettingsPage


class GlobalVersionSettingsPage(QmlSettingsPage):
    def __init__(self, parent):
        super().__init__(parent, 'global')
