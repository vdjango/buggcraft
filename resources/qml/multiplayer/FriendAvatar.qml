import QtQuick

Rectangle {
    id: avatar
    property string name: ""
    property bool online: false
    property bool showStatus: true
    property int tone: name.length ? name.charCodeAt(0) % 4 : 0
    implicitWidth: 38; implicitHeight: 38
    color: ["#423455", "#303e50", "#34463f", "#4b3b39"][tone]
    border.color: ["#78608e", "#577491", "#597c69", "#8b6a61"][tone]
    Text {
        anchors.centerIn: parent; text: avatar.name.slice(0, 1).toUpperCase() || "?"
        color: "#f2eafa"; font.pixelSize: 18; font.bold: true
    }
    Rectangle {
        visible: avatar.showStatus
        anchors.right: parent.right; anchors.bottom: parent.bottom
        anchors.rightMargin: -2; anchors.bottomMargin: -2
        width: 11; height: 11; radius: 6
        color: avatar.online ? "#88d6a7" : "#777180"
        border.width: 2; border.color: "#201c29"
    }
}
