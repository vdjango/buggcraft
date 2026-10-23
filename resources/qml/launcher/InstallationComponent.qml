import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Rectangle {
    id: root
    property string name: ""
    property string description: "不安装"
    property string symbol: ""
    property url icon: ""
    property bool selected: false
    property bool available: true
    property bool fixed: false
    signal choose()
    signal remove()
    width: 140; height: 150
    color: selected || !available ? "#33beb7ff" : "#1abeb7ff"
    ColumnLayout {
        anchors.fill: parent; anchors.margins: 10; spacing: 5
        Item { Layout.preferredHeight: 0 }
        Item {
            Layout.preferredWidth: 50; Layout.preferredHeight: 50; Layout.alignment: Qt.AlignHCenter
            Image { anchors.fill: parent; visible: !!root.icon.toString(); source: root.icon; fillMode: Image.PreserveAspectFit }
            Label { anchors.centerIn: parent; visible: !root.icon.toString(); text: root.symbol || root.name.substring(0, 2); font.pixelSize: 21; font.bold: true; color: "#ded7ff" }
        }
        Item { Layout.preferredHeight: 0 }
        Label { Layout.fillWidth: true; text: root.name; color: "#f2f2f2"; font.pixelSize: 13; font.bold: true; horizontalAlignment: Text.AlignHCenter }
        Label { Layout.fillWidth: true; text: root.description; color: "#b3ffffff"; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.Wrap; maximumLineCount: 2; elide: Text.ElideRight }
        Item { Layout.fillHeight: true }
    }
    MouseArea {
        anchors.fill: parent; enabled: root.available && !root.fixed
        cursorShape: Qt.PointingHandCursor; onClicked: root.choose()
    }
    IconButton {
        objectName: root.objectName + "-remove"
        anchors.top: parent.top; anchors.right: parent.right
        width: 25; height: 25; visible: root.selected && !root.fixed
        source: "../../images/version/close.png"; text: "移除 " + root.name
        onClicked: root.remove()
    }
}
