import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Rectangle {
    id: root
    property var state: dialogModel.view
    color: "#211f2b"; radius: 8; border.color: "#8b85da"
    Connections { target: dialogModel; function onChanged() { root.state = dialogModel.view } }
    ColumnLayout {
        anchors.fill: parent; anchors.margins: 22; spacing: 14
        Label { text: root.state.title; font.pixelSize: 18; font.bold: true; color: "#f4f1ff" }
        Label {
            Layout.fillWidth: true; text: root.state.data.instance || ""
            textFormat: Text.PlainText; elide: Text.ElideMiddle; color: "#aaa2c8"; font.pixelSize: 12
        }
        ListView {
            objectName: "missing-mod-list"
            Layout.fillWidth: true; Layout.fillHeight: true; clip: true; spacing: 7
            model: root.state.data.mods || []
            ScrollBar.vertical: ScrollBar {}
            delegate: Rectangle {
                required property var modelData
                width: ListView.view.width - 12; height: row.implicitHeight + 20
                radius: 5; color: "#302a40"; border.color: "#514361"
                ColumnLayout {
                    id: row; anchors.left: parent.left; anchors.right: parent.right
                    anchors.top: parent.top; anchors.margins: 10; spacing: 5
                    Label {
                        Layout.fillWidth: true; text: modelData.name; textFormat: Text.PlainText
                        wrapMode: Text.WrapAnywhere; color: "#f1d1a1"; font.bold: true; font.pixelSize: 13
                    }
                    Label {
                        Layout.fillWidth: true; text: modelData.reason; textFormat: Text.PlainText
                        wrapMode: Text.Wrap; color: "#bfb4cd"; font.pixelSize: 12
                    }
                }
            }
        }
        Label {
            objectName: "missing-mod-warning"; Layout.fillWidth: true
            text: "跳过后会继续安装。缺少必需模组可能导致游戏无法启动。"
            wrapMode: Text.Wrap; color: "#f1d1a1"; font.pixelSize: 12
        }
        Rectangle {
            Layout.fillWidth: true; implicitHeight: help.implicitHeight + 22; radius: 6; color: "#292538"
            Label {
                id: help; objectName: "missing-mod-multiplayer-help"
                anchors.fill: parent; anchors.margins: 11; wrapMode: Text.Wrap
                text: "联机时，若房主正在使用这些模组，请向房主索要，并放入此实例的 mods 文件夹；房主没有使用的模组无需补齐。"
                color: "#d7cee8"; font.pixelSize: 12
            }
        }
        RowLayout {
            Layout.fillWidth: true; spacing: 10
            Label { text: (root.state.data.mods || []).length + " 个模组"; color: "#aaa2c8"; font.pixelSize: 11 }
            Item { Layout.fillWidth: true }
            ActionButton { objectName: "missing-mod-stop"; text: "停止导入"; onClicked: dialogModel.action(text) }
            ActionButton { objectName: "missing-mod-continue"; text: "跳过并继续"; primary: true; onClicked: dialogModel.action(text) }
        }
    }
}
