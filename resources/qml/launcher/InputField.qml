import QtQuick
import QtQuick.Controls

TextField {
    id: control
    implicitHeight: 36
    color: "#f0edf8"
    placeholderTextColor: "#aaa2ba"
    selectByMouse: true
    font.pixelSize: 12
    background: Rectangle {
        color: "#211f2b"
        radius: 4
        border.width: 1
        border.color: control.activeFocus ? "#a99bf8" : "#625277"
    }
}
