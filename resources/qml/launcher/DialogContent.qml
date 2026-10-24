import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root
    property var state: dialogModel.view
    color: "#272937"
    border.color: "#655e9b"
    radius: 6
    Connections { target: dialogModel; function onChanged() { root.state = dialogModel.view } }
    ColumnLayout {
        anchors.fill: parent; anchors.margins: 24; spacing: 14
        Label {
            Layout.fillWidth: true; text: root.state.title
            font.pixelSize: 19; font.bold: true; color: "#eeeef4"
            MouseArea { anchors.fill: parent; onPressed: dialogModel.dragWindow() }
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
                Label { objectName: "dialog-detail"; Layout.fillWidth: true; text: root.state.detail; textFormat: Text.PlainText; wrapMode: Text.Wrap; color: "#c0c0d0"; font.pixelSize: 13 }
                Label { Layout.fillWidth: true; visible: !!root.state.code; text: root.state.code; font.pixelSize: 26; font.bold: true; color: "#b7abff"; horizontalAlignment: Text.AlignHCenter }
                Label { Layout.fillWidth: true; visible: !!root.state.uri; text: root.state.uri; color: "#bfc4d5"; wrapMode: Text.Wrap; horizontalAlignment: Text.AlignHCenter }
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
                    text: modelData
                    primary: modelData === root.state.primaryAction
                    danger: modelData === root.state.dangerAction
                    onClicked: dialogModel.action(modelData)
                }
            }
        }
    }
}
