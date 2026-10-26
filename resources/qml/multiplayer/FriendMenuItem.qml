import QtQuick
import QtQuick.Controls.Basic

MenuItem {
    id: control
    property bool destructive: false
    implicitHeight: 36
    leftPadding: 12
    rightPadding: 12
    hoverEnabled: true
    contentItem: Text {
        text: control.text
        color: !control.enabled ? "#93879f" : control.destructive ? "#ffc1c1" : "#f1e8fc"
        font.pixelSize: 12
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
    background: Rectangle {
        color: control.down ? "#634479" : control.highlighted || control.hovered ? "#4b365f" : "transparent"
        border.width: control.visualFocus ? 1 : 0
        border.color: "#bfa0ef"
    }
}
