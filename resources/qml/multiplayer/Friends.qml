import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

ColumnLayout {
    id: root
    property var vm: lobby.view
    property int tab: vm.friendTab || 0
    Connections {
        target: lobby
        ignoreUnknownSignals: true
        function onShowInvitations() { root.tab = 2 }
    }
    property var items: tab === 0 ? (vm.contacts || []) : tab === 1 ? (vm.friendRequests || []) : (vm.friendInvitations || [])
    spacing: 10
    RowLayout {
        Layout.fillWidth: true
        CopyText { objectName: "friend-access-mode"; Layout.fillWidth: true; text: vm.nodeAccessExpired ? "接入码已过期" : vm.socialLoading ? "正在登录…" : vm.socialReady ? vm.socialName : "匿名接入"; font.pixelSize: 13; color: "#e5dfef" }
        HeaderAction { text: "↻"; label: "刷新好友"; visible: !!vm.socialReady; onClicked: lobby.act("refreshFriends", {}) }
        ActionButton { objectName: "add-friend"; text: "添加好友"; visible: !!vm.socialReady; primary: true; implicitHeight: 30; onClicked: lobby.act("navigate", {page:"friendForm"}) }
    }
    CopyText { Layout.fillWidth: true; visible: !vm.socialReady; text: vm.socialError || "匿名接入没有好友功能。请在节点网页登录，领取个人启动器接入码并添加到启动器。"; font.pixelSize: 12 }
    Surface {
        objectName: "pending-friend-invite-banner"
        visible: !!vm.pendingFriendInvite
        Layout.fillWidth: true; implicitHeight: 50
        color: "#302741"; border.color: "#76629e"
        RowLayout {
            anchors.fill: parent; anchors.margins: 8; spacing: 8
            CopyText { Layout.fillWidth: true; text: "正在等房间开放，之后会自动邀请 " + vm.pendingFriendInvite; color: "#e5dcf5"; font.pixelSize: 12; wrapMode: Text.Wrap }
            ActionButton { objectName: "cancel-pending-friend-invite"; text: "取消"; quiet: true; implicitHeight: 28; onClicked: lobby.act("cancelFriendInvite", {}) }
        }
    }
    ActionButton { objectName: "friends-replace-node-code"; visible: !!vm.nodeAccessExpired; text: "更换接入码"; primary: true; onClicked: lobby.act("replaceNodeCode", {}) }
    Surface {
        objectName: "friend-invite-banner"
        Layout.fillWidth: true; Layout.preferredHeight: 46
        visible: !!vm.socialReady && (vm.friendInvitations || []).length > 0
        color: "#3a2c52"; border.color: "#a28aef"
        RowLayout {
            anchors.fill: parent; anchors.margins: 9; spacing: 8
            CopyText { Layout.fillWidth: true; text: "你有 " + vm.friendInvitations.length + " 个联机邀请"; color: "#f3eaff"; font.pixelSize: 12; font.bold: true }
            ActionButton { objectName: "show-friend-invites"; text: "查看"; primary: true; implicitHeight: 28; onClicked: root.tab = 2 }
        }
    }
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
                    CopyText { Layout.fillWidth: true; text: root.tab === 0 ? (vm.outgoingInvitations && vm.outgoingInvitations[modelData.account] ? vm.outgoingInvitations[modelData.account].status : modelData.online ? "在线" : "离线") : root.tab === 1 ? (modelData.incoming ? "请求添加你为好友" : "等待对方同意") : "邀请你一起玩 · 5 分钟内有效"; font.pixelSize: 11; elide: Text.ElideRight; wrapMode: Text.NoWrap }
                }
                ActionButton { visible: root.tab === 0; text: removing ? "确认移除" : "移除"; quiet: true; danger: true; implicitHeight: 28; implicitWidth: 64; enabled: !vm.friendBusy; onClicked: { if (removing) lobby.act("removeFriend", {account:modelData.account}); else removing = true } }
                ActionButton {
                    objectName: "invite-friend-" + (modelData.index || 0); visible: root.tab === 0
                    property var inviteState: vm.outgoingInvitations ? vm.outgoingInvitations[modelData.account] : null
                    text: !inviteState ? "邀请" : inviteState.status === "发送中…" ? "发送中" : inviteState.status === "等待房间开放，自动发送" ? "待发送" : inviteState.status === "已发送" ? "再邀请" : "重试"
                    implicitHeight: 28; implicitWidth: 64
                    enabled: !!modelData.online && !vm.friendBusy && (!inviteState || !["等待房间开放，自动发送", "发送中…"].includes(inviteState.status))
                    ToolTip.visible: hovered; ToolTip.text: "没有房间时会先引导创建并等待世界开放"
                    onClicked: lobby.act("inviteFriend", {account:modelData.account})
                }
                ActionButton { visible: root.tab === 1; text: modelData.incoming ? "拒绝" : "撤回"; quiet: true; implicitHeight: 28; implicitWidth: 58; enabled: !vm.friendBusy; onClicked: lobby.act("declineFriend", {account:modelData.account}) }
                ActionButton { objectName: "accept-friend"; visible: root.tab === 1 && !!modelData.incoming; text: "同意"; primary: true; implicitHeight: 28; implicitWidth: 58; enabled: !vm.friendBusy; onClicked: lobby.act("acceptFriend", {account:modelData.account,id:modelData.id}) }
                ActionButton { objectName: "join-friend-invite"; visible: root.tab === 2; text: "加入"; primary: true; implicitHeight: 28; implicitWidth: 58; enabled: !vm.friendBusy; onClicked: lobby.act("joinFriend", {account:modelData.account,id:modelData.id}) }
                ActionButton { objectName: "ignore-friend-invite"; visible: root.tab === 2; text: "忽略"; quiet: true; implicitHeight: 28; implicitWidth: 48; enabled: !vm.friendBusy; onClicked: lobby.act("ignoreFriendInvite", {id:modelData.id}) }
            }
        }
        CopyText { anchors.centerIn: parent; width: parent.width - 24; visible: list.count === 0; horizontalAlignment: Text.AlignHCenter; text: root.tab === 0 ? "还没有好友，发送一份申请吧。" : root.tab === 1 ? "暂无好友申请" : "暂无联机邀请"; font.pixelSize: 12 }
    }
    CopyText { Layout.fillWidth: true; visible: !!vm.socialReady; text: vm.socialError || ""; color: "#ffbcb6"; font.pixelSize: 11 }
}
