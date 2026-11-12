pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import Bugg.DesignSystem

// 好友业务快照归 C++，搜索/选择归 PageStateStore；通知复用同一列表与命令组件。
PageLayout {
    id: root
    property var service: null
    property var status: service ? service.status : ({})
    property real viewportHeight: 460
    property string queryText: ""
    property string loginOrigin: ""
    property string selectedId: ""
    property bool inviteMode: false
    property bool notificationMode: false
    property bool detailMode: false
    property string notificationCategory: "rooms"
    readonly property bool ready: status.state === "ready"
    readonly property bool split: DesignTokens.comfortable && !inviteMode && !notificationMode && !detailMode
    readonly property string activeCategory: notificationMode ? notificationCategory : (selectedPerson || {}).category || "rooms"
    readonly property var notifications: (status.notifications || []).filter(item => (item.notificationKind === "requests") === (activeCategory === "requests"))
    readonly property var items: notificationMode ? notifications : (status.friends || []).concat(inviteMode ? [] : [
        {
            id: "bugg-notifications",
            account: "bugg-notifications",
            name: qsTr("联机通知"),
            service: true,
            category: "rooms",
            unread: status.roomNotificationCount || 0,
            receivedAt: status.roomNotificationAt || 0
        },
        {
            id: "bugg-friend-requests",
            account: "bugg-friend-requests",
            name: qsTr("好友申请"),
            service: true,
            category: "requests",
            unread: status.friendRequestCount || 0,
            receivedAt: status.friendRequestAt || 0
        }
    ])
    readonly property var filteredItems: items.map((person, index) => ({
                person: person,
                index: index
            })).filter(entry => entry.person.service || ((entry.person.username || entry.person.name || "") + " " + (entry.person.alias || "")).toLowerCase().includes(queryText.trim().toLowerCase())).sort((a, b) => (b.person.receivedAt || 0) - (a.person.receivedAt || 0) || a.index - b.index).map(entry => entry.person)
    readonly property var selectedPerson: (detailMode ? status.friends || [] : filteredItems).find(item => (item.id || item.account) === selectedId) || (!detailMode && !notificationMode ? filteredItems[0] : null)
    readonly property var selectedRoom: selectedPerson ? selectedPerson.room || ({}) : ({})
    readonly property bool viewingNotifications: ready && (notificationMode || split && !!(selectedPerson || {}).service)
    signal openRequested(string route)
    signal edited(string key, var value)
    signal noticeRequested(string message)
    function personCaption(person) {
        if (person.service) {
            const latest = (status.notifications || []).find(item => (item.notificationKind === "requests") === (person.category === "requests"));
            return latest ? (latest.username || latest.name || "") + " · " + personCaption(latest) : qsTr("暂无通知");
        }
        const mode = person.notificationKind || "friends";
        return mode === "requests" ? (person.incoming ? qsTr("请求添加你为好友") : qsTr("等待对方接受")) : mode === "invitations" ? qsTr("邀请你一起联机") : mode === "joins" ? qsTr("申请加入你的房间") : person.online ? ((person.room || {}).title || qsTr("在线")) : qsTr("离线");
    }
    function markVisibleNotificationsRead() {
        if (viewingNotifications && service)
            service.mark_notifications_read(activeCategory);
    }
    onViewingNotificationsChanged: Qt.callLater(markVisibleNotificationsRead)
    onActiveCategoryChanged: Qt.callLater(markVisibleNotificationsRead)
    Connections {
        target: root.service
        function onChanged() {
            Qt.callLater(root.markVisibleNotificationsRead);
        }
    }
    maximumWidth: 1040
    horizontalPadding: DesignTokens.comfortable && ready ? 12 : 20
    centered: !ready
    verticalPadding: 12
    spacing: 12
    Component.onCompleted: {
        if (service && ready)
            service.refresh();
    }
    NodeLogin {
        Layout.alignment: Qt.AlignHCenter
        Layout.fillWidth: true
        Layout.maximumWidth: 360
        visible: !root.ready
        status: root.status
        onLoginRequested: {
            if (root.service)
                root.service.login(root.loginOrigin);
        }
        onSettingsRequested: root.openRequested("multiplayerSettings")
        onLogoutRequested: {
            if (root.service)
                root.service.logout();
        }
    }
    RowLayout {
        Layout.fillWidth: true
        visible: root.ready
        Layout.preferredHeight: root.split || root.detailMode ? Math.max(280, root.viewportHeight - root.verticalPadding * 2 - (root.status.error ? friendNotice.implicitHeight + root.spacing : 0)) : -1
        spacing: root.split ? 12 : 0
        ColumnLayout {
            objectName: "friendSidebar"
            visible: !root.detailMode
            Layout.fillWidth: !root.split
            Layout.fillHeight: root.split
            Layout.preferredWidth: root.split ? 232 : -1
            Layout.alignment: Qt.AlignTop
            spacing: 8
            RowLayout {
                visible: !root.notificationMode
                Layout.fillWidth: true
                spacing: 4
                InputField {
                    objectName: "friendSearchField"
                    Layout.fillWidth: true
                    text: root.queryText
                    placeholderText: qsTr("搜索好友")
                    leadingIcon: "compass"
                    onTextEdited: root.edited("query", text)
                }
                IconButton {
                    objectName: "addFriendButton"
                    visible: !root.inviteMode && !root.notificationMode
                    iconName: "plus"
                    accessibleName: qsTr("添加好友")
                    onClicked: root.openRequested("addFriend")
                }
            }
            ListViewport {
                objectName: "friendsViewport"
                Layout.fillWidth: true
                Layout.fillHeight: root.split
                Layout.preferredHeight: Math.min(DesignTokens.comfortable ? 330 : 276, Math.max(108, count * (DesignTokens.rowHeight + 6) - 6))
                model: root.filteredItems
                delegate: personDelegate
                EmptyState {
                    anchors.centerIn: parent
                    width: Math.min(260, parent.width - 24)
                    visible: parent.count === 0
                    title: root.notificationMode ? qsTr("暂无通知") : root.queryText.length ? qsTr("没有匹配的好友") : qsTr("暂无好友")
                }
            }
            SettingRow {
                objectName: "ownFriendCodeButton"
                visible: !root.inviteMode && !root.notificationMode
                Layout.fillWidth: true
                implicitHeight: 36
                text: qsTr("我的好友码")
                value: root.status.friendCode || "—"
                iconName: "copy"
                onClicked: {
                    if (root.service.copy_friend_code())
                        root.noticeRequested(qsTr("已复制好友码"));
                }
            }
        }
        Divider {
            visible: root.split
            Layout.preferredWidth: 1
            Layout.fillHeight: true
        }
        ColumnLayout {
            objectName: "friendDetails"
            visible: (root.split || root.detailMode) && !!root.selectedPerson
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 12
            RowLayout {
                Layout.fillWidth: true
                spacing: 12
                Avatar {
                    Layout.preferredWidth: 40
                    Layout.preferredHeight: 40
                    initials: (root.selectedPerson || {}).service ? "B" : ((root.selectedPerson || {}).alias || (root.selectedPerson || {}).username || (root.selectedPerson || {}).name || "").slice(0, 1)
                    online: !!(root.selectedPerson || {}).online
                    showStatus: !(root.selectedPerson || {}).service
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 4
                    UiText {
                        objectName: "friendDetailName"
                        Layout.fillWidth: true
                        text: (root.selectedPerson || {}).alias || (root.selectedPerson || {}).username || (root.selectedPerson || {}).name || ""
                        font.pixelSize: 16
                        font.weight: Font.DemiBold
                    }
                    UiText {
                        Layout.fillWidth: true
                        text: root.selectedPerson && !root.viewingNotifications ? root.personCaption(root.selectedPerson) : ""
                        visible: text.length > 0
                        color: DesignTokens.muted
                        font.pixelSize: 12
                    }
                }
                FriendActions {
                    visible: !root.viewingNotifications
                    service: root.service
                    status: root.status
                    person: root.selectedPerson || ({})
                    onNoticeRequested: message => root.noticeRequested(message)
                }
            }
            Divider {
                Layout.fillWidth: true
            }
            ListViewport {
                objectName: "friendNotificationViewport"
                visible: root.viewingNotifications
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumHeight: 120
                model: root.notifications
                delegate: personDelegate
                EmptyState {
                    anchors.centerIn: parent
                    visible: parent.count === 0
                    title: qsTr("暂无通知")
                }
            }
            ListRow {
                visible: !root.viewingNotifications && !!root.selectedRoom.id
                Layout.fillWidth: true
                text: root.selectedRoom.title || qsTranslate("ToolDeck", "房间")
                caption: [(root.selectedRoom.game || {}).version, (root.selectedRoom.game || {}).loader, root.selectedRoom.availability === "ready" ? qsTranslate("ToolDeck", "世界已开放") : qsTranslate("ToolDeck", "等待房主开放世界")].filter(Boolean).join(" · ")
                showChevron: false
                hoverFeedbackEnabled: false
                leadingComponent: Component {
                    WorldMark {}
                }
            }
            RoomChat {
                objectName: "friendConversation"
                visible: !root.viewingNotifications
                Layout.fillWidth: true
                Layout.fillHeight: true
                available: false
                emptyTitle: qsTr("待实现")
                emptyCaption: ""
            }
        }
        Item {
            visible: root.split && !root.selectedPerson
            Layout.fillWidth: true
            Layout.fillHeight: true
        }
    }
    Component {
        id: personDelegate
        ListRow {
            id: friendRow
            required property var modelData
            objectName: "friendRow_" + modelData.account
            width: ListView.view.width
            compact: true
            text: modelData.alias || modelData.username || modelData.name || ""
            caption: root.personCaption(modelData)
            selected: root.split && !!root.selectedPerson && (root.selectedPerson.id || root.selectedPerson.account) === (modelData.id || modelData.account)
            showChevron: false
            showSelectionMark: false
            showTrailing: !modelData.service && (!root.split || !!modelData.notificationKind)
            onClicked: {
                if (modelData.service && !root.split) {
                    root.edited("notificationCategory", modelData.category);
                    root.openRequested("notifications");
                } else if (!modelData.notificationKind) {
                    root.edited("selected", modelData.id || modelData.account);
                    if (!root.split && !modelData.service && !root.inviteMode)
                        root.openRequested("friendConversation");
                }
            }
            leadingComponent: Component {
                Avatar {
                    initials: friendRow.modelData.service ? "B" : friendRow.text.slice(0, 1)
                    online: !!friendRow.modelData.online
                    showStatus: !friendRow.modelData.service && !friendRow.modelData.notificationKind
                    badgeCount: friendRow.modelData.service ? friendRow.modelData.unread : 0
                }
            }
            trailingComponent: Component {
                FriendActions {
                    service: root.service
                    status: root.status
                    person: friendRow.modelData
                    mode: friendRow.modelData.notificationKind || "friends"
                    inviteMode: root.inviteMode
                    onNoticeRequested: message => root.noticeRequested(message)
                }
            }
        }
    }
    NoticeBanner {
        id: friendNotice
        objectName: "friendStatusNotice"
        Layout.fillWidth: true
        visible: root.ready && !!root.status.error
        text: root.status.error || ""
        color: DesignTokens.danger
    }
}
