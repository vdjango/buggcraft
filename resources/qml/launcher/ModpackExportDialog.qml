import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Rectangle {
    id: root
    property var state: dialogModel.view
    color: "#181722"
    border.color: root.state.data.phase === "error" ? "#b95f73" : "#735fd0"
    border.width: 1
    radius: 12

    Connections { target: dialogModel; function onChanged() { root.state = dialogModel.view } }
    MouseArea {
        objectName: "dialog-drag-region"
        anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
        height: 62; acceptedButtons: Qt.LeftButton
        onPressed: dialogModel.dragWindow()
    }
    ColumnLayout {
        anchors.fill: parent; anchors.margins: 26; spacing: 16
        RowLayout {
            Layout.fillWidth: true; spacing: 12
            Rectangle { width: 34; height: 34; radius: 10; color: "#392f66"
                Label { anchors.centerIn: parent; text: "↗"; color: "#d8d0ff"; font.pixelSize: 20; font.bold: true }
            }
            ColumnLayout { Layout.fillWidth: true; spacing: 2
                Label { text: root.state.title; color: "#f4f1ff"; font.pixelSize: 19; font.bold: true }
                Label { text: root.state.data.instance || "整合包"; color: "#aaa2c8"; font.pixelSize: 12; elide: Text.ElideRight; Layout.fillWidth: true }
            }
        }
        Rectangle { Layout.fillWidth: true; height: 1; color: "#302b43" }
        Label {
            objectName: "dialog-message"; Layout.fillWidth: true
            text: root.state.message; color: root.state.data.phase === "error" ? "#ffb5bd" : "#eeeaff"
            font.pixelSize: 16; font.bold: true; wrapMode: Text.Wrap
        }
        Label {
            objectName: "dialog-detail"; Layout.fillWidth: true
            text: root.state.detail; color: "#bcb6d0"; font.pixelSize: 13
            wrapMode: Text.Wrap; maximumLineCount: 2; elide: Text.ElideMiddle
        }
        RowLayout {
            Layout.fillWidth: true; visible: root.state.data.phase === "choose"
            spacing: 12
            Rectangle {
                Layout.fillWidth: true; height: 116; radius: 10; color: "#272239"; border.color: "#514774"
                ColumnLayout { anchors.fill: parent; anchors.margins: 16; spacing: 7
                    Label { text: "精简"; color: "#e9e3ff"; font.pixelSize: 15; font.bold: true }
                    Label { objectName: "compact-export-description"; text: "查询 Modrinth、CurseForge 并比对哈希，可下载的模组仅存链接，其余随包保留"; color: "#aaa2c8"; font.pixelSize: 12; wrapMode: Text.Wrap; Layout.fillWidth: true }
                }
            }
            Rectangle {
                Layout.fillWidth: true; height: 116; radius: 10; color: "#242131"; border.color: "#423a59"
                ColumnLayout { anchors.fill: parent; anchors.margins: 16; spacing: 7
                    Label { text: "常规"; color: "#e9e3ff"; font.pixelSize: 15; font.bold: true }
                    Label { text: "所有本地模组和资源文件都随包打包，导入时无需从资源站补齐"; color: "#aaa2c8"; font.pixelSize: 12; wrapMode: Text.Wrap; Layout.fillWidth: true }
                }
            }
        }
        Label {
            objectName: "export-source-links"
            Layout.fillWidth: true; visible: root.state.data.phase === "choose"
            text: "支持网站：<a href='https://modrinth.com'>modrinth.com</a> · <a href='https://www.curseforge.com/minecraft'>curseforge.com</a>"
            textFormat: Text.RichText; linkColor: "#b7a8ff"; color: "#aaa2c8"; font.pixelSize: 12
            onLinkActivated: function(link) { Qt.openUrlExternally(link) }
        }
        Rectangle {
            id: exportTrack
            objectName: "export-progress-bar"
            Layout.fillWidth: true; height: 8; radius: 4; color: "#2a253c"
            visible: root.state.working || root.state.data.phase === "complete"
            clip: true
            Rectangle {
                id: exportFill
                objectName: "export-progress-fill"
                width: root.state.progress < 0 ? parent.width * .24 : parent.width * Math.max(0, root.state.progress)
                height: parent.height; radius: 4; color: "#8b78e6"
                SequentialAnimation on x {
                    running: root.state.working && root.state.progress < 0
                    loops: Animation.Infinite
                    NumberAnimation { from: -exportFill.width; to: exportTrack.width; duration: 1100 }
                }
                onWidthChanged: if (root.state.progress >= 0) x = 0
            }
        }
        Label {
            objectName: "export-progress-text"; Layout.fillWidth: true
            visible: root.state.working
            text: root.state.progress < 0 ? "正在准备…" : Math.round(root.state.progress * 100) + "%"
            font.pixelSize: 12; color: "#c5b9ff"
        }
        Label {
            Layout.fillWidth: true; visible: root.state.data.phase === "complete"
            text: "导出完成，确认文件无误后点击关闭"; color: "#b9e5cf"; font.pixelSize: 12
        }
        RowLayout { Layout.fillWidth: true
            Item { Layout.fillWidth: true }
            Repeater {
                model: root.state.actions
                delegate: ActionButton {
                    required property string modelData
                    required property int index
                    objectName: "dialog-action-" + index
                    text: modelData; enabled: root.state.actionsEnabled
                    primary: modelData === root.state.primaryAction
                    danger: modelData === root.state.dangerAction
                    onClicked: dialogModel.action(modelData)
                }
            }
        }
    }
}
