"""First-run setup flow for language, content preferences, and multiplayer."""
from pathlib import Path

from PySide6.QtCore import QObject, Property, Signal, Slot, Qt, QUrl
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QDialog, QVBoxLayout

from config.settings import get_settings_manager


class OnboardingController(QObject):
    changed = Signal()
    completed = Signal(str)

    def __init__(self, parent):
        super().__init__(parent)
        self.settings = get_settings_manager()
        self.step = 0
        self.language = self.settings.get_setting('game.language', 'zh_cn')
        self.translation = bool(self.settings.get_setting('translation.enabled', False))
        self.preferences = list(self.settings.get_setting('onboarding.game_preferences', []) or [])
        self.route = 'discover'

    @Property('QVariantMap', notify=changed)
    def view(self):
        return dict(step=self.step, language=self.language, translation=self.translation,
                    preferences=self.preferences, route=self.route)

    @Slot(str)
    def setLanguage(self, language):
        if language in ('zh_cn', 'zh_tw', 'en_us'):
            self.language = language
            self.changed.emit()

    @Slot(bool)
    def setTranslation(self, enabled):
        self.translation = bool(enabled)
        self.changed.emit()

    @Slot(str)
    def togglePreference(self, preference):
        allowed = {'survival', 'creative', 'modded', 'multiplayer'}
        if preference not in allowed:
            return
        selected = set(self.preferences)
        if preference in selected:
            selected.remove(preference)
        else:
            selected.add(preference)
        self.preferences = sorted(selected)
        self.changed.emit()

    @Slot(str)
    def setRoute(self, route):
        if route in ('create', 'discover'):
            self.route = route
            self.changed.emit()

    @Slot()
    def next(self):
        self.step = min(3, self.step + 1)
        self.changed.emit()

    @Slot()
    def back(self):
        self.step = max(0, self.step - 1)
        self.changed.emit()

    @Slot()
    def skip(self):
        self._save()
        self.completed.emit('')

    @Slot()
    def finish(self):
        self._save()
        self.completed.emit(self.route)

    def _save(self):
        self.settings.set_setting('game.language', self.language)
        self.settings.set_setting('translation.enabled', self.translation)
        self.settings.set_setting('onboarding.game_preferences', self.preferences)
        self.settings.set_setting('onboarding.completed', True)
        self.settings.save_settings()


class OnboardingDialog(QDialog):
    def __init__(self, launcher, resources):
        super().__init__(launcher, Qt.Dialog | Qt.FramelessWindowHint)
        self.launcher = launcher
        self.setWindowTitle('Buggcraft | Start')
        self.setFixedSize(800, 540)
        self.setWindowModality(Qt.WindowModal)
        if launcher is not None:
            self.move(launcher.geometry().center() - self.rect().center())
        self.controller = OnboardingController(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.quick = QQuickWidget(self)
        self.quick.setResizeMode(QQuickWidget.SizeRootObjectToView)
        self.quick.rootContext().setContextProperty('onboarding', self.controller)
        self.quick.setSource(QUrl.fromLocalFile(str(Path(resources) / 'qml' / 'launcher' / 'Onboarding.qml')))
        if self.quick.status() == QQuickWidget.Error:
            raise RuntimeError('First-run setup could not be loaded: ' + '\n'.join(error.toString() for error in self.quick.errors()))
        layout.addWidget(self.quick)
        self.controller.completed.connect(self._complete)

    @Slot(str)
    def _complete(self, route):
        self.accept()
        if not route:
            return
        page = self.launcher.started_page
        page.show_multiplayer_dialog()
        lobby = page._multiplayer_dialog.backend
        destination = 'hall'
        if route == 'create':
            destination = 'create' if lobby.view.get('nodeAvailable') else 'nodes'
        lobby.navigate(destination)\n