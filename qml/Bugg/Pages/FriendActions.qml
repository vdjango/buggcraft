pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import Bugg.DesignSystem

// 好友列表与详情共用命令区；业务状态归 MultiplayerService，不复制联机流程。
RowLayout {
    id: root
    property var service: null
    property var status: service ? service.status : ({})
    property var person: ({})
    property string mode: "friends"
    property bool inviteMode: false
    readonly property var joinRequest: (status.joinRequests || []).find(item => !item.incoming && item.account === person.account && item.room === (person.room || {}).id) || ({})
    readonly property string outgoing: (status.outgoingInvitations || {})[person.account] || ""
    readonly property bool pendingInvite: (status.pendingInvites || []).includes(person.account)
    readonly property bool canJoin: !inviteMode && !!(person.room || {}).can_request
    signal noticeRequested(string message)
    ActionButton {
        objectName: "friendPrimary_" + (root.mode === "friends" ? "" : root.mode + "_") + root.person.account
        visible: root.mode !== "requests" || !!root.person.incoming
        text: root.mode === "requests" ? qsTranslate("FriendsPage", "接受") : root.mode === "invitations" ? qsTranslate("FriendsPage", "加入") : root.mode === "joins" ? qsTranslate("FriendsPage", "同意") : root.canJoin ? (root.joinRequest.status === "pending" ? qsTranslate("FriendsPage", "已申请") : qsTranslate("FriendsPage", "申请加入")) : root.pendingInvite ? qsTranslate("FriendsPage", "待邀请") : root.outgoing === "sent" ? qsTranslate("FriendsPage", "已邀请") : qsTranslate("FriendsPage", "邀请")
        compact: true
        variant: "soft"
        enabled: !root.status.socialBusy && (root.mode !== "friends" || (!!root.person.online && !root.pendingInvite && root.outgoing !== "sending" && root.outgoing !== "sent" && !(root.canJoin && root.joinRequest.status === "pending"))) && (root.mode !== "invitations" || (!root.status.room && !root.status.roomBusy))
        onClicked: {
            if (root.mode === "friends") {
                if (root.canJoin)
                    root.service.social("request_join", root.person.account, {
                        room: root.person.room.id
                    });
                else
                    root.service.invite_friend(root.person.account);
            } else
                root.service.social(({
                        requests: "accept",
                        invitations: "join",
                        joins: "accept_join"
                    })[root.mode], root.person.account, Object.assign({
                    ref: root.person.id
                }, root.mode === "joins" ? {
                    room: root.person.room
                } : {}));
        }
    }
    IconButton {
        objectName: "friendMore_" + (root.mode === "friends" ? "" : root.mode + "_") + root.person.account
        iconName: "more"
        accessibleName: qsTranslate("FriendsPage", "好友操作")
        enabled: !root.status.socialBusy
        onClicked: actions.open()
        SelectionMenu {
            id: actions
            x: parent.width - width
            y: parent.height + 4
            available: root.visible && root.status.state === "ready"
            items: root.mode === "friends" ? [
                {
                    id: "invite",
                    name: qsTranslate("FriendsPage", "邀请联机")
                },
                {
                    id: "copy",
                    name: qsTranslate("FriendsPage", "复制好友码")
                }
            ] : []
            actionText: root.mode === "friends" ? qsTranslate("FriendsPage", "删除好友") : root.mode === "invitations" ? qsTranslate("FriendsPage", "忽略邀请") : root.mode === "joins" ? qsTranslate("FriendsPage", "拒绝加入") : root.person.incoming ? qsTranslate("FriendsPage", "拒绝申请") : qsTranslate("FriendsPage", "取消申请")
            onChosen: id => {
                if (id === "invite")
                    root.service.invite_friend(root.person.account);
                else if (root.service.copy_friend_code(root.person.account))
                    root.noticeRequested(qsTranslate("FriendsPage", "已复制好友码"));
            }
            onActionRequested: root.service.social(root.mode === "invitations" ? "ignore" : root.mode === "joins" ? "decline_join" : "remove", root.person.account, root.mode === "joins" ? {
                ref: root.person.id,
                room: root.person.room
            } : {
                ref: root.person.id || ""
            })
        }
    }
}
