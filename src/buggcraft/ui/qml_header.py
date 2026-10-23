"""Qt Quick title bar with the original artwork and bounded version popup."""
from pathlib import Path
import logging

from PySide6.QtCore import QEvent, QObject, Property, QPoint, QTimer, QUrl, Qt, Signal, Slot
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout

from config.settings import get_settings_manager
from ui.pages.qml_host import QmlPage
from utils.instances import installed_instance_ids

logger = logging.getLogger(__name__)

class HeaderController(QObject):
    changed = Signal()

    def __init__(self, window, resources):
        super().__init__(window)
        self.window = window
        self.header = None
        self.resources = QUrl.fromLocalFile(str(Path(resources).resolve()) + '/').toString()
        self.versions = []
        self.selected = ''
        self.active = '开始'
        self.collapsed = False
        self.picker_open = False
        self.picker_index = -1

    @Property('QVariantMap', notify=changed)
    def view(self):
        return dict(resources=self.resources, versions=self.versions, selected=self.selected,
                    active=self.active, collapsed=self.collapsed,
                    picker_open=self.picker_open, picker_index=self.picker_index)

    @Slot(str)
    def navigate(self, name):
        if name in ('开始', '下载', '设置', '实例'):
            self.active = name
            self.changed.emit()
            self.header.tab_switch_clicked.emit(name)

    @Slot()
    def refreshVersions(self):
        self.header.refresh_versions()

    @Slot(str)
    def selectVersion(self, value):
        # Finish the popup's activation handler before rebuilding its model.
        was_open = self.picker_open
        self.dismissVersionPicker()
        if was_open:
            QTimer.singleShot(0, self, lambda: self.header.on_version_selected(value))
        else:
            self.header.on_version_selected(value)

    @Slot(float, float)
    def openVersionPicker(self, x, y):
        self.header.show_version_picker(x, y)

    @Slot()
    def dismissVersionPicker(self):
        if self.header._picker is not None:
            self.header._picker.hide()

    def set_selected(self, value):
        self.selected = value or ''
        self.changed.emit()

    @Slot()
    def toggleMenu(self):
        self.collapsed = not self.collapsed
        self.changed.emit()
        self.header.menu_toggle_signal.emit(self.collapsed)

    @Slot()
    def minimize(self):
        self.window.showMinimized()

    @Slot()
    def closeWindow(self):
        self.window.close()

    @Slot()
    def dragWindow(self):
        handle = self.window.windowHandle()
        if handle:
            handle.startSystemMove()


class TitleBar(QmlPage):
    tab_switch_clicked = Signal(str)
    menu_toggle_signal = Signal(bool)
    version_changed = Signal(str)

    def __init__(self, parent, resource_path):
        controller = HeaderController(parent, resource_path)
        super().__init__(parent, resource_path, 'LauncherHeader.qml', 'headerModel', controller)
        self.parent = parent
        self.settings_manager = get_settings_manager()
        self.resource_path = resource_path
        self._picker = None
        self.setFixedHeight(50)
        self.version_popup = controller
        controller.header = self
        self.refresh_versions()

    def show_version_picker(self, x, y):
        self.refresh_versions()
        self.controller.picker_index = (self.controller.versions.index(self.controller.selected)
                                        if self.controller.selected in self.controller.versions else -1)
        if self._picker is None:
            self._picker = VersionPicker(self, self.resource_path)
        picker = self._picker
        height = min(420, max(74, len(self.controller.versions) * 59) + 10)
        width = 310
        position = self.quick.mapToGlobal(QPoint(round(x), round(y)))
        screen = QApplication.screenAt(position) or QApplication.primaryScreen()
        if screen is not None:
            bounds = screen.availableGeometry()
            width = min(width, bounds.width())
            height = min(height, max(1, bounds.height() - 12))
        picker.resize(width, height)
        # Align the popup's right edge with its trigger, as in the original picker.
        position.setX(position.x() + 125 - width)
        if screen is not None:
            position.setX(max(bounds.left(), min(position.x(), bounds.right() - picker.width() + 1)))
            if position.y() + height > bounds.bottom() + 1:
                position.setY(max(bounds.top(), position.y() - height - 35))
        picker.move(position)
        picker.show()
        picker.host.ensure_loaded()
        picker.quick.setFocus()
        self.controller.picker_open = True
        self.controller.changed.emit()

    def set_active_tab(self, name):
        self.controller.active = name
        self.controller.changed.emit()

    def refresh_versions(self):
        versions = installed_instance_ids(self.settings_manager.get_setting('minecraft.directory.enable'))
        previous = self.settings_manager.get_setting('minecraft.version.enable')
        selected = previous if previous in versions else versions[0] if versions else None
        if self.settings_manager.get_setting('minecraft.version.installed') != versions or selected != previous:
            self.settings_manager.set_setting('minecraft.version.installed', versions)
            self.settings_manager.set_setting('minecraft.version.enable', selected)
            self.settings_manager.save_settings()
        self.controller.versions = ([selected] + [version for version in versions if version != selected]
                                    if selected else versions)
        self.controller.set_selected(selected)
        if selected != previous:
            self.version_changed.emit(selected or '')

    def on_version_selected(self, version):
        if version not in installed_instance_ids(self.settings_manager.get_setting('minecraft.directory.enable')):
            self.refresh_versions()
            return
        if version == self.settings_manager.get_setting('minecraft.version.enable'):
            return
        self.settings_manager.set_setting('minecraft.version.enable', version)
        logger.info('Selected launcher instance: %s', version)
        self.settings_manager.save_settings()
        self.controller.set_selected(version)
        self.version_changed.emit(version)


class VersionPicker(QWidget):
    """Keep the existing QML ChoiceBox in a QWidget popup owned by the header.

    Avoid a QQuickPopupWindow attached to QQuickWidget's offscreen window.
    The popup stays alive across selections; only its visibility changes.
    """
    def __init__(self, header, resources):
        super().__init__(header, Qt.Popup | Qt.FramelessWindowHint)
        self.header = header
        self.host = QmlPage(self, resources, 'VersionPicker.qml', 'headerModel',
                            header.controller, own_controller=False)
        self.quick = self.host.quick
        self.quick.installEventFilter(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.host)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.KeyPress and self._handle_key(event.key()):
            event.accept()
            return True
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event):
        if self._handle_key(event.key()):
            event.accept()
        else:
            super().keyPressEvent(event)

    def _handle_key(self, key):
        model = self.header.controller
        if key == Qt.Key_Escape:
            self.hide()
            return True
        if key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            if 0 <= model.picker_index < len(model.versions):
                model.selectVersion(model.versions[model.picker_index])
            return True
        if key not in (Qt.Key_Home, Qt.Key_End, Qt.Key_Up, Qt.Key_Down, Qt.Key_PageUp, Qt.Key_PageDown):
            return False
        if key == Qt.Key_Home:
            index = 0
        elif key == Qt.Key_End:
            index = len(model.versions) - 1
        else:
            index = model.picker_index + {Qt.Key_Up: -1, Qt.Key_Down: 1, Qt.Key_PageUp: -7, Qt.Key_PageDown: 7}[key]
        model.picker_index = max(0, min(index, len(model.versions) - 1)) if model.versions else -1
        model.changed.emit()
        return True

    def hideEvent(self, event):
        self.header.controller.picker_open = False
        self.header.controller.changed.emit()
        super().hideEvent(event)
