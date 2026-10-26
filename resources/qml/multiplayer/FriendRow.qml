import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Rectangle {
    id: row
    required property var person
    objectName: "friend-row-" + (person.index || 0)
    property int mode: 0
    property bool busy: false
    property bool inviteBlocked: false
    property bool canRequestJoin: false
    property var joinRequest: null
    property var receivedInvite: null
    readonly property var room: person.room || ({})
    property var inviteState: null
    property bool joining: false
    readonly property string username: person.name || person.username || "玩家"
    readonly property string displayName: person.alias || username
    signal action(string name, var data)
    implicitHeight: 72
    color: hover.hovered ? "#2b2335" : "transparent"
    HoverHandler { id: hover }
    Rectangle { anchors.left: parent.left; anchors.leftMargin: 12; anchors.right: parent.right; anchors.rightMargin: 12; anchors.bottom: parent.bottom; height: 1; color: "#342c3e" }
    RowLayout {
        anchors.fill: parent; anchors.margins: 12; spacing: 12
        FriendAvatar { name: row.username; online: !!row.person.online; showStatus: row.mode === 0; Layout.preferredWidth: 38; Layout.preferredHeight: 38 }
        ColumnLayout {
            Layout.fillWidth: true; Layout.minimumWidth: 0; spacing: 4
            RowLayout {
                Layout.fillWidth: true; spacing: 5
                CopyText { Layout.fillWidth: true; text: row.displayName; font.pixelSize: 13; font.bold: true; color: "#eee7f5"; wrapMode: Text.NoWrap; elide: Text.ElideRight }
                CopyText { visible: row.mode === 0 && !!row.person.favorite; text: "★"; color: "#d7b582"; font.pixelSize: 11 }
            }
            CopyText {
                Layout.fillWidth: true; font.pixelSize: 11; wrapMode: Text.NoWrap; elide: Text.ElideRight
                color: row.mode === 0 && row.person.online ? "#a8cbb4" : "#a79bae"
                text: row.mode === 0 ? (row.inviteState ? row.inviteState.status :
                    !row.person.online ? "离线" : row.room.id ? (row.room.role === "host" ? "房主 · " : "联机中 · ") + (row.room.title || "好友的房间") + (row.room.availability === "waiting" ? " · 等待世界开放" : "") : "在线，可以一起玩") :
                    row.mode === 1 ? (row.person.incoming ? "想添加你为好友" : "申请已发送，等待回应") : row.mode === 3 ? "想加入你的房间 · 同意后自动发送邀请" : row.joining ? "正在接受邀请并连接房间…" : "邀请你一起联机 · 接受后自动连接"
            }
        }
        ActionButton {
            objectName: "request-join-friend-" + (row.person.index || 0)
            visible: row.mode === 0 && !!row.person.online && !!row.room.can_request && row.canRequestJoin
            text: row.receivedInvite ? "加入联机" : row.joinRequest && row.joinRequest.status === "pending" ? "等待同意" : row.joinRequest && row.joinRequest.status === "declined" ? "再次申请" : "申请加入"
            implicitHeight: 30; implicitWidth: 80; primary: true
            enabled: !row.busy && (!!row.receivedInvite || !row.joinRequest || row.joinRequest.status !== "pending")
            ToolTip.visible: hovered; ToolTip.text: row.joinRequest && row.joinRequest.status === "declined" ? "房主暂未同意，可以重新申请" : "房主同意后，你会收到可直接加入的邀请"
            onClicked: row.action(row.receivedInvite ? "joinFriend" : "requestJoinFriend", {account:row.person.account, id:row.receivedInvite ? row.receivedInvite.id : ""})
        }
        ActionButton {
            objectName: "invite-friend-" + (row.person.index || 0)
            visible: row.mode === 0; primary: !!row.person.online
            text: !row.inviteState ? "邀请联机" : row.inviteState.status === "发送中…" ? "发送中…" :
                row.inviteState.status === "等待房间开放，自动发送" ? "继续邀请" : row.inviteState.status === "已发送" ? "再次邀请" : "重试邀请"
            implicitHeight: 30; implicitWidth: 88
            enabled: !row.inviteBlocked && (row.inviteState && row.inviteState.status === "等待房间开放，自动发送" || !!row.person.online && (!row.inviteState || row.inviteState.status !== "发送中…"))
            ToolTip.visible: hovered; ToolTip.text: row.person.online ? "没有房间时会引导创建，开放世界后自动发送邀请" : "好友上线后可邀请"
            onClicked: row.action(row.inviteState && row.inviteState.status === "等待房间开放，自动发送" ? "continueFriendInvite" : "inviteFriend", {account:row.person.account})
        }
        HeaderAction {
            objectName: "friend-more-" + (row.person.index || 0)
            visible: row.mode === 0; iconName: "more"; label: "管理 " + row.displayName; enabled: !row.busy
            onClicked: row.action("manageFriend", {account:row.person.account, name:row.username, alias:row.person.alias || "", favorite:!!row.person.favorite, anchorX:mapToItem(null, width, height).x, anchorY:mapToItem(null, width, height).y})

        }
        ActionButton { visible: row.mode === 1; text: row.person.incoming ? "拒绝" : "撤回申请"; quiet: true; implicitHeight: 30; enabled: !row.busy; onClicked: row.action("declineFriend", {account:row.person.account}) }
        ActionButton { objectName: "accept-friend"; visible: row.mode === 1 && !!row.person.incoming; text: "同意"; primary: true; implicitHeight: 30; enabled: !row.busy; onClicked: row.action("acceptFriend", {account:row.person.account,id:row.person.id}) }
        ActionButton { objectName: "ignore-friend-invite"; visible: row.mode === 2; text: "忽略"; quiet: true; implicitHeight: 30; enabled: !row.busy; onClicked: row.action("ignoreFriendInvite", {id:row.person.id}) }
        ActionButton { objectName: "join-friend-invite"; visible: row.mode === 2; text: row.joining ? "连接中…" : "加入联机"; primary: true; implicitHeight: 30; implicitWidth: 88; enabled: !row.busy; onClicked: row.action("joinFriend", {account:row.person.account,id:row.person.id}) }
        ActionButton { objectName: "decline-join-request"; visible: row.mode === 3; text: "暂不接纳"; quiet: true; implicitHeight: 30; enabled: !row.busy; onClicked: row.action("declineJoinRequest", {account:row.person.account,id:row.person.id}) }
        ActionButton { objectName: "accept-join-request"; visible: row.mode === 3; text: "同意加入"; primary: true; implicitHeight: 30; implicitWidth: 88; enabled: !row.busy; onClicked: row.action("acceptJoinRequest", {account:row.person.account,id:row.person.id}) }
    }
}
