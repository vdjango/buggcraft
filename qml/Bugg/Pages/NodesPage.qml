pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import Bugg.DesignSystem

PageLayout {
    id: root
    property var service: null
    readonly property var status: service ? service.status : ({})
    signal noticeRequested(string message)
    Component.onCompleted: if (service)
        service.refresh_nodes()
    UiText {
        Layout.fillWidth: true
        text: qsTr("自动选择会结合连接耗时与节点容量。手动选择仅影响下次建房；加入房间时跟随房主节点，不中断当前游戏。")
        color: DesignTokens.muted
        font.pixelSize: DesignTokens.comfortable ? 13 : 11
        wrapMode: Text.Wrap
        elide: Text.ElideNone
    }
    ActionButton {
        Layout.fillWidth: true
        text: root.status.nodesBusy ? qsTr("正在测量…") : qsTr("刷新节点与延迟")
        enabled: root.status.state === "ready" && !root.status.nodesBusy
        compact: true
        onClicked: root.service.refresh_nodes()
    }
    UiText {
        Layout.fillWidth: true
        visible: root.status.state !== "ready" || !!root.status.nodesError
        text: root.status.nodesError || qsTr("登录联机账号后获取可用节点")
        wrapMode: Text.Wrap
        color: DesignTokens.muted
    }
    ListRow {
        Layout.fillWidth: true
        text: qsTr("自动选择")
        caption: qsTr("根据当前网络与节点容量分配")
        selected: root.status.autoNode === true
        enabled: root.status.state === "ready" && !root.status.nodesBusy
        onClicked: root.service.select_node(-1)
    }
    Repeater {
        model: root.status.routes || []
        ListRow {
            required property var modelData
            Layout.fillWidth: true
            text: modelData.name || modelData.region || qsTr("联机节点")
            caption: modelData.reachable ? qsTr("到节点连接耗时 · %1 ms").arg(Math.round(modelData.rtt_ms)) : qsTr("当前不可达")
            iconName: "server"
            selected: modelData.selected === true
            enabled: !root.status.nodesBusy && modelData.reachable === true
            onClicked: root.service.select_node(modelData.index)
        }
    }
}
