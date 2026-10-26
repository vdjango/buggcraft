import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

ColumnLayout {
    id: nodesPage
    property var vm: lobby.view
    property bool removing: false
    property bool advanced: false
    spacing: 12
    Connections {
        target: lobby
        ignoreUnknownSignals: true
        function onChanged() { nodesPage.removing = false }
    }
    RowLayout {
        Layout.fillWidth: true; Layout.fillHeight: true; spacing: 12
        Surface {
            Layout.preferredWidth: 248; Layout.fillHeight: true
            ColumnLayout {
                anchors.fill: parent; anchors.margins: 12; spacing: 10
                RowLayout {
                    Layout.fillWidth: true
                    CopyText { text: "已添加的节点"; font.pixelSize: 13; font.bold: true; color: "#eee8fa" }
                    Item { Layout.fillWidth: true }
                    CopyText { text: vm.nodes.length; font.pixelSize: 11; color: "#aa9bbc" }
                }
                ListView {
                    id: list; objectName: "nodes-list"
                    Layout.fillWidth: true; Layout.fillHeight: true
                    model: vm.nodes; spacing: 6; clip: true
                    ScrollBar.vertical: ScrollBar {}
                    delegate: Button {
                        required property var modelData
                        required property int index
                        objectName: "choose-node-" + index
                        width: list.width; height: 68; padding: 10
                        Accessible.name: "使用节点 " + modelData.title
                        contentItem: ColumnLayout {
                            spacing: 5
                            CopyText { Layout.fillWidth: true; text: modelData.title; color: "#eee8fa"; font.pixelSize: 12; elide: Text.ElideMiddle; wrapMode: Text.NoWrap }
                            CopyText { text: modelData.codeExpired ? "接入码已过期 · 请更换" : (vm.nodeIndex === index ? "● 当前入口" : "切换至此节点 →") + (modelData.personalCode ? " · 个人启动器接入码" : " · 匿名接入"); color: modelData.codeExpired ? "#f0c49c" : vm.nodeIndex === index ? "#9dd4b8" : "#b4a6ca"; font.pixelSize: 10 }
                        }
                        background: Rectangle {
                            color: vm.nodeIndex === index ? "#382c4d" : parent.hovered ? "#2f283b" : "#231f2d"
                            border.color: vm.nodeIndex === index ? "#a18acb" : "#44394f"
                            Rectangle { width: 2; height: parent.height - 16; y: 8; color: "#b79ae6"; visible: vm.nodeIndex === index }
                        }
                        enabled: !vm.connections.length
                        onClicked: { nodesPage.removing = false; lobby.act("node", {index:index}) }
                    }
                    CopyText { anchors.centerIn: parent; width: parent.width - 16; visible: vm.nodes.length === 0; text: "你的联机入口\n\n添加后会显示在这里"; horizontalAlignment: Text.AlignHCenter; font.pixelSize: 12; color: "#a79ab6" }
                }
                RowLayout {
                    Layout.fillWidth: true; spacing: 6
                    ActionButton {
                        objectName: "remove-node"; text: nodesPage.removing ? "确认移除" : "移除"; Layout.fillWidth: true; implicitHeight: 28
                        enabled: vm.nodeIndex >= 0; danger: true; quiet: true
                        onClicked: { if (nodesPage.removing) { nodesPage.removing = false; lobby.act("removeNode", {}) } else nodesPage.removing = true }
                    }
                }
            }
        }
        Surface {
            Layout.fillWidth: true; Layout.fillHeight: true
            color: "#c4241d32"; border.color: "#645077"
            ColumnLayout {
                anchors.fill: parent; anchors.margins: 20; spacing: 12
                CopyText { text: vm.nodeAccessExpired ? "更换接入码" : "添加联机节点"; font.pixelSize: 20; font.bold: true; color: "#f0e8ff" }
                CopyText { Layout.fillWidth: true; text: vm.nodeAccessExpired ? "从原节点网页领取新码，粘贴后更新即可。" : "从节点网页复制接入码，粘贴到这里即可联机。"; font.pixelSize: 12; color: "#baaccb"; wrapMode: Text.Wrap }
                Item { Layout.fillHeight: true; Layout.minimumHeight: 0; Layout.maximumHeight: 14 }
                CopyText { text: "接入码"; font.pixelSize: 12; color: "#e2d6f2" }
                InputField {
                    objectName: "node-code"; Layout.fillWidth: true; Layout.preferredHeight: 36
                    placeholderText: "粘贴从节点网页复制的接入码"; maximumLength: 4096
                    text: vm.nodeDraft || ""; onTextEdited: lobby.act("nodeDraft", {text:text})
                    onAccepted: { if (!vm.busy && (vm.nodeDraft || "").trim()) lobby.act("addNodeCode", {}) }
                }
                ActionButton {
                    objectName: "add-node-code"; Layout.fillWidth: true; implicitHeight: 36
                    text: vm.busy ? "正在验证…" : "添加节点"; primary: true
                    enabled: !vm.busy && (vm.nodeDraft || "").trim().length > 0
                    onClicked: lobby.act("addNodeCode", {})
                }
                ActionButton {
                    objectName: "node-advanced"; text: nodesPage.advanced ? "收起更多选项" : "更多选项"; quiet: true; implicitHeight: 28
                    onClicked: nodesPage.advanced = !nodesPage.advanced
                }
                ColumnLayout {
                    visible: nodesPage.advanced; Layout.fillWidth: true; spacing: 8
                    Rectangle { Layout.fillWidth: true; height: 1; color: "#494056" }
                    CopyText { Layout.fillWidth: true; text: "匿名码可直接联机；个人码还可使用好友功能。"; font.pixelSize: 11; color: "#b7a8c8" }
                    RowLayout {
                        Layout.fillWidth: true; spacing: 8
                        ActionButton { objectName: "import-node"; text: "导入配置"; Layout.fillWidth: true; quiet: true; enabled: !vm.busy; implicitHeight: 28; onClicked: lobby.act("importNode", {}) }
                        ActionButton { objectName: "export-node"; text: "导出配置"; Layout.fillWidth: true; implicitHeight: 28; enabled: !vm.busy && vm.nodeIndex >= 0; quiet: true; onClicked: lobby.act("exportNode", {}) }
                    }
                }
                Item { Layout.fillHeight: true; Layout.minimumHeight: 0 }
                CopyText { Layout.fillWidth: true; text: "接入码请勿公开分享。"; font.pixelSize: 11; color: "#a397b4" }
            }
        }
    }
    RowLayout {
        Layout.fillWidth: true
        CopyText { Layout.fillWidth: true; text: "联邦节点可发现同网络房间，无需注册账号。"; font.pixelSize: 11; color: "#b0a0c3" }
        ActionButton { objectName: "nodes-done"; text: "完成，返回大厅"; implicitHeight: 30; primary: true; onClicked: lobby.act("navigate", {page:"hall"}) }
    }
}
