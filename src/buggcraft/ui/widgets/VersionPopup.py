"""Installed instance picker with separate selection, hover and keyboard states."""
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout, QHBoxLayout, QScrollArea, QFrame, QApplication
from PySide6.QtCore import Qt, Signal, QPoint, QRect, QEvent
from PySide6.QtGui import QFont, QColor, QPainter
from ui.fonts import system_font
from ui.widgets.lable import SmartLabel


class VersionItem(QWidget):
    clicked = Signal(str)

    def __init__(self, version_id, description, resource_path, icon_path=None, height=59, parent=None):
        super().__init__(parent)
        self.version_id = version_id
        self.is_hovered = self.is_selected = self._pressed = False
        self.setFixedHeight(height)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName(version_id)
        self.setToolTip(version_id)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(12)
        self.version_label = SmartLabel(version_id, font_size=10, max_heiht=10000)
        self.version_label.setStyleSheet('color: #f4f0ff; background: transparent; border: none;')
        layout.addWidget(self.version_label, 1)
        self.selection_label = QLabel('✓ 当前')
        self.selection_label.setFont(system_font(9))
        self.selection_label.setStyleSheet('color: #d7cbff; background: transparent; border: none;')
        layout.addWidget(self.selection_label)
        for child in self.findChildren(QWidget):
            child.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.set_selected(False)

    def set_selected(self, selected):
        self.is_selected = bool(selected)
        self.selection_label.setVisible(self.is_selected)
        self.setAccessibleDescription('当前游戏版本' if selected else '按回车选择游戏版本')
        self.update()

    def selected(self):
        self.set_selected(True)

    def paintEvent(self, event):
        painter = QPainter(self)
        color = ('#473668' if self.is_hovered else '#392b58') if self.is_selected else (
            '#292735' if self.is_hovered else '#1d1c28')
        painter.fillRect(self.rect(), QColor(color))
        if self.is_selected:
            painter.fillRect(0, 7, 3, self.height() - 14, QColor('#a99bf8'))
        if self.hasFocus():
            painter.setPen(QColor('#8b85da'))
            painter.drawRect(self.rect().adjusted(2, 2, -3, -3))

    def enterEvent(self, event):
        self.is_hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.is_hovered = False
        self.update()
        super().leaveEvent(event)

    def focusInEvent(self, event):
        self.update()
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        self._pressed = False
        self.update()
        super().focusOutEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._pressed = True
            self.setFocus(Qt.MouseFocusReason)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        activate = self._pressed and event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint())
        self._pressed = False
        if activate:
            self.clicked.emit(self.version_id)
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            if not event.isAutoRepeat():
                self.clicked.emit(self.version_id)
            event.accept()
        else:
            super().keyPressEvent(event)


