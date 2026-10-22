import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

ColumnLayout {
    id: root
    property var vm: lobby.view
    property int tab: 0
    property var items: tab === 0 ? (vm.contacts || []) : tab === 1 ? (vm.friendRequests || []) : (vm.friendInvitations || [])
    spacing: 10
    RowLayout {
        Layout.fillWidth: true
        CopyText { objectName: "friend-access-mode"; Layout.fillWidth: true; text: vm.socialReady ? vm.socialName : "匿名接入"; font.pixelSize: 13; color: "#e5dfef" }
        HeaderAction { text: "↻"; label: "刷新好友"; visible: !!vm.socialReady; onClicked: lobby.act("refreshFriends", {}) }
        ActionButton { objectName: "add-friend"; text: "添加好友"; visible: !!vm.socialReady; primary: true; implicitHeight: 30; onClicked: lobby.act("navigate", {page:"friendForm"}) }
    }
    CopyText { Layout.fillWidth: true; visible: !vm.socialReady; text: vm.socialError || "匿名接入没有好友功能。请在节点网页登录，领取个人接入码并添加到启动器。"; font.pixelSize: 12 }
    RowLayout {
        visible: !!vm.socialReady; Layout.fillWidth: true; spacing: 4
        Repeater {
            model: ["好友 · " + (vm.contacts || []).length, "申请 · " + (vm.friendRequests || []).length, "邀请 · " + (vm.friendInvitations || []).length]
            ActionButton { required property int index; required property string modelData; Layout.fillWidth: true; text: modelData; primary: root.tab === index; implicitHeight: 30; onClicked: root.tab = index }
        }
    }
    ListView {
        id: list; objectName: "friends-list"; visible: !!vm.socialReady
        Layout.fillWidth: true; Layout.fillHeight: true; clip: true; spacing: 6
        model: root.items
        ScrollBar.vertical: ScrollBar {}
        delegate: Rectangle {
            required property var modelData
            property bool removing: false
            width: list.width; height: 72; color: "#24212d"; border.color: "#41394e"
            RowLayout {
                anchors.fill: parent; anchors.margins: 9; spacing: 8
                Rectangle { Layout.preferredWidth: 7; Layout.preferredHeight: 7; radius: 4; color: root.tab === 0 && modelData.online ? "#8ad9ae" : "#7e7889" }
                ColumnLayout {
                    Layout.fillWidth: true; Layout.minimumWidth: 0; spacing: 3
                    CopyText { Layout.fillWidth: true; text: modelData.name || modelData.username; color: "#f3eff9"; font.pixelSize: 13; font.bold: true; wrapMode: Text.NoWrap; elide: Text.ElideRight }
                    CopyText { Layout.fillWidth: true; text: root.tab === 0 ? (modelData.online ? "在线" : "离线") : root.tab === 1 ? (modelData.incoming ? "请求添加你为好友" : "等待对方同意") : "邀请你一起玩 · 5 分钟内有效"; font.pixelSize: 11; elide: Text.ElideRight; wrapMode: Text.NoWrap }
                }
                ActionButton { visible: root.tab === 0; text: removing ? "确认移除" : "移除"; quiet: true; danger: true; implicitHeight: 28; implicitWidth: 64; enabled: !vm.friendBusy; onClicked: { if (removing) lobby.act("removeFriend", {account:modelData.account}); else removing = true } }
                ActionButton { objectName: "invite-friend-" + (modelData.index || 0); visible: root.tab === 0; text: "邀请"; implicitHeight: 28; implicitWidth: 58; enabled: !!modelData.online && !vm.friendBusy && vm.connections.some(function(c) { return c.role === "host" && c.state === "online" }); ToolTip.visible: hovered; ToolTip.text: "邀请加入当前创建的房间"; onClicked: lobby.act("inviteFriend", {account:modelData.account}) }
                ActionButton { visible: root.tab === 1; text: modelData.incoming ? "拒绝" : "撤回"; quiet: true; implicitHeight: 28; implicitWidth: 58; enabled: !vm.friendBusy; onClicked: lobby.act("declineFriend", {account:modelData.account}) }
                ActionButton { objectName: "accept-friend"; visible: root.tab === 1 && !!modelData.incoming; text: "同意"; primary: true; implicitHeight: 28; implicitWidth: 58; enabled: !vm.friendBusy; onClicked: lobby.act("acceptFriend", {account:modelData.account,id:modelData.id}) }
                ActionButton { objectName: "join-friend-invite"; visible: root.tab === 2; text: "加入"; primary: true; implicitHeight: 28; implicitWidth: 58; enabled: !vm.friendBusy; onClicked: lobby.act("joinFriend", {account:modelData.account,id:modelData.id}) }
            }
        }
        CopyText { anchors.centerIn: parent; width: parent.width - 24; visible: list.count === 0; horizontalAlignment: Text.AlignHCenter; text: root.tab === 0 ? "还没有好友，发送一份申请吧。" : root.tab === 1 ? "暂无好友申请" : "暂无联机邀请"; font.pixelSize: 12 }
    }
    CopyText { Layout.fillWidth: true; visible: !!vm.socialReady; text: vm.socialError || ""; color: "#ffbcb6"; font.pixelSize: 11 }
}
