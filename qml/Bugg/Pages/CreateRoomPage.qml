pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import Bugg.DesignSystem

// 表单草稿由 ToolDeck/PageStateStore 持有，建房与世界发现由 MultiplayerService 持有。
PageLayout {
    id: root
    property var service: null
    property var status: service ? service.status : ({})
    property var instances: []
    property int selectedIndex: -1
    property var draft: ({})
    property bool instanceLocked: false
    readonly property var instance: instances[selectedIndex] || ({})
    readonly property bool busy: !!status.roomBusy
    readonly property var worlds: status.worlds || []
    readonly property string selectedWorldPort: worlds.some(world => String(world.port) === String(draft.port)) ? String(draft.port) : (worlds.length === 1 ? String(worlds[0].port) : "")
    readonly property string roomVisibility: draft.visibility || "invite"
    signal selected(int index)
    signal edited(string key, var value)
    signal createRequested(string title, var options)
    signal openRequested(string route)
    maximumWidth: 680
    spacing: DesignTokens.comfortable ? 12 : 14
    verticalPadding: 16
    Component.onCompleted: {
        if (root.draft.existingWorld && root.service)
            root.service.discover_worlds();
    }
    SelectField {
        objectName: "roomInstanceField"
        Layout.fillWidth: true
        label: qsTr("游戏")
        options: root.instances.map(item => ({
                    id: item.id,
                    name: item.name,
                    caption: item.version + " · " + item.loader
                }))
        selection: root.instance.id || ""
        placeholderText: qsTr("请先安装游戏")
        enabled: !root.busy && !root.instanceLocked
        onChosen: id => root.selected(root.instances.findIndex(item => item.id === id))
    }
    ActionButton {
        visible: root.instances.length === 0
        text: qsTr("安装游戏")
        variant: "soft"
        onClicked: root.openRequested("install")
    }
    FormField {
        objectName: "roomTitleField"
        Layout.fillWidth: true
        label: qsTr("房间名称")
        text: root.draft.title === undefined ? (root.status.username || qsTr("玩家")) + qsTr("的房间") : root.draft.title
        enabled: !root.busy
        onTextEdited: value => root.edited("title", value)
    }
    SelectField {
        objectName: "roomVisibilityField"
        Layout.fillWidth: true
        label: qsTr("可见范围")
        options: [
            {
                id: "private",
                name: qsTr("仅邀请")
            },
            {
                id: "public",
                name: qsTr("公开")
            },
            {
                id: "invite",
                name: qsTr("公开 · 需要邀请")
            }
        ]
        selection: root.roomVisibility
        enabled: !root.busy
        onChosen: id => root.edited("visibility", id)
    }
    CheckOption {
        objectName: "roomCacheAccelerationOption"
        text: qsTr("加速缓存")
        checked: !!root.draft.cacheAcceleration
        enabled: !root.busy
        onToggled: root.edited("cacheAcceleration", checked)
    }
    CheckOption {
        objectName: "roomExistingWorldOption"
        text: qsTr("关联已开放的世界")
        checked: !!root.draft.existingWorld
        enabled: !root.busy
        onToggled: {
            root.edited("existingWorld", checked);
            if (checked && root.service)
                root.service.discover_worlds();
        }
    }
    RowLayout {
        visible: !!root.draft.existingWorld
        Layout.fillWidth: true
        SelectField {
            objectName: "roomWorldField"
            Layout.fillWidth: true
            label: qsTr("局域网世界")
            options: root.worlds.map(world => ({
                        id: String(world.port),
                        name: world.motd || qsTr("游戏世界"),
                        caption: world.version || ""
                    }))
            selection: root.selectedWorldPort
            placeholderText: root.status.worldsLoading ? qsTr("正在查找…") : (root.worlds.length > 1 ? qsTr("请选择要关联的世界") : qsTr("请在游戏中对局域网开放"))
            busy: !!root.status.worldsLoading
            enabled: !root.busy && !root.status.worldsLoading
            onChosen: id => root.edited("port", id)
        }
        IconButton {
            Layout.alignment: Qt.AlignBottom
            iconName: "refresh"
            accessibleName: qsTr("查找世界")
            enabled: !root.status.worldsLoading && !root.busy
            onClicked: root.service.discover_worlds()
        }
    }
    UiText {
        Layout.fillWidth: true
        visible: !root.draft.existingWorld
        text: qsTr("创建后启动游戏，再将世界对局域网开放。")
        wrapMode: Text.Wrap
        color: DesignTokens.muted
        font.pixelSize: 12
    }
    NoticeBanner {
        Layout.fillWidth: true
        visible: !!root.status.error
        text: root.status.error || ""
        color: DesignTokens.danger
    }
    ActionButton {
        objectName: "confirmCreateRoomButton"
        Layout.alignment: Qt.AlignRight
        text: root.busy ? qsTr("正在创建…") : qsTr("创建房间")
        enabled: root.status.state === "ready" && !root.busy && !!root.instance.id && (!root.draft.existingWorld || (!root.status.worldsLoading && !!root.selectedWorldPort))
        onClicked: {
            root.createRequested(root.draft.title === undefined ? (root.status.username || qsTr("玩家")) + qsTr("的房间") : root.draft.title, {
                "public": root.roomVisibility !== "private",
                requireInvite: root.roomVisibility !== "public",
                cacheAcceleration: !!root.draft.cacheAcceleration,
                port: root.draft.existingWorld ? Number(root.selectedWorldPort) : 0
            });
        }
    }
}
