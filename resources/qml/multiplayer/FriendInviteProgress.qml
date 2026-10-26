import QtQuick
import QtQuick.Layouts

Surface {
    id: root
    property var flow: ({})
    signal action(string name, var data)
    visible: !!flow.stage
    Layout.fillWidth: true
    implicitHeight: content.implicitHeight + 22
    color: "#30263f"
    border.color: flow.stage === "error" ? "#a66c7c" : "#80649f"
    ColumnLayout {
        id: content
        anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 11
        spacing: 7
        RowLayout {
            Layout.fillWidth: true; spacing: 8
            ColumnLayout {
                Layout.fillWidth: true; spacing: 3
                CopyText { objectName: "friend-invite-progress-title"; Layout.fillWidth: true; text: root.flow.title || ""; color: "#f0e5fc"; font.pixelSize: 12; font.bold: true; wrapMode: Text.Wrap }
                CopyText { Layout.fillWidth: true; text: "邀请 " + (root.flow.friend || "好友") + " · " + (root.flow.detail || ""); color: "#cbbbdc"; font.pixelSize: 11; wrapMode: Text.Wrap }
            }
            ActionButton {
                objectName: "continue-friend-invite"; visible: root.flow.action === "continue"
                text: root.flow.stage === "create" ? "去创建" : "查看房间"; primary: true; implicitHeight: 30
                onClicked: root.action("continueFriendInvite", {})
            }
            ActionButton { objectName: "retry-friend-invite"; visible: root.flow.action === "retry"; text: "重新邀请"; primary: true; implicitHeight: 30; onClicked: root.action("inviteFriend", {account:root.flow.account}) }
            HeaderAction {
                objectName: "cancel-pending-friend-invite"; visible: root.flow.stage !== "sending"
                text: "×"; label: root.flow.action === "continue" ? "取消待发送的邀请" : "收起邀请结果"
                implicitWidth: 24; implicitHeight: 26
                onClicked: root.action(root.flow.action === "continue" ? "cancelFriendInvite" : "dismissFriendInvite", {})
            }
        }
        RowLayout {
            Layout.fillWidth: true; spacing: 5
            Repeater {
                model: ["创建房间", "开放世界", "发送邀请"]
                delegate: RowLayout {
                    required property string modelData
                    required property int index
                    Layout.fillWidth: true; spacing: 5
                    Rectangle { width: 5; height: 5; color: root.flow.step >= index ? "#c3a4ff" : "#746280" }
                    CopyText { text: modelData; font.pixelSize: 10; color: root.flow.step >= index ? "#e0cefa" : "#9e8fac" }
                    Rectangle { visible: index < 2; Layout.fillWidth: true; height: 1; color: "#665374" }
                }
            }
        }
    }
}
