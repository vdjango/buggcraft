import QtQuick

Rectangle {
    id: badge
    property int count: 0
    property bool urgent: false
    visible: count > 0
    width: Math.max(18, label.implicitWidth + 10); height: 18; radius: 4
    color: urgent ? "#cc566f" : "#7853bc"
    border.color: urgent ? "#ffb0bf" : "#c5a3f5"
    Text { id: label; anchors.centerIn: parent; text: badge.count > 99 ? "99+" : badge.count; color: "#ffffff"; font.pixelSize: 11; font.bold: true }
}
