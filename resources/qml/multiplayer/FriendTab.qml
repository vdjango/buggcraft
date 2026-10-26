import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../shared" as Shared

Button {
    id: control
    property bool selected: false
    property int count: 0
    property bool attention: false
    property bool urgent: false
    implicitHeight: 38; implicitWidth: contentItem.implicitWidth + 16
    leftPadding: 8; rightPadding: 8; hoverEnabled: true
    Accessible.name: text + " " + count
    contentItem: RowLayout {
        spacing: 7
        Text {
            text: control.text; color: control.selected ? "#f2eafa" : "#afa4bc"
            font.pixelSize: 13; font.bold: control.selected
        }
        Rectangle {
            visible: control.count > 0
            implicitWidth: badge.implicitWidth + 10; implicitHeight: 18; radius: 3
            color: control.urgent && control.count > 0 ? "#a9405d" : control.selected ? "#574174" : "#302838"
            Text { id: badge; anchors.centerIn: parent; text: control.count; font.pixelSize: 10; color: "#ded0f0" }
        }
    }
    background: Item {
        Rectangle { anchors.fill: parent; color: control.hovered ? "#272030" : "transparent" }
        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 2; color: control.selected ? "#b695ff" : "transparent" }
        Rectangle { anchors.fill: parent; color: "transparent"; border.color: control.visualFocus ? "#bc9ff1" : "transparent" }
    }
    Shared.AttentionFrame { active: control.attention; tint: control.urgent ? "#f283aa" : "#a68aff" }
    HoverHandler { cursorShape: Qt.PointingHandCursor }
}
