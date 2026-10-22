import QtQuick
import QtQuick.Layouts

RowLayout {
    property string number: "1"
    property string title: ""
    property string detail: ""
    spacing: 14
    Rectangle {
        Layout.alignment: Qt.AlignTop
        width: 22; height: 22; color: "#3b3058"
        CopyText { anchors.centerIn: parent; text: number; color: "#d0bbff"; font.bold: true }
    }
    ColumnLayout {
        Layout.fillWidth: true
        spacing: 2
        CopyText { Layout.fillWidth: true; text: title; color: "#f3f0ff"; font.pixelSize: 11; font.bold: true }
        CopyText { Layout.fillWidth: true; text: detail; visible: detail.length > 0; font.pixelSize:10 }
    }
}
