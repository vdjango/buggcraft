import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

ColumnLayout {
    id: section
    property string title: ""
    property string summary: ""
    property bool collapsible: true
    property bool expanded: true
    property bool inlineControl: false
    property bool headerVisible: true
    property Component headerControl
    default property alias body: contents.data
    spacing: 0

    Rectangle {
        Layout.fillWidth: true
        implicitHeight: section.inlineControl ? 46 : 54
        visible: section.headerVisible
        color: "#292536"
        border.color: "#49415c"
        border.width: 1
        MouseArea {
            objectName: section.objectName + "-header"
            anchors.fill: parent
            enabled: section.collapsible
            cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
            onClicked: section.expanded = !section.expanded
        }
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 18; anchors.rightMargin: 18
            spacing: 14
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 2
                Label { Layout.fillWidth: true; text: section.title; color: "white"; font.pixelSize: 13; font.bold: true; elide: Text.ElideRight }
                Label { Layout.fillWidth: true; visible: !!section.summary; text: section.summary; color: "#aaaaaa"; font.pixelSize: 12; elide: Text.ElideMiddle }
            }
            Loader { sourceComponent: section.headerControl; Layout.preferredWidth: item ? item.implicitWidth : 0 }
            Image {
                visible: section.collapsible
                Layout.preferredWidth: 16; Layout.preferredHeight: 16
                source: "../../images/version/" + (section.expanded ? "fold-up.png" : "expand.png")
            }
        }
    }
    Rectangle {
        Layout.fillWidth: true
        implicitHeight: contents.implicitHeight + 28
        visible: section.expanded && !section.inlineControl
        color: "#1d1a25"
        border.color: "#383246"
        border.width: 1
        ColumnLayout {
            id: contents
            anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
            anchors.margins: 18
            spacing: 10
        }
    }
}
