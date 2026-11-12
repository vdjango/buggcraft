pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import Bugg.DesignSystem

// 房间快照归 C++；导航与操作固定在上方，聊天输入位于聊天视图底部。
PageLayout {
    id: root
    property var service: null
    property var runtime: null
    property var instances: []
    property var tasks: []
    property var status: service ? service.status : ({})
    property var room: status.room || ({})
    property var lobby: room.lobby || ({})
    property var launchStatus: ({
            state: "idle"
        })
    property real viewportHeight: 460
    property string chatDraft: ""
    property string activeView: "chat"
    signal chatEdited(string value)
    signal viewEdited(string value)
    readonly property bool host: room.role === "host"
    readonly property bool preparing: launchStatus.state === "preparing"
    readonly property bool running: launchStatus.state === "running"
    readonly property bool syncing: room.syncState === "queued" || room.syncState === "running"
    readonly property bool needsPreparation: !host && !room.instanceId
    signal launchRequested
    signal cancelRequested
    signal openRequested(string route)
    signal noticeRequested(string message)
    maximumWidth: 1040
    spacing: 0
    verticalPadding: 8
    EmptyState {
        Layout.fillWidth: true
        visible: !root.status.room
        title: qsTr("尚未加入房间")
    }
    ColumnLayout {
        visible: !!root.status.room
        Layout.fillWidth: true
        Layout.preferredHeight: Math.max(330, root.viewportHeight - root.verticalPadding * 2)
        spacing: 12
        UiText {
            Layout.fillWidth: true
            objectName: "roomNodeLatency"
            text: [root.room.nodeName || qsTr("正在确认房间节点"), root.room.nodeLatencyMs >= 0 ? qsTr("到节点 %1 ms").arg(Math.round(root.room.nodeLatencyMs)) : qsTr("到节点待测"), root.host ? qsTr("本机房主") : root.room.latencyMs >= 0 ? qsTr("到房主 %1 ms").arg(Math.round(root.room.latencyMs)) : qsTr("到房主待测")].join(" · ")
            font.pixelSize: 11
            color: DesignTokens.muted
            wrapMode: Text.Wrap
        }
        GridLayout {
            Layout.fillWidth: true
            columns: 2
            rowSpacing: 6
            columnSpacing: 12
            NavigationBar {
                objectName: "roomViews"
                items: [qsTr("聊天"), qsTr("成员") + " · " + (root.room.members || []).filter(item => item.online !== false).length, root.host ? qsTr("缓存") : qsTr("游戏")]
                toolIds: [100, 101, 102]
                itemWidth: DesignTokens.comfortable ? 70 : 32
                itemHeight: DesignTokens.comfortable ? 34 : 30
                iconNames: DesignTokens.comfortable ? [] : ["chat", "people", root.host ? "download" : "minecraft"]
                underline: true
                selectedIndex: root.activeView === "members" ? 101 : root.activeView === "files" ? 102 : 100
                onSelected: index => root.viewEdited(index === 101 ? "members" : index === 102 ? "files" : "chat")
            }
            RowLayout {
                Layout.fillWidth: true
                Layout.alignment: Qt.AlignRight
                Item {
                    Layout.fillWidth: true
                }
                ActionButton {
                    objectName: "copyRoomInviteButton"
                    text: DesignTokens.comfortable ? qsTr("复制邀请") : ""
                    iconName: DesignTokens.comfortable ? "" : "copy"
                    Accessible.name: qsTr("复制邀请")
                    variant: "ghost"
                    compact: true
                    enabled: !!root.room.invite
                    onClicked: {
                        if (root.service.copy_invite())
                            root.noticeRequested(qsTr("已复制邀请"));
                    }
                }
                ActionButton {
                    objectName: "inviteRoomFriendsButton"
                    visible: root.room.isManager || root.host
                    text: DesignTokens.comfortable ? qsTr("邀请好友") : ""
                    iconName: DesignTokens.comfortable ? "" : "people"
                    Accessible.name: qsTr("邀请好友")
                    variant: "ghost"
                    compact: true
                    onClicked: root.openRequested("inviteFriends")
                }
                ActionButton {
                    objectName: "roomLaunchButton"
                    text: root.preparing ? qsTr("取消启动") : root.running ? qsTr("游戏运行中") : root.room.checking ? qsTr("正在核对…") : root.syncing ? qsTr("正在准备…") : root.needsPreparation ? qsTr("同步安装") : qsTr("启动游戏")
                    compact: true
                    enabled: !root.running && !root.room.checking && !root.syncing && root.launchStatus.state !== "stopping"
                    onClicked: root.preparing ? root.cancelRequested() : root.launchRequested()
                }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            visible: !!root.lobby.transfer
            UiText {
                Layout.fillWidth: true
                text: qsTr("房主转让等待确认")
                font.pixelSize: 12
            }
            ActionButton {
                text: (root.lobby.transfer || {}).to === root.lobby.self_id ? qsTr("接受") : qsTr("取消")
                compact: true
                onClicked: root.service.room_command((root.lobby.transfer || {}).to === root.lobby.self_id ? "owner_answer" : "owner_cancel", {
                    offer: (root.lobby.transfer || {}).id,
                    accept: true
                })
            }
        }
        RowLayout {
            Layout.fillWidth: true
            visible: (root.status.pendingInvites || []).length > 0
            UiText {
                Layout.fillWidth: true
                text: qsTr("世界开放后自动邀请 %1 位好友").arg((root.status.pendingInvites || []).length)
                wrapMode: Text.Wrap
                font.pixelSize: 12
            }
            IconButton {
                iconName: "close"
                accessibleName: qsTr("取消待发送邀请")
                onClicked: root.service.cancel_invites()
            }
        }
        ProgressItem {
            Layout.fillWidth: true
            visible: root.preparing
            title: root.launchStatus.title || qsTr("正在启动游戏")
            caption: root.launchStatus.detail || ""
            progress: root.launchStatus.progress === undefined ? -1 : root.launchStatus.progress
        }
        NoticeBanner {
            Layout.fillWidth: true
            visible: !!root.status.error || root.launchStatus.state === "failed"
            text: root.status.error || root.launchStatus.detail || ""
            color: DesignTokens.danger
        }
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 180
            ListViewport {
                objectName: "roomMembersViewport"
                anchors.fill: parent
                visible: root.activeView === "members"
                model: (root.room.members || []).filter(item => item.online !== false)
                delegate: ListRow {
                    id: memberRow
                    required property var modelData
                    width: ListView.view.width
                    compact: true
                    text: modelData.name || qsTr("玩家")
                    caption: [modelData.id === root.lobby.manager_id ? qsTr("房主") : "", ({
                                idle: qsTr("等待准备"),
                                ready: qsTr("已就绪"),
                                playing: qsTr("游戏中"),
                                starting: qsTr("正在启动"),
                                checking: qsTr("检查文件"),
                                downloading: qsTr("正在下载"),
                                installing: qsTr("正在安装"),
                                verifying: qsTr("正在校验"),
                                failed: qsTr("准备失败"),
                                cancelled: qsTr("已取消")
                            })[modelData.state] || qsTr("准备中"), typeof modelData.node_rtt_ms === "number" && modelData.node_rtt_ms >= 0 ? qsTr("到节点 %1 ms").arg(Math.round(modelData.node_rtt_ms)) : qsTr("到节点待测"), modelData.id === root.lobby.provider_id ? qsTr("本机世界") : typeof modelData.host_rtt_ms === "number" && modelData.host_rtt_ms >= 0 ? qsTr("到房主 %1 ms").arg(Math.round(modelData.host_rtt_ms)) : qsTr("到房主待测")].filter(Boolean).join(" · ")
                    showChevron: false
                    value: modelData.total > 0 && !["ready", "playing", "idle"].includes(modelData.state) ? Math.round(modelData.done * 100 / modelData.total) + "%" : ""
                    leadingComponent: Component {
                        Avatar {
                            initials: memberRow.text.slice(0, 1)
                        }
                    }
                    trailingComponent: Component {
                        IconButton {
                            objectName: "roomMemberActions_" + memberRow.modelData.id
                            visible: !!root.room.isManager && memberRow.modelData.id !== root.lobby.self_id
                            iconName: "more"
                            accessibleName: qsTr("成员操作")
                            onClicked: memberActions.open()
                            SelectionMenu {
                                id: memberActions
                                x: parent.width - width
                                y: parent.height
                                items: [
                                    {
                                        id: "owner_offer",
                                        name: qsTr("转让房主")
                                    },
                                    {
                                        id: "member_kick",
                                        name: qsTr("移出房间")
                                    }
                                ].filter(item => item.id !== "member_kick" || memberRow.modelData.id !== root.lobby.provider_id)
                                onChosen: id => root.service.room_command(id, {
                                        member: memberRow.modelData.id
                                    })
                            }
                        }
                    }
                }
                EmptyState {
                    anchors.centerIn: parent
                    visible: parent.count === 0
                    title: qsTr("正在获取成员…")
                }
            }
            RoomChat {
                anchors.fill: parent
                visible: root.activeView === "chat"
                service: root.service
                draft: root.chatDraft
                onEdited: value => root.chatEdited(value)
            }
            RoomSyncPage {
                instanceLocked: !["idle", "failed"].includes(root.launchStatus.state)
                anchors.fill: parent
                visible: root.activeView === "files" && !root.host
                embedded: true
                service: root.service
                runtime: root.runtime
                instances: root.instances
                tasks: root.tasks
                onOpenRequested: route => root.viewEdited("chat")
            }
            ColumnLayout {
                anchors.top: parent.top
                anchors.left: parent.left
                anchors.right: parent.right
                visible: root.activeView === "files" && root.host
                spacing: 16
                ProgressItem {
                    objectName: "roomCacheProgress"
                    Layout.fillWidth: true
                    visible: !!root.room.allowSharing && !!root.status.cacheProgress
                    title: qsTr("加速缓存")
                    state: (root.status.cacheProgress || {}).label || ""
                    showBar: !!(root.status.cacheProgress || {}).active
                    caption: (root.status.cacheProgress || {}).detail || ""
                    captionSize: 12
                    progress: (root.status.cacheProgress || {}).progress === undefined ? -1 : root.status.cacheProgress.progress
                }
                SettingRow {
                    Layout.fillWidth: true
                    visible: !root.room.allowSharing
                    text: qsTr("加速缓存未开启")
                    value: qsTr("房间设置")
                    onClicked: root.openRequested("roomSettings")
                }
                SelectField {
                    objectName: "lobbyWorldField"
                    visible: root.room.availability !== "ready" && (root.status.worlds || []).length > 1
                    Layout.fillWidth: true
                    label: qsTr("选择要开放的世界")
                    options: (root.status.worlds || []).map(world => ({
                                id: String(world.port),
                                name: world.motd || qsTr("游戏世界"),
                                caption: world.version
                            }))
                    enabled: !root.status.worldBusy
                    onChosen: id => root.service.connect_world(Number(id))
                }
            }
        }
    }
}
