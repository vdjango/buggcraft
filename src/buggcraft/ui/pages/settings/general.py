"""General preferences rendered by the shared QML form."""
from ui.pages.qml_settings import QmlSettingsPage


class GeneralSettingsPages(QmlSettingsPage):
    def __init__(self, parent):
        super().__init__(parent, 'general')
