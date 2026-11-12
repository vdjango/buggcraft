pragma ComponentBehavior: Bound
import QtQuick
import Bugg.DesignSystem

Item {
    id: root
    required property var instances
    required property int selectedIndex
    property bool spacious: false
    property color backdropTint: "#243D44"
    property real viewportHeight: 500
    property var launchStatus: ({
            state: "idle"
        })
    property var identityStatus: ({})
    property bool canStart: false
    property bool viewActive: true
    property bool loadingInstances: false
    property var room: ({})
    readonly property bool inRoom: !!room.id
    readonly property string launchState: launchStatus.state || "idle"
    readonly property bool showingStatus: launchState !== "idle"
    readonly property var currentInstance: instances[selectedIndex] || null
    signal launchRequested
    signal cancelRequested
    signal stopRequested
    signal openRequested(string route)
    signal identitySelected(string id)
    implicitHeight: spacious ? viewportHeight : (launchState === "failed" ? 112 : 72)

    ListRow {
        objectName: "homeRoomSummary"
        visible: root.inRoom && root.spacious
        x: root.spacious ? 40 : 16
        y: root.spacious ? 12 : 0
        width: root.spacious ? Math.min(parent.width - 80, 520) : parent.width - 32
        compact: true
        faded: root.spacious
        backdropTint: root.backdropTint
        iconName: "people"
        text: root.room.title || ""
        caption: [qsTr("%1 人").arg(root.room.memberCount === undefined ? (root.room.members || []).filter(item => item.online !== false).length : root.room.memberCount), root.room.availability === "ready" ? qsTr("世界已开放") : qsTr("等待世界开放"), ({
                    local: qsTr("本地世界"),
                    p2p: qsTr("直连"),
                    relay: qsTr("中转")
                })[root.room.connectionMode] || qsTr("连接中"), root.room.role !== "host" && root.room.latencyMs >= 0 ? Math.round(root.room.latencyMs) + " ms" : ""].filter(Boolean).join(" · ")
        value: qsTr("返回房间")
        showChevron: false
        hoverFeedbackEnabled: false
        onClicked: root.openRequested("room")
    }

    SummaryButton {
        objectName: "instanceButton"
        opacity: root.showingStatus ? 0 : 1
        visible: opacity > 0
        enabled: !root.showingStatus
        Behavior on opacity {
            NumberAnimation {
                duration: 150
            }
        }
        x: root.spacious ? 40 : 24
        y: root.spacious ? parent.height - height - 48 : 12
        width: root.spacious ? parent.width - 312 : launchButton.x - x - 14
        height: root.spacious ? 112 : 48
        text: root.currentInstance ? root.currentInstance.name : root.loadingInstances ? qsTr("正在加载游戏") : qsTr("选择游戏")
        caption: root.currentInstance ? root.currentInstance.version + " · " + root.currentInstance.loader : root.loadingInstances ? "" : qsTr("尚未安装游戏")
        titleSize: root.spacious ? 30 : 16
        titleWeight: root.spacious ? Font.Normal : Font.DemiBold
        centered: false
        feedbackEnabled: false
        frosted: root.spacious
        backdropTint: root.backdropTint
        iconName: root.spacious ? (root.currentInstance ? root.currentInstance.loader.toLowerCase() : "minecraft") : ""
        Accessible.name: qsTr("切换游戏")
        onClicked: root.openRequested("selectInstance")
    }
    ProfileButton {
        id: accountButton
        objectName: "homeAccountButton"
        opacity: root.spacious && !root.showingStatus ? 1 : 0
        visible: opacity > 0
        enabled: !root.showingStatus
        Behavior on opacity {
            NumberAnimation {
                duration: 150
            }
        }
        x: parent.width - width - 40
        y: launchButton.y - height - 14
        width: launchButton.width
        text: root.identityStatus.name || qsTr("选择账号")
        caption: qsTr(root.identityStatus.caption || "") || qsTr("微软 / 离线身份")
        initials: root.identityStatus.initials || "?"
        menuOpen: profileMenu.opened
        onMenuRequested: {
            if (profileMenu.items.length === 0)
                root.openRequested("identity");
            else if (profileMenu.opened)
                profileMenu.close();
            else
                profileMenu.open();
        }
        onClicked: root.openRequested("identity")
    }
    SelectionMenu {
        id: profileMenu
        objectName: "profileMenu"
        parent: accountButton
        x: accountButton.width - width
        y: -height - 8
        items: root.identityStatus.profiles || []
        available: root.viewActive && root.spacious && !root.showingStatus
        selectedId: root.identityStatus.selectedId || ""
        emptyText: qsTr("暂无已保存的角色")
        actionText: qsTr("管理游戏身份")
        onChosen: id => root.identitySelected(id)
        onActionRequested: root.openRequested("identity")
    }
    Column {
        id: statusColumn
        objectName: "homeLaunchStatus"
        x: root.spacious ? 40 : 24
        y: root.spacious ? parent.height - height - 48 : 14
        width: root.spacious ? parent.width - 312 : launchButton.x - x - 14
        spacing: root.spacious ? 14 : 8
        opacity: root.showingStatus ? 1 : 0
        visible: opacity > 0
        enabled: root.showingStatus
        transform: Translate {
            y: (1 - statusColumn.opacity) * 6
        }
        Behavior on opacity {
            NumberAnimation {
                duration: 180
            }
        }
        UiText {
            visible: root.spacious
            width: parent.width
            text: (root.launchStatus.instanceName || "") + (root.launchStatus.preview ? qsTr(" · 交互预览") : "")
            color: DesignTokens.muted
            font.pixelSize: root.spacious ? 13 : 11
        }
        ProgressItem {
            objectName: "homeLaunchProgress"
            width: parent.width
            title: root.launchStatus.title || ""
            state: root.spacious ? root.launchStatus.stage || "" : ""
            caption: root.spacious || root.launchState === "failed" ? root.launchStatus.detail || "" : ""
            progress: root.launchStatus.progress === undefined ? -1 : root.launchStatus.progress
            showBar: ["initializing", "preparing", "stopping"].includes(root.launchState)
            titleSize: root.spacious ? 30 : 14
            captionSize: root.spacious ? 12 : 11
            titleWeight: Font.Normal
        }
    }
    ActionButton {
        objectName: "launchSecondaryButton"
        visible: root.launchState === "failed" || (root.spacious && root.launchState === "running")
        x: launchButton.x
        y: root.spacious ? launchButton.y - height - 8 : launchButton.y + launchButton.height + 6
        width: launchButton.width
        height: 32
        variant: "ghost"
        text: qsTr("查看日志")
        iconName: "more"
        onClicked: root.openRequested("logs")
    }
    ActionButton {
        id: launchButton
        objectName: "launchButton"
        x: parent.width - width - (root.spacious ? 40 : 24)
        y: root.spacious ? parent.height - height - 40 : root.launchState === "failed" ? 14 : (parent.height - height) / 2
        width: root.spacious ? 192 : 136
        height: root.spacious ? 50 : 40
        compact: !root.spacious
        cornerRadius: root.spacious ? 25 : 8
        text: {
            switch (root.launchState) {
            case "initializing":
                return qsTr("正在初始化…");
            case "preparing":
                return qsTr("取消启动");
            case "running":
                return qsTr("停止游戏");
            case "stopping":
                return qsTr("正在停止…");
            case "failed":
                return qsTr("重新启动");
            default:
                return root.currentInstance ? (root.canStart ? qsTr("启动游戏") : qsTr("选择账号")) : root.loadingInstances ? qsTr("正在加载…") : root.instances.length ? qsTr("选择游戏") : qsTr("安装游戏");
            }
        }
        iconName: root.launchState === "preparing" ? "close" : (root.launchState === "running" || root.launchState === "stopping" ? "stop" : (root.currentInstance ? "play" : "plus"))
        enabled: !["initializing", "stopping"].includes(root.launchState) && !root.loadingInstances
        onClicked: {
            if (root.launchState === "preparing")
                root.cancelRequested();
            else if (root.launchState === "running")
                root.stopRequested();
            else if (root.currentInstance && !root.canStart)
                root.openRequested("identity");
            else if (root.currentInstance)
                root.launchRequested();
            else
                root.openRequested(root.instances.length ? "selectInstance" : "install");
        }
    }
}