class VersionPopup(QWidget):
    version_selected = Signal(str)
    popup_closed = Signal()

    def __init__(self, trigger_widget, resource_path, parent=None):
        super().__init__(parent)
        self.trigger_widget = trigger_widget
        self.resource_path = resource_path
        self.version_items = []
        self.selected_version = None
        self.is_visible = False
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFixedWidth(310)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)
        self.setObjectName('VersionPopup')
        self.setStyleSheet('QWidget#VersionPopup { background: #1d1c28; border: 1px solid #8b85da; }')
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet('''
            QScrollArea, QScrollArea > QWidget > QWidget { background: #1d1c28; border: none; }
            QScrollBar:vertical { background: #1d1c28; width: 8px; }
            QScrollBar::handle:vertical { background: #7465ad; min-height: 24px; }
            QScrollBar::handle:vertical:hover { background: #a99bf8; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
        ''')
        self.versions_container = QWidget()
        self.versions_layout = QVBoxLayout(self.versions_container)
        self.versions_layout.setContentsMargins(0, 0, 0, 0)
        self.versions_layout.setSpacing(0)
        self.versions_layout.setAlignment(Qt.AlignTop)
        self.empty_label = QLabel('还没有可用版本\n请到“实例”导入游戏，或到“下载”安装。')
        self.empty_label.setWordWrap(True)
        self.empty_label.setStyleSheet('color: #c6c1d8; padding: 14px; background: transparent;')
        self.versions_layout.addWidget(self.empty_label)
        self.scroll_area.setWidget(self.versions_container)
        layout.addWidget(self.scroll_area)
        QApplication.instance().installEventFilter(self)
        self.hide()

    def add_version_item(self, version_id, icon_path=None):
        if any(item.version_id == version_id for item in self.version_items):
            return
        item = VersionItem(version_id, None, self.resource_path, icon_path)
        item.clicked.connect(self.on_version_selected)
        self.version_items.append(item)
        self.versions_layout.addWidget(item)
        self.empty_label.hide()
        self.update_popup_height()

    def set_versions(self, versions, selected=None):
        if list(versions) != [item.version_id for item in self.version_items]:
            self.clear_versions()
            for version in versions:
                self.add_version_item(version)
        self.set_selected(selected)

    def set_selected(self, version):
        self.selected_version = version if any(item.version_id == version for item in self.version_items) else None
        for item in self.version_items:
            item.set_selected(item.version_id == self.selected_version)

    def update_popup_height(self):
        self.setFixedHeight(min(420, max(84, len(self.version_items) * 59 + 2)))

    def show_popup(self):
        if self.is_visible:
            return
        self.update_popup_height()
        anchor = self.trigger_widget.mapToGlobal(QPoint(0, self.trigger_widget.height()))
        screen = self.trigger_widget.screen().availableGeometry()
        self.setFixedWidth(min(310, screen.width()))
        self.setFixedHeight(min(self.height(), max(1, screen.height() - 12)))
        x = min(max(screen.left(), anchor.x() + self.trigger_widget.width() - self.width()), screen.right() - self.width() + 1)
        y = anchor.y() + 3
        if y + self.height() > screen.bottom() + 1:
            y = max(screen.top(), anchor.y() - self.trigger_widget.height() - self.height() - 3)
        self.move(x, y)
        for item in self.version_items:
            item.is_hovered = False
            item.update()
        self.is_visible = True
        self.show()
        self.raise_()
        self.activateWindow()
        QApplication.setActiveWindow(self)
        selected = next((i for i in self.version_items if i.is_selected), None)
        if selected is None and self.version_items:
            selected = self.version_items[0]
        if selected:
            selected.setFocus(Qt.PopupFocusReason)
            self.scroll_area.ensureWidgetVisible(selected)
        else:
            self.setFocus(Qt.PopupFocusReason)

    def hide_popup(self):
        if self.is_visible:
            self.hide()

    def hideEvent(self, event):
        was_visible = self.is_visible
        self.is_visible = False
        for item in self.version_items:
            item.is_hovered = item._pressed = False
            item.update()
        if was_visible:
            self.popup_closed.emit()
        super().hideEvent(event)

    def toggle_popup(self):
        self.hide_popup() if self.is_visible else self.show_popup()

    def selected(self, version):
        self.on_version_selected(version)

    def on_version_selected(self, version_id):
        if not any(item.version_id == version_id for item in self.version_items):
            return
        self.set_selected(version_id)
        self.version_selected.emit(version_id)
        self.hide_popup()

    def clear_versions(self):
        for item in self.version_items:
            self.versions_layout.removeWidget(item)
            item.hide()
            item.deleteLater()
        self.version_items.clear()
        self.selected_version = None
        self.empty_label.show()
        self.update_popup_height()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.hide_popup()
            event.accept()
        else:
            super().keyPressEvent(event)

    def event(self, event):
        # QQuickWidget shortcuts from another launcher window must not steal Escape.
        if event.type() == QEvent.ShortcutOverride and event.key() in (
                Qt.Key_Escape, Qt.Key_Up, Qt.Key_Down, Qt.Key_Home, Qt.Key_End,
                Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            event.accept()
            return True
        return super().event(event)

    def eventFilter(self, obj, event):
        if self.is_visible:
            if event.type() == QEvent.MouseButtonPress:
                pos = event.globalPosition().toPoint()
                trigger = QRect(self.trigger_widget.mapToGlobal(QPoint()), self.trigger_widget.size())
                if not self.frameGeometry().contains(pos) and not trigger.contains(pos):
                    self.hide_popup()
            elif event.type() == QEvent.ApplicationDeactivate:
                self.hide_popup()
            elif event.type() == QEvent.KeyPress and (obj is self or isinstance(obj, QWidget) and self.isAncestorOf(obj)):
                key = event.key()
                if key == Qt.Key_Escape:
                    self.hide_popup()
                    self.trigger_widget.setFocus()
                    return True
                if self.version_items and key in (Qt.Key_Up, Qt.Key_Down, Qt.Key_Home, Qt.Key_End):
                    index = self.version_items.index(obj) if obj in self.version_items else 0
                    index = (0 if key == Qt.Key_Home else len(self.version_items) - 1 if key == Qt.Key_End
                             else (index + (1 if key == Qt.Key_Down else -1)) % len(self.version_items))
                    item = self.version_items[index]
                    item.setFocus(Qt.TabFocusReason)
                    self.scroll_area.ensureWidgetVisible(item)
                    return True
        return super().eventFilter(obj, event)
