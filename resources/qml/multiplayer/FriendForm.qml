import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

ColumnLayout {
    property var vm: lobby.view
    spacing: 16
    CopyText { text: "添加好友"; color: "#f4efff"; font.pixelSize: 18; font.bold: true }
    CopyText { Layout.fillWidth: true; text: "用户名"; font.pixelSize: 12 }
    InputField {
        id: identifier; objectName: "friend-identifier"; Layout.fillWidth: true; maximumLength: 32
        placeholderText: "输入对方的用户名"; enabled: !vm.friendBusy && !!vm.socialReady
        onAccepted: if (!vm.friendBusy && vm.socialReady) lobby.act("saveFriend", {identifier:text})
    }
    CopyText { Layout.fillWidth: true; text: "可以添加同一联机网络中的用户。对方同意后，你们才能互相查看在线状态和发送联机邀请。"; font.pixelSize: 12 }
    RowLayout {
        Layout.fillWidth: true
        ActionButton { text: "返回"; quiet: true; onClicked: lobby.act("navigate", {page:"friends"}) }
        Item { Layout.fillWidth: true }
        ActionButton { objectName: "save-friend"; text: vm.friendBusy ? "发送中…" : "发送申请"; primary: true; enabled: !!vm.socialReady && !vm.friendBusy && identifier.text.trim().length >= 3; onClicked: lobby.act("saveFriend", {identifier:identifier.text}) }
    }
    Item { Layout.fillHeight: true }
}
