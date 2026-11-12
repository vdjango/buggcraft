pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import Bugg.DesignSystem

PageLayout {
    id: root
    property var service: null
    property var runtime: null
    property var tasks: []
    property var instances: []
    property bool embedded: false
    property bool instanceLocked: false
    readonly property var status: service ? service.status : ({})
    readonly property var room: status.room || ({})
    readonly property var roomTasks: tasks.filter(item => item.kind === "room" && item.name === room.syncName)
    readonly property bool syncing: roomTasks.some(item => ["queued", "running", "cancelling"].includes(item.state))
    signal openRequested(string route)
    signal noticeRequested(string message)
    maximumWidth: 720
    verticalPadding: embedded ? 0 : 16
    spacing: 14
    PageHeader {
        visible: !root.embedded
        Layout.fillWidth: true
        title: root.room.title || qsTr("房间游戏")
        caption: [(root.room.game || {}).version, (root.room.game || {}).loader].filter(Boolean).join(" · ")
        titleSize: 18
    }
    SelectField {
        objectName: "roomLocalInstanceField"
        Layout.fillWidth: true
        label: qsTr("本地游戏")
        options: root.instances.map(item => ({
                    id: item.id,
                    name: item.name,
                    caption: item.version + " · " + item.loader
                }))
        selection: root.room.candidateId || root.room.instanceId || ""
        enabled: !root.syncing && !root.instanceLocked
        busy: !!root.room.checking
        onChosen: id => root.service.select_room_instance(id)
    }
    NoticeBanner {
        Layout.fillWidth: true
        text: root.room.checking ? qsTr("正在核对房间配置…") : root.room.compatibility || root.room.loaderWarning || (root.room.instanceId ? qsTr("配置已匹配，可以启动游戏") : qsTr("请选择本地游戏或安装房间配置"))
        color: root.room.instanceId ? DesignTokens.success : DesignTokens.warning
    }
    UiText {
        Layout.fillWidth: true
        visible: !root.syncing && !root.room.instanceId
        text: qsTr("创建独立房间配置，原有游戏和存档不变。")
        font.pixelSize: 12
        wrapMode: Text.Wrap
    }
    RowLayout {
        Layout.fillWidth: true
        visible: !root.syncing && !root.room.instanceId && root.roomTasks.length === 0
        ActionButton {
            objectName: "supplementRoomButton"
            text: qsTr("复用已有配置")
            compact: true
            variant: "soft"
            enabled: !!root.room.canSupplement && !root.room.checking
            onClicked: root.service.sync_room("existing")
        }
        Item {
            Layout.fillWidth: true
        }
        ActionButton {
            objectName: "syncRoomButton"
            text: qsTr("全新安装")
            compact: true
            enabled: !!root.room.id
            onClicked: root.service.sync_room("fresh")
        }
    }
    Repeater {
        model: root.room.instanceId ? [] : root.roomTasks.slice(0, 1)
        TaskCard {
            required property var modelData
            Layout.fillWidth: true
            task: modelData
            onCancelRequested: id => root.runtime.cancel_task(id)
            onRetryRequested: id => root.runtime.retry_task(id)
            onDependencyChoiceRequested: (id, choice) => root.runtime.resolve_dependencies(id, choice)
        }
    }
    NoticeBanner {
        Layout.fillWidth: true
        visible: !!root.status.error
        text: root.status.error || ""
        color: DesignTokens.danger
    }
}
