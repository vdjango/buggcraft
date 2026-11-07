import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

ColumnLayout {
    id: picker
    property var vm: lobby.view
    property var routes: (vm.nodeRoutes || []).filter(function(route) { return route.reachable })
    spacing: 12
    CopyText {
        Layout.fillWidth: true
        text: "登录后和每次启动时自动选择低延迟节点。你也可以手动切换，本次启动期间保留选择。"
        font.pixelSize: 12; color: "#c7bad8"
    }
    RowLayout {
        Layout.fillWidth: true; visible: !!vm.nodeRoutesBusy
        BusyIndicator { implicitWidth: 20; implicitHeight: 20; running: visible }
        CopyText { Layout.fillWidth: true; text: "正在测量节点延迟，请稍候…"; font.pixelSize: 12; color: "#d7c7ed" }
    }
    CopyText {
        objectName: "node-route-error"; Layout.fillWidth: true; visible: !!vm.nodeRouteError
        text: vm.nodeRouteError || ""; font.pixelSize: 12; color: "#ffc2bd"
    }
    ListView {
        id: routeList; objectName: "node-routes-list"
        Layout.fillWidth: true; Layout.fillHeight: true; spacing: 8; clip: true
        model: picker.routes
        ScrollBar.vertical: ScrollBar {}
        delegate: Button {
            id: routeButton
            required property var modelData
            objectName: "select-node-route-" + modelData.index
            width: routeList.width; height: 62; padding: 12
            enabled: !vm.nodeRoutesBusy && vm.connections.length === 0 && modelData.accepting !== false && modelData.remaining_visitors !== 0
            Accessible.name: "切换到 " + (modelData.region || modelData.name)
            onClicked: lobby.act("selectNodeRoute", {index: modelData.index})
            contentItem: RowLayout {
                spacing: 10
                Rectangle { width: 7; height: 7; radius: 4; color: modelData.selected ? "#a9e1c2" : "#89759f" }
                ColumnLayout {
                    Layout.fillWidth: true; spacing: 4
                    CopyText { Layout.fillWidth: true; text: modelData.region || modelData.name; color: "#f0e8ff"; font.bold: true; font.pixelSize: 13; elide: Text.ElideRight; wrapMode: Text.NoWrap }
                    CopyText {
                        Layout.fillWidth: true
                        text: modelData.accepting === false || modelData.remaining_visitors === 0 ? "暂时满载" : modelData.selected ? "当前节点" : "点击切换，无需重新登录"
                        color: modelData.selected ? "#a9e1c2" : "#b9a9ce"; font.pixelSize: 11
                    }
                }
                CopyText { text: typeof modelData.rtt_ms === "number" ? Math.round(modelData.rtt_ms) + " ms" : "—"; color: "#d6c4ee"; font.pixelSize: 13 }
            }
            background: Surface {
                color: !routeButton.enabled ? "#242536" : routeButton.down ? "#463b75" :
                    routeButton.hovered ? "#4a3d62" : modelData.selected ? "#392d4f" : "#251e30"
                border.width: routeButton.activeFocus ? 2 : 1
                border.color: routeButton.activeFocus ? "#d4c9ff" : modelData.selected ? "#a38ad5" : "#625b83"
                Rectangle { x: 2; y: 2; width: parent.width - 4; height: 1; color: "#ffffff"; opacity: routeButton.down ? 0.04 : 0.16 }
            }
            HoverHandler { cursorShape: routeButton.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor }
        }
        CopyText {
            anchors.centerIn: parent; width: parent.width
            visible: !vm.nodeRoutesBusy && picker.routes.length === 0
            text: "暂时没有可用节点，请检查网络后重新测速。"
            font.pixelSize: 12; color: "#b9a9ce"; horizontalAlignment: Text.AlignHCenter
        }
    }
    RowLayout {
        Layout.fillWidth: true; spacing: 8
        ActionButton { objectName: "auto-node-route"; text: "自动选择最快"; primary: true; Layout.fillWidth: true; enabled: !vm.nodeRoutesBusy && vm.connections.length === 0; onClicked: lobby.act("autoNodeRoute", {}) }
        ActionButton { objectName: "refresh-node-routes"; text: "重新测速"; quiet: true; enabled: !vm.nodeRoutesBusy && vm.connections.length === 0; onClicked: lobby.act("refreshNodeRoutes", {}) }
        ActionButton { objectName: "login-another-node"; text: "登录其他节点"; quiet: true; enabled: !vm.nodeRoutesBusy; onClicked: { lobby.act("closeNodePicker", {}); lobby.act("navigate", {page:"nodes"}) } }
    }
}
