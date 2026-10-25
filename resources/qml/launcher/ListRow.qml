import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Shared compact row for instances, Java versions, resources and task lists.
Rectangle {
    id: row
    property string title: ""
    property string description: ""
    property url icon: ""
    property bool selected: false
    property Component actions
    property Component footer
    signal clicked()
    implicitHeight: 70 + (footerLoader.item ? footerLoader.item.implicitHeight : 0)
    color: selected ? "#2b2538" : rowMouse.containsMouse ? "#211e2a" : "transparent"
    border.color: selected ? "#7964a9" : "transparent"
    MouseArea { id: rowMouse; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: row.clicked() }
    Rectangle { visible: row.selected; x: 0; y: 8; width: 3; height: row.height - 16; radius: 1; color: "#a88df1" }
    Rectangle { anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom; height: 1; color: "#393445" }
    RowLayout {
        id: header
        anchors.top: parent.top; anchors.left: parent.left; anchors.right: parent.right
        height: row.footer ? 70 : row.height
        anchors.leftMargin: 14; anchors.rightMargin: 14
        spacing: 12
        Image {
            id: rowIcon
            visible: !!row.icon.toString(); Layout.preferredWidth: 30; Layout.preferredHeight: 30
            source: row.icon; fillMode: Image.PreserveAspectFit; asynchronous: true
            Image {
                anchors.fill: parent; visible: rowIcon.status !== Image.Ready
                source: visible ? "../../images/user/offline_login.png" : ""
                fillMode: Image.PreserveAspectFit
            }
        }
        ColumnLayout {
            Layout.fillWidth: true; spacing: 5
            Label {
                Layout.fillWidth: true; text: row.title; color: "#f2f2f2"; font.pixelSize: 13; font.bold: true; elide: Text.ElideRight
                HoverHandler { id: titleHover }
                ToolTip.visible: titleHover.hovered; ToolTip.text: text
            }
            Label { Layout.fillWidth: true; text: row.description; color: "#aaa2bb"; font.pixelSize: 11; elide: Text.ElideRight }
        }
        Loader { sourceComponent: row.actions; Layout.preferredWidth: item ? item.implicitWidth : 0 }
    }
    Loader {
        id: footerLoader
        anchors.top: header.bottom; anchors.left: parent.left; anchors.right: parent.right
        anchors.leftMargin: 15; anchors.rightMargin: 15
        sourceComponent: row.footer
        height: item ? item.implicitHeight : 0
    }
}
