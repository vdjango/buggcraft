"""Verify input delivery through real Qt controls without desktop mouse APIs."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from _qml_test_support import QTest, qt_mouse_click, qt_mouse_drag, qt_mouse_move
from PySide6.QtCore import QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QCursor, QInputMethodEvent, QWheelEvent
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QApplication


_QML = b'''
import QtQuick
import QtQuick.Controls
Rectangle {
    width: 380; height: 300
    property int clicks: 0
    property int disabledClicks: 0
    property int coveredClicks: 0
    property int overlayClicks: 0
    property int wheelDelta: 0
    property int edits: 0
    property alias sliderValue: slider.value
    property alias inputText: editor.text
    Button { x: 10; y: 10; width: 100; height: 40
        text: "click"; onClicked: ++parent.clicks }
    Button { x: 130; y: 10; width: 100; height: 40
        enabled: false; onClicked: ++parent.disabledClicks }
    Button { x: 250; y: 10; width: 100; height: 40
        onClicked: ++parent.coveredClicks }
    Rectangle { x: 250; y: 10; width: 100; height: 40; z: 2
        MouseArea { anchors.fill: parent; onClicked: ++parent.parent.overlayClicks } }
    Slider { id: slider; x: 10; y: 80; width: 340; height: 40
        from: 0; to: 100; value: 0 }
    MouseArea { x: 10; y: 140; width: 340; height: 40
        onWheel: function(wheel) { parent.wheelDelta += wheel.angleDelta.y; wheel.accepted = true } }
    TextField { id: editor; x: 10; y: 210; width: 340; height: 40
        onTextEdited: ++parent.edits }
}
'''


class QtInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix='buggcraft-qt-input-')
        self.addCleanup(directory.cleanup)
        source = Path(directory.name) / 'Input.qml'
        source.write_bytes(_QML)
        self.widget = QQuickWidget()
        self.widget.setResizeMode(QQuickWidget.SizeRootObjectToView)
        self.widget.resize(380, 300)
        self.widget.setSource(QUrl.fromLocalFile(str(source)))
        self.assertEqual(self.widget.status(), QQuickWidget.Ready, self.widget.errors())
        self.widget.show()
        self.addCleanup(self.widget.close)
        self.addCleanup(self.widget.deleteLater)
        self.app.processEvents()
        self.root = self.widget.rootObject()
        # A regression to QTest's pointer-moving API must fail even if the
        # control happens to produce the expected business result afterwards.
        for owner, name in [(QCursor, 'setPos')] + [
                (QTest, name) for name in ('mouseMove', 'mouseClick', 'mousePress', 'mouseRelease')]:
            guard = patch.object(owner, name, side_effect=AssertionError('Desktop mouse API used: ' + name))
            guard.start()
            self.addCleanup(guard.stop)

    def test_click_obeys_enabled_state_and_visual_hit_testing(self):
        for point in (QPoint(60, 30), QPoint(180, 30), QPoint(300, 30)):
            qt_mouse_click(self.widget, point)
        self.app.processEvents()
        self.assertEqual(self.root.property('clicks'), 1)
        self.assertEqual(self.root.property('disabledClicks'), 0)
        self.assertEqual(self.root.property('coveredClicks'), 0)
        self.assertEqual(self.root.property('overlayClicks'), 1)

    def test_drag_and_wheel_change_the_actual_control_values(self):
        qt_mouse_drag(self.widget, QPoint(23, 100), QPoint(337, 100))
        self.assertGreater(self.root.property('sliderValue'), 90)
        qt_mouse_drag(self.widget, QPoint(337, 100), QPoint(23, 100))
        self.assertLess(self.root.property('sliderValue'), 10)
        point = QPoint(50, 160)
        qt_mouse_move(self.widget, point)
        event = QWheelEvent(QPointF(point), QPointF(self.widget.mapToGlobal(point)),
                            QPoint(), QPoint(0, -120), Qt.NoButton, Qt.NoModifier,
                            Qt.NoScrollPhase, False)
        self.app.sendEvent(self.widget, event)
        self.assertEqual(self.root.property('wheelDelta'), -120)

    def test_text_input_uses_the_focused_editor_and_unicode_input_method(self):
        qt_mouse_click(self.widget, QPoint(70, 230))
        QTest.keyClicks(self.widget, 'old value')
        self.assertEqual(self.root.property('inputText'), 'old value')
        QTest.keyClick(self.widget, Qt.Key_A, Qt.ControlModifier)
        event = QInputMethodEvent()
        event.setCommitString('上海节点网络诊断🙂')
        self.app.sendEvent(self.widget, event)
        self.assertEqual(self.root.property('inputText'), '上海节点网络诊断🙂')
        self.assertGreater(self.root.property('edits'), 1)
