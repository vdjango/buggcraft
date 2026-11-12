"""System readings for the QML preview; mirrors the minimal C++ shell port."""

import sys

from PySide6.QtCore import QObject, QRect, Signal, Slot, Qt
from PySide6.QtGui import QCursor, QGuiApplication, QWindow


class PreviewDesktop(QObject):
    available_geometry_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        app = QGuiApplication.instance()
        for screen in app.screens():
            self._watch_screen(screen)
        app.screenAdded.connect(self._screen_added)
        app.screenRemoved.connect(lambda _screen: self.available_geometry_changed.emit())
        self._windows_user32 = None
        if sys.platform == "win32":
            import ctypes

            self._windows_user32 = ctypes.windll.user32

    def _watch_screen(self, screen):
        screen.availableGeometryChanged.connect(
            lambda _geometry: self.available_geometry_changed.emit()
        )

    def _screen_added(self, screen):
        self._watch_screen(screen)
        self.available_geometry_changed.emit()

    @Slot(QWindow, result=QRect)
    def available_geometry(self, window):
        screen = window.screen() if window else None
        screen = screen or QGuiApplication.primaryScreen()
        return screen.availableGeometry() if screen else QRect()

    @Slot(result=bool)
    def left_button_pressed(self):
        if self._windows_user32 is not None:
            return bool(self._windows_user32.GetAsyncKeyState(0x01) & 0x8000)
        return bool(QGuiApplication.mouseButtons() & Qt.LeftButton)

    @Slot(QWindow, result=bool)
    def pointer_inside(self, window):
        return bool(window and window.isVisible() and window.geometry().contains(QCursor.pos()))
