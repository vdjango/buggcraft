import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

ColumnLayout {
    id: root
    property var vm: lobby.view
    property int tab: vm.friendTab || 0
    property string filter: "all"
    property var selectedFriend: ({})
    property var inviteTarget: ({})
    readonly property bool hasReadyHost: (vm.connections || []).some(function(c) { return c.role === "host" && c.state === "online" && (!c.availability || c.availability === "ready") })
    readonly property bool hasWaitingHost: (vm.connections || []).some(function(c) { return c.role === "host" && ["online", "connecting", "reconnecting"].includes(c.state) })
    readonly property int onlineCount: (vm.contacts || []).filter(function(c) { return !!c.online }).length
    readonly property int incomingCount: (vm.friendRequests || []).filter(function(c) { return !!c.incoming }).length
    readonly property var items: {
        var source = tab === 0 ? (vm.contacts || []) : tab === 1 ? (vm.friendRequests || []) : tab === 2 ? (vm.friendInvitations || []) : (vm.joinRequests || []).filter(function(r) { return r.incoming && r.status === "pending" })
        var query = search.text.trim().toLocaleLowerCase()
        return source.filter(function(c) {
            var name = (c.name || c.username || "") + " " + (c.alias || "")
            return (!query || name.toLocaleLowerCase().includes(query)) &&
                (tab !== 0 || filter === "all" || (filter === "online" ? !!c.online : !!c.favorite))
        }).slice().sort(function(a, b) {
            if (tab === 0) {
                if (!!a.online !== !!b.online) return a.online ? -1 : 1
                if (!!a.favorite !== !!b.favorite) return a.favorite ? -1 : 1
            } else if (tab === 1 && !!a.incoming !== !!b.incoming) return a.incoming ? -1 : 1
            return (a.alias || a.name || a.username || "").localeCompare(b.alias || b.name || b.username || "")
        })
    }
    spacing: 10
    function markCurrentTabRead() {
        if (!vm.friendWindowActive || !vm.socialReady) return
        var kind = root.tab === 1 ? "requests" : root.tab === 2 ? "invitations" : root.tab === 3 ? "joinRequests" : ""
        if (kind && ((vm.friendNotifications || {})[kind] || 0) > 0)
            lobby.act("readFriendNotifications", {kind:kind})
    }
    onTabChanged: Qt.callLater(markCurrentTabRead)
    function handleAction(name, data) {
        if (name === "manageFriend") {
            selectedFriend = data
            moreMenu.open()
        } else if (name === "editAlias") {
            selectedFriend = data
            aliasInput.text = data.alias || ""
            aliasPopup.open()
        } else if (name === "confirmRemove") {
            selectedFriend = data
            removePopup.open()
        } else if (name === "inviteFriend" && !hasReadyHost && !vm.pendingFriendInvite) {
            inviteTarget = (vm.contacts || []).find(function(c) { return c.account === data.account }) || data
            invitePopup.open()
        } else lobby.act(name, data)
    }
    Connections {
        target: lobby; ignoreUnknownSignals: true
        function onShowInvitations() { root.tab = 2; search.clear() }
        function onChanged() { Qt.callLater(root.markCurrentTabRead) }
    }
    RowLayout {
        Layout.fillWidth: true; spacing: 12
        FriendAvatar { name: vm.socialName || "我"; online: !!vm.socialReady && vm.socialState !== "stale"; Layout.preferredWidth: 38; Layout.preferredHeight: 38 }
        ColumnLayout {
            Layout.fillWidth: true; spacing: 3
            CopyText {
                objectName: "friend-access-mode"; Layout.fillWidth: true
                text: vm.nodeAccessExpired ? "登录已失效" : vm.socialLoading ? "正在连接好友服务…" : vm.socialReady ? vm.socialName : vm.friendEntryAvailable ? "好友服务未连接" : "匿名接入"
                font.pixelSize: 14; font.bold: true; color: "#e9e1f2"; wrapMode: Text.NoWrap; elide: Text.ElideRight
            }
            CopyText { Layout.fillWidth: true; text: vm.socialReady ? "好友码 " + vm.socialFriendCode : "连接账号后，和朋友一起玩"; font.pixelSize: 11; color: "#a99bb6"; elide: Text.ElideRight }
        }
        HeaderAction { objectName: "copy-social-name"; iconName: "copy"; label: "复制我的好友码"; visible: !!vm.socialReady; onClicked: lobby.act("copySocialName", {}) }
        HeaderAction { objectName: "refresh-friends"; iconName: "refresh"; label: "刷新好友"; visible: !!vm.socialReady; enabled: !vm.friendBusy; onClicked: lobby.act("refreshFriends", {}) }
        ActionButton { objectName: "add-friend"; text: "添加好友"; visible: !!vm.socialReady; primary: true; implicitHeight: 32; onClicked: lobby.act("navigate", {page:"friendForm"}) }
    }
    Surface {
        objectName: "my-network-profile"; visible: true
        Layout.fillWidth: true; implicitHeight: 50; color: "#24202c"; border.color: "#51445d"
        RowLayout {
            anchors.fill: parent; anchors.margins: 8; spacing: 7
            ColumnLayout {
                Layout.fillWidth: true; spacing: 3
                CopyText {
                    objectName: "my-network-type"; Layout.fillWidth: true
                    text: "你的网络类型：" + (!vm.playerNetworkTypeReady ? "正在判断…" : (vm.playerNetworkProfile || {}).type === "direct_easier" ? "较容易直连" : (vm.playerNetworkProfile || {}).type === "relay_likely" ? "可能需要中转" : "暂时无法判断")
                    font.pixelSize: 12; font.bold: true; color: "#e6dced"; elide: Text.ElideRight
                }
                CopyText {
                    objectName: "my-network-history"; Layout.fillWidth: true
                    text: !vm.playerNetworkProfileReady ? "正在读取近 7 天的联机记录…" : "近 7 天总记录：直连成功 " + ((vm.playerNetworkProfile || {}).direct_successes || 0) + " 次 · 中转成功 " + ((vm.playerNetworkProfile || {}).relay_successes || 0) + " 次"
                    font.pixelSize: 10; color: "#b7aabd"; elide: Text.ElideRight
                }
            }
            HeaderAction {
                objectName: "network-profile-help"; text: "?"; iconSize: 13
                label: "网络类型是按当前网络情况给出的参考，不能保证和每位好友都能直接连接；还要看好友当时的网络和本次连接。失败时会自动尝试中转。同步的只有网络类型和近 7 天成功次数，不包含网络地址。次数是与所有玩家的总记录，不代表和某位好友单独联机的次数。"
            }
        }
    }
    Surface {
        objectName: "friends-stale-state"; visible: !!vm.socialReady && vm.socialState === "stale"
        Layout.fillWidth: true; implicitHeight: 54; color: "#3b2b25"; border.color: "#a9764d"
        RowLayout {
            anchors.fill: parent; anchors.margins: 10; spacing: 8
            CopyText { Layout.fillWidth: true; text: (vm.socialError || "好友节点暂时不可达") + "\n显示上次同步的联系人，在线状态未知。"; color: "#ffd7b0"; font.pixelSize: 11; wrapMode: Text.Wrap; verticalAlignment: Text.AlignVCenter }
            ActionButton { objectName: "friends-stale-recovery"; text: vm.nodeCredentialRequired ? "重新登录" : "重试连接"; implicitHeight: 30; onClicked: lobby.act(vm.nodeCredentialRequired ? "reloginNode" : "refreshFriends", {}) }
        }
    }
    Surface {
        objectName: "friends-sign-in"; visible: !vm.socialReady
        Layout.fillWidth: true; Layout.fillHeight: true; color: "#201b29"; border.color: "#43364f"
        ColumnLayout {
            anchors.centerIn: parent; width: Math.min(parent.width - 40, 340); spacing: 14
            FriendAvatar { Layout.alignment: Qt.AlignHCenter; name: "友"; showStatus: false; Layout.preferredWidth: 56; Layout.preferredHeight: 56 }
            CopyText { Layout.fillWidth: true; text: vm.socialLoading ? "正在连接你的好友" : vm.nodeAccessExpired ? "重新连接，继续和朋友玩" : "和朋友一起探索"; horizontalAlignment: Text.AlignHCenter; font.pixelSize: 16; font.bold: true; color: "#e9dff3" }
            CopyText {
                Layout.fillWidth: true; text: vm.socialError || (vm.socialLoading ? "请稍候，好友列表会自动更新。" : "填写节点地址并登录账号，即可查看好友和发送联机邀请。")
                font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.Wrap
            }
            ActionButton { objectName: "friends-replace-node-code"; Layout.alignment: Qt.AlignHCenter; text: (vm.nodeAccessExpired || vm.nodeCredentialRequired) ? "重新登录" : vm.friendEntryAvailable ? "重试连接" : "连接好友服务"; primary: true; visible: !vm.socialLoading; onClicked: lobby.act(vm.friendEntryAvailable && !vm.nodeAccessExpired && !vm.nodeCredentialRequired ? "refreshFriends" : "reloginNode", {}) }
        }
    }
    FriendInviteProgress {
        objectName: "pending-friend-invite-banner"; flow: vm.friendInviteFlow || ({})
        onAction: function(name, data) { root.handleAction(name, data) }
    }
    Surface {
        objectName: "friend-invite-banner"; visible: !!vm.socialReady && root.tab !== 2 && (vm.friendInvitations || []).length > 0
        Layout.fillWidth: true; implicitHeight: 44; color: "#302442"; border.color: "#8061b1"
        RowLayout {
            anchors.fill: parent; anchors.margins: 8; spacing: 8
            CopyText { Layout.fillWidth: true; text: vm.friendInvitations.length === 1 ? (vm.friendInvitations[0].username + " 邀请你一起玩") : "收到 " + vm.friendInvitations.length + " 个联机邀请"; font.pixelSize: 12; color: "#ecdcff"; elide: Text.ElideRight }
            ActionButton { objectName: "show-friend-invites"; text: "查看邀请"; primary: true; implicitHeight: 28; onClicked: { root.tab = 2; search.clear() } }
        }
    }
    RowLayout {
        visible: !!vm.socialReady; Layout.fillWidth: true; spacing: 4
        FriendTab { objectName: "friends-tab-0"; text: "好友"; count: (vm.contacts || []).length; selected: root.tab === 0; onClicked: { root.tab = 0; search.clear() } }
        FriendTab { objectName: "friends-tab-1"; text: "好友申请"; count: root.incomingCount; attention: ((vm.friendNotifications || {}).requests || 0) > 0; selected: root.tab === 1; onClicked: { root.tab = 1; search.clear() } }
        FriendTab { objectName: "friends-tab-2"; text: "联机邀请"; count: (vm.friendInvitations || []).length; attention: ((vm.friendNotifications || {}).invitations || 0) > 0; urgent: true; selected: root.tab === 2; onClicked: { root.tab = 2; search.clear() } }
        FriendTab { objectName: "friends-tab-3"; text: "加入申请"; count: (vm.joinRequests || []).filter(function(r) { return r.incoming && r.status === "pending" }).length; attention: ((vm.friendNotifications || {}).joinRequests || 0) > 0; urgent: true; selected: root.tab === 3; onClicked: { root.tab = 3; search.clear() } }
        Item { Layout.fillWidth: true }
    }
    RowLayout {
        visible: !!vm.socialReady; Layout.fillWidth: true; spacing: 6
        InputField {
            id: search; objectName: "friend-search"; Layout.fillWidth: true; Layout.minimumWidth: 100; implicitHeight: 32; maximumLength: 64
            placeholderText: root.tab === 0 ? "搜索好友或备注" : "搜索用户名"
            Accessible.name: placeholderText
            rightPadding: 28
            HeaderAction { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; width: 28; height: 28; text: "×"; label: "清空搜索"; visible: search.text.length > 0; onClicked: search.clear() }
        }
        Repeater {
            model: [{key:"all",title:"全部"}, {key:"online",title:"在线"}, {key:"favorite",title:"收藏"}]
            ActionButton {
                required property var modelData
                objectName: "friend-filter-" + modelData.key; visible: root.tab === 0
                text: modelData.title; primary: root.filter === modelData.key; quiet: true; implicitHeight: 30; implicitWidth: 48
                onClicked: root.filter = modelData.key
            }
        }
    }
    Rectangle {
        visible: !!vm.socialReady; Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumHeight: 130
        color: "#201b29"; border.color: "#43374e"
        ListView {
            id: list; objectName: "friends-list"; anchors.fill: parent; anchors.margins: 1
            clip: true; model: root.items; spacing: 0; boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar {}
            delegate: FriendRow {
                required property var modelData
                width: list.width - 8; person: modelData; mode: root.tab; busy: !!vm.friendBusy
                inviteBlocked: !!vm.socialMutationBusy
                canRequestJoin: !!(vm.socialCapabilities || {}).join_requests
                joinRequest: (vm.joinRequests || []).find(function(r) { return !r.incoming && r.account === modelData.account && r.room === ((modelData.room || {}).id || "") }) || null
                receivedInvite: (vm.friendInvitations || []).find(function(r) { return r.account === modelData.account && r.room === ((modelData.room || {}).id || "") }) || null
                inviteState: vm.outgoingInvitations ? vm.outgoingInvitations[modelData.account] || null : null
                joining: vm.joiningFriendAccount === modelData.account
                onAction: function(name, data) { root.handleAction(name, data) }
            }
        }
        ColumnLayout {
            objectName: "friends-empty"; anchors.centerIn: parent; width: parent.width - 40
            visible: list.count === 0; spacing: 10
            FriendAvatar { name: root.tab === 0 ? "友" : root.tab === 1 ? "申" : "邀"; showStatus: false; Layout.preferredWidth: 46; Layout.preferredHeight: 46; Layout.alignment: Qt.AlignHCenter }
            CopyText {
                Layout.fillWidth: true; horizontalAlignment: Text.AlignHCenter; color: "#e0d5ea"; font.pixelSize: 14; font.bold: true
                text: search.text.trim() ? "没有找到匹配的好友" : root.tab === 0 ? root.filter === "online" ? "好友暂时都不在线" : root.filter === "favorite" ? "收藏常一起玩的朋友" : "从第一位好友开始" : root.tab === 1 ? "暂时没有好友申请" : root.tab === 2 ? "暂时没有联机邀请" : "暂时没有加入申请"
            }
            CopyText {
                Layout.fillWidth: true; horizontalAlignment: Text.AlignHCenter; font.pixelSize: 11; wrapMode: Text.Wrap
                text: search.text.trim() ? "试试用户名或你设置的备注。" : root.tab === 0 ? root.filter === "favorite" ? "在好友右侧的菜单中添加收藏。" : root.filter === "online" ? "切换“全部”仍可管理好友。" : "添加对方用户名，通过后就能邀请联机。" : root.tab === 1 ? "收到和发出的申请都会显示在这里。" : root.tab === 2 ? "好友邀请你时，这里会出现加入入口。" : "朋友申请进入你的房间后，在这里同意即可。"
            }
            ActionButton { objectName: "empty-add-friend"; visible: root.tab === 0 && root.filter === "all" && !search.text.trim(); Layout.alignment: Qt.AlignHCenter; text: "添加好友"; primary: true; implicitHeight: 30; onClicked: lobby.act("navigate", {page:"friendForm"}) }
        }
    }
    CopyText { Layout.fillWidth: true; visible: !!vm.socialReady && !!vm.socialError; text: vm.socialError || ""; color: "#ffbcb6"; font.pixelSize: 11; wrapMode: Text.Wrap }
    Menu {
        id: moreMenu; objectName: "friend-actions-menu"
        parent: Overlay.overlay; popupType: Popup.Item; width: 160
        x: Math.max(8, Math.min((root.selectedFriend.anchorX || parent.width) - width, parent.width - width - 8))
        y: Math.max(8, Math.min((root.selectedFriend.anchorY || 80) + 4, parent.height - height - 8))
        padding: 5
        background: Rectangle { color: "#282130"; border.color: "#9274b1"; border.width: 1 }
        delegate: FriendMenuItem {}
        FriendMenuItem { objectName: "friend-toggle-favorite"; text: root.selectedFriend.favorite ? "取消收藏" : "收藏好友"; onTriggered: lobby.act("setFriendFavorite", {account:root.selectedFriend.account, favorite:!root.selectedFriend.favorite}) }
        FriendMenuItem { objectName: "friend-edit-alias"; text: "设置备注"; onTriggered: root.handleAction("editAlias", root.selectedFriend) }
        FriendMenuItem { objectName: "friend-copy-name"; text: "复制好友码"; onTriggered: lobby.act("copyFriendName", {account:root.selectedFriend.account}) }
        MenuSeparator { padding: 4; contentItem: Rectangle { implicitHeight: 1; color: "#594365" } }
        FriendMenuItem { objectName: "friend-remove"; destructive: true; text: "移除好友…"; onTriggered: root.handleAction("confirmRemove", root.selectedFriend) }
    }
    Popup {
        id: invitePopup; objectName: "friend-invite-preflight"; parent: Overlay.overlay; anchors.centerIn: parent
        width: Math.min(400, parent.width - 32); padding: 18; modal: true; focus: true
        background: Surface { color: "#251e30"; border.color: "#9477ba" }
        contentItem: ColumnLayout {
            spacing: 14
            RowLayout {
                Layout.fillWidth: true; spacing: 12
                FriendAvatar { name: root.inviteTarget.name || "好友"; online: !!root.inviteTarget.online; Layout.preferredWidth: 38; Layout.preferredHeight: 38 }
                ColumnLayout {
                    Layout.fillWidth: true; spacing: 4
                    CopyText { Layout.fillWidth: true; text: "邀请 " + (root.inviteTarget.alias || root.inviteTarget.name || "好友") + " 一起玩"; font.pixelSize: 15; font.bold: true; color: "#f1e7fb"; wrapMode: Text.Wrap }
                    CopyText { Layout.fillWidth: true; text: root.hasWaitingHost ? "房间还未就绪，邀请暂未发送" : "你还没有可加入的房间"; font.pixelSize: 12; color: "#cab8df"; wrapMode: Text.Wrap }
                }
            }
            Surface {
                Layout.fillWidth: true; implicitHeight: inviteSteps.implicitHeight + 24; color: "#30263e"; border.color: "#51405f"
                ColumnLayout {
                    id: inviteSteps; anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 12; spacing: 10
                    CopyText { Layout.fillWidth: true; text: root.hasWaitingHost ? "① 在游戏中开放世界" : "① 选择世界并创建房间"; font.pixelSize: 12; color: "#e8dcf5"; wrapMode: Text.Wrap }
                    CopyText { Layout.fillWidth: true; text: "② 房间就绪后，自动向好友发送邀请"; font.pixelSize: 12; color: "#e8dcf5"; wrapMode: Text.Wrap }
                    CopyText { Layout.fillWidth: true; text: "③ 好友点「加入联机」即可连接"; font.pixelSize: 12; color: "#e8dcf5"; wrapMode: Text.Wrap }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                ActionButton { objectName: "cancel-friend-invite-preflight"; text: "暂不邀请"; quiet: true; onClicked: invitePopup.close() }
                Item { Layout.fillWidth: true }
                ActionButton {
                    objectName: "confirm-friend-invite-preflight"; text: root.hasWaitingHost ? "去开放并邀请" : "去创建并邀请"; primary: true; enabled: !vm.socialMutationBusy
                    onClicked: { lobby.act("inviteFriend", {account:root.inviteTarget.account}); if (!lobby.view.error) invitePopup.close() }
                }
            }
        }
    }
    Popup {
        id: aliasPopup; objectName: "friend-alias-dialog"; parent: Overlay.overlay; anchors.centerIn: parent
        width: Math.min(360, parent.width - 40); padding: 18; modal: true; focus: true
        background: Surface { color: "#251e30"; border.color: "#82689c" }
        contentItem: ColumnLayout {
            spacing: 12
            CopyText { text: "设置好友备注"; font.pixelSize: 16; font.bold: true; color: "#eee4f7" }
            CopyText { Layout.fillWidth: true; text: root.selectedFriend.name || root.selectedFriend.username || ""; font.pixelSize: 12 }
            InputField { id: aliasInput; objectName: "friend-alias-input"; Layout.fillWidth: true; maximumLength: 32; placeholderText: "给朋友起个好记的名字"; onAccepted: aliasSave.clicked() }
            CopyText { text: "仅你可见，留空恢复用户名。"; font.pixelSize: 11 }
            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                ActionButton { text: "取消"; onClicked: aliasPopup.close() }
                ActionButton { id: aliasSave; objectName: "save-friend-alias"; text: "保存"; primary: true; onClicked: { lobby.act("setFriendAlias", {account:root.selectedFriend.account,alias:aliasInput.text}); if (!lobby.view.error) aliasPopup.close() } }
            }
        }
    }
    Popup {
        id: removePopup; objectName: "friend-remove-dialog"; parent: Overlay.overlay; anchors.centerIn: parent
        width: Math.min(360, parent.width - 40); padding: 18; modal: true; focus: true
        background: Surface { color: "#251e30"; border.color: "#82689c" }
        contentItem: ColumnLayout {
            spacing: 12
            CopyText { text: "移除这位好友？"; font.pixelSize: 16; font.bold: true; color: "#eee4f7" }
            CopyText { Layout.fillWidth: true; text: "移除 " + (root.selectedFriend.alias || root.selectedFriend.name || root.selectedFriend.username || "") + " 后，需要重新申请才能邀请联机。"; wrapMode: Text.Wrap; font.pixelSize: 12 }
            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                ActionButton { objectName: "cancel-remove-friend"; text: "保留好友"; onClicked: removePopup.close() }
                ActionButton { objectName: "confirm-remove-friend"; text: "移除好友"; danger: true; enabled: !vm.friendBusy; onClicked: { lobby.act("removeFriend", {account:root.selectedFriend.account}); if (!lobby.view.error) removePopup.close() } }
            }
        }
    }
}
