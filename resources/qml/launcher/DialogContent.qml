import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root
    property var state: dialogModel.view
    property bool deletionChoice: !!state.data.showKeepDirectory && (state.title === "移除游戏目录？" || state.title === "删除游戏实例？")
    property bool preserveFiles: state.data.keepDirectory !== "false"
    color: "#272937"
    border.color: "#655e9b"
    radius: 6
    MouseArea {
        objectName: "dialog-drag-region"
        anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
        height: 64
        acceptedButtons: Qt.LeftButton
        onPressed: dialogModel.dragWindow()
    }
    Connections { target: dialogModel; function onChanged() { root.state = dialogModel.view } }
    ColumnLayout {
        anchors.fill: parent; anchors.margins: 24; spacing: 14
        Label {
            id: titleLabel
            Layout.fillWidth: true; text: root.state.title; textFormat: Text.PlainText
            font.pixelSize: 19; font.bold: true; color: "#eeeef4"
        }
        Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: "#454052" }
        ScrollView {
            id: messageScroll
            Layout.fillWidth: true; Layout.fillHeight: true; visible: !root.state.log
            contentWidth: availableWidth
            contentHeight: messageBody.implicitHeight
            clip: true
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
            ColumnLayout {
                id: messageBody
                width: messageScroll.availableWidth; spacing: 14
                Label { objectName: "dialog-message"; Layout.fillWidth: true; text: root.state.message; textFormat: Text.PlainText; wrapMode: Text.Wrap; color: "#e0e0e8"; font.pixelSize: 15; font.bold: true }
                Label {
                    objectName: "dialog-detail"; Layout.fillWidth: true
                    text: root.deletionChoice
                        ? (root.preserveFiles ? "仅从启动器列表移除，游戏、模组和存档均保留。" : "请核对上方路径，确认已备份需要保留的存档。") : root.state.detail
                    textFormat: Text.PlainText; wrapMode: Text.Wrap; color: "#c0c0d0"; font.pixelSize: 13
                }
                CheckBox {
                    objectName: "keep-game-directory"
                    visible: root.deletionChoice
                    enabled: !root.state.working
                    checked: root.state.data.keepDirectory !== "false"
                    text: "仅从启动器移除，保留本地文件"
                    onToggled: dialogModel.setDataValue("keepDirectory", checked ? "true" : "false")
                    contentItem: Text {
                        text: parent.text; color: "#e0e0e8"; font.pixelSize: 13
                        leftPadding: parent.indicator.width + parent.spacing
                        verticalAlignment: Text.AlignVCenter
                    }
                }
                Rectangle {
                    objectName: "delete-local-files-warning"
                    Layout.fillWidth: true; implicitHeight: warningText.implicitHeight + 24
                    visible: root.deletionChoice
                    radius: 5
                    color: root.preserveFiles ? "#233d35" : "#4b2630"
                    border.color: root.preserveFiles ? "#548570" : "#da7382"
                    Label {
                        id: warningText
                        objectName: "delete-local-files-warning-text"
                        anchors.fill: parent; anchors.margins: 12
                        text: root.preserveFiles
                            ? (root.state.data.isDirectory ? "保留本地文件：以后可重新添加此游戏目录。" : "保留本地文件：可点击“恢复已移除实例”恢复显示。")
                            : (root.state.data.isDirectory ? "永久删除 · 会删除本地文件\n此文件夹及其中所有实例、存档、模组和资源都会被删除，无法撤销！" : "永久删除 · 会删除本地文件\n此实例文件夹中的存档、模组和资源都会被删除，无法撤销！")
                        color: root.preserveFiles ? "#bfe7ce" : "#ffb3bd"
                        font.pixelSize: 14; font.bold: true
                        textFormat: Text.PlainText; wrapMode: Text.Wrap
                    }
                }
                Label { objectName: "login-device-code"; Layout.fillWidth: true; visible: !!root.state.code; text: root.state.code; font.pixelSize: 26; font.bold: true; color: "#b7abff"; horizontalAlignment: Text.AlignHCenter }
                Label { objectName: "login-verification-uri"; Layout.fillWidth: true; visible: !!root.state.uri; text: root.state.uri; color: "#bfc4d5"; wrapMode: Text.Wrap; horizontalAlignment: Text.AlignHCenter }
            }
        }
        ScrollView {
            Layout.fillWidth: true; Layout.fillHeight: true; visible: !!root.state.log
            TextArea { readOnly: true; text: root.state.log; selectByMouse: true; wrapMode: TextEdit.Wrap; color: "#e0e0e8"; font.pixelSize: 12; background: Rectangle { color: "#1d202b" } }
        }
        ProgressBar {
            Layout.fillWidth: true
            visible: root.state.working
            indeterminate: root.state.progress < 0
            from: 0; to: 1
            value: Math.max(0, root.state.progress)
        }
        RowLayout {
            Layout.fillWidth: true
            Item { Layout.fillWidth: true }
            ActionButton { objectName: "copy-login-code"; visible: !!root.state.code; text: root.state.copied ? "已复制" : "复制登录码"; onClicked: dialogModel.copyCode() }
            Repeater {
                model: root.state.actions
                delegate: ActionButton {
                    required property string modelData
                    required property int index
                    objectName: "dialog-action-" + index
                    implicitWidth: 84
                    text: root.deletionChoice && index === 1 ? (root.preserveFiles ? "仅移除" : "永久删除") : modelData
                    enabled: root.state.actionsEnabled
                    primary: modelData === root.state.primaryAction
                    danger: root.deletionChoice && index === 1 ? !root.preserveFiles : modelData === root.state.dangerAction
                    onClicked: dialogModel.action(modelData)
                }
            }
        }
    }
}
