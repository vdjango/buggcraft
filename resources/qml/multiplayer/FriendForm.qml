import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

ColumnLayout {
    id: form
    property var vm: lobby.view
    readonly property bool validName: /^(?:[A-Za-z0-9_-]{3,32}|[0-9a-f]{32}\.[0-9a-f]{32})$/.test(identifier.text.trim())
    spacing: 16
    Item { Layout.fillHeight: true; Layout.maximumHeight: 24 }
    FriendAvatar { name: "友"; showStatus: false; Layout.preferredWidth: 52; Layout.preferredHeight: 52; Layout.alignment: Qt.AlignHCenter }
    ColumnLayout {
        Layout.fillWidth: true; spacing: 7
        CopyText { Layout.fillWidth: true; text: "下次一起玩，直接邀请"; horizontalAlignment: Text.AlignHCenter; font.pixelSize: 18; font.bold: true; color: "#f1e7fc" }
        CopyText { Layout.fillWidth: true; text: "输入同一联机网络中朋友的账号 ID 或用户名。"; horizontalAlignment: Text.AlignHCenter; font.pixelSize: 12 }
    }
    Surface {
        Layout.fillWidth: true; implicitHeight: entry.implicitHeight + 32
        color: "#211b2b"; border.color: "#493952"
        ColumnLayout {
            id: entry
            anchors.top: parent.top; anchors.left: parent.left; anchors.right: parent.right; anchors.margins: 16; spacing: 10
            CopyText { text: "朋友的账号 ID / 用户名"; color: "#e2d6ed"; font.pixelSize: 12 }
            InputField {
                id: identifier; objectName: "friend-identifier"; Layout.fillWidth: true; maximumLength: 65; implicitHeight: 38
                placeholderText: "粘贴完整账号 ID，或输入用户名"; enabled: !vm.friendBusy && !!vm.socialReady
                Component.onCompleted: forceActiveFocus()
                onAccepted: if (form.validName && !vm.friendBusy && vm.socialReady) lobby.act("saveFriend", {identifier:text})
            }
            CopyText {
                Layout.fillWidth: true
                text: identifier.text.length > 0 && !form.validName ? "用户名使用 3–32 位字母、数字、下划线或短横线，也可粘贴完整账号 ID。" : "同名时请核对账号 ID。对方同意后即可邀请联机。"
                color: identifier.text.length > 0 && !form.validName ? "#dcba91" : "#a99ab7"; font.pixelSize: 11; wrapMode: Text.Wrap
            }
            ActionButton {
                objectName: "save-friend"; Layout.fillWidth: true; implicitHeight: 36
                text: vm.friendBusy ? "正在发送申请…" : "发送好友申请"; primary: true
                enabled: !!vm.socialReady && !vm.friendBusy && form.validName
                onClicked: lobby.act("saveFriend", {identifier:identifier.text})
            }
            Repeater {
                model: vm.friendLookupResults || []
                delegate: ActionButton {
                    required property var modelData
                    Layout.fillWidth: true; implicitHeight: 48
                    text: modelData.username + " · " + modelData.account
                    enabled: !vm.friendBusy && !!vm.socialReady
                    onClicked: { identifier.text = modelData.account; lobby.act("saveFriend", {identifier:modelData.account}) }
                }
            }
        }
    }
    RowLayout {
        Layout.fillWidth: true; spacing: 8
        CopyText { Layout.fillWidth: true; text: "我的账号：" + (vm.socialName || "未连接"); font.pixelSize: 12; elide: Text.ElideRight; wrapMode: Text.NoWrap }
        ActionButton { objectName: "copy-social-name-form"; text: "复制给朋友"; quiet: true; implicitHeight: 28; enabled: !!vm.socialReady; onClicked: lobby.act("copySocialName", {}) }
    }
    Item { Layout.fillHeight: true }
    ActionButton { text: "返回好友列表"; Layout.alignment: Qt.AlignHCenter; quiet: true; implicitHeight: 30; onClicked: lobby.act("navigate", {page:"friends"}) }
}
