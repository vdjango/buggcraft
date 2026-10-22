import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

ColumnLayout {
    id: hall
    property var vm: lobby.view
    property bool canUseNode: vm.nodeIndex >= 0 && !!vm.nodeAvailable
    spacing: 8
    RowLayout {
        Layout.fillWidth: true; spacing: 8
        CopyText { objectName: "lobby-identity"; Layout.fillWidth: true; text: vm.socialReady ? "已登录 · " + vm.socialName : (vm.nodeIndex >= 0 && vm.nodes[vm.nodeIndex] && vm.nodes[vm.nodeIndex].personalCode ? "个人码待验证" : "匿名接入"); font.pixelSize: 11; color: vm.socialReady ? "#8edbb0" : "#c1b7ce" }
        CopyText { text: "连接方式"; font.pixelSize: 11 }
        ChoiceBox {
            objectName: "hall-transport"
            Layout.preferredWidth: 168; Layout.preferredHeight: 28
            enabled: !vm.busy && vm.connections.length === 0
            model: ["P2P 优先，自动中转", "仅通过节点中转"]
            currentIndex: vm.transportPolicy === "relay" ? 1 : 0
            Accessible.name: "加入房间的连接方式"
            onActivated: function(index) { lobby.act("transport", {policy:index === 1 ? "relay" : "auto"}) }
        }
    }
    Rectangle {
        id: nodeBar
        objectName: "room-node-row"
        Layout.fillWidth: true
        Layout.preferredHeight: 42
        color: "#201c29"
        border.color: "#40384a"
        property color statusColor: vm.roomError ? "#d9aa7a" :
            vm.nodeIndex < 0 || !vm.nodeAvailable ? "#c99b74" : "#83c39f"
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 9; anchors.rightMargin: 9
            spacing: 8
            CopyText {
                text: "联机节点"
                color: "#b9adca"; font.pixelSize: 12
            }
            ChoiceBox {
                objectName: "node-picker"
                enabled: vm.connections.length === 0
                Layout.preferredWidth: 250; Layout.preferredHeight: 32
                model: vm.nodes.map(function(node) { return node.title }).concat(["＋ 添加与管理节点"])
                currentIndex: vm.nodeIndex
                displayText: vm.nodeIndex >= 0 && vm.nodes[vm.nodeIndex] ? vm.nodes[vm.nodeIndex].title : "＋ 添加联机节点"
                Accessible.name: "切换节点或添加与管理节点"
                onActivated: function(index) {
                    if (index < vm.nodes.length) lobby.act("node", {index:index})
                    else {
                        currentIndex = Qt.binding(function() { return vm.nodeIndex })
                        lobby.act("navigate", {page:"nodes"})
                    }
                }
            }
            RowLayout {
                objectName: "node-status"
                Layout.preferredWidth: 112
                spacing: 6
                Rectangle {
                    objectName: "node-status-indicator"
                    width: 7; height: 7; radius: 4
                    color: nodeBar.statusColor
                }
                CopyText {
                    objectName: "rooms-loaded"
                    Layout.fillWidth: true
                    horizontalAlignment: Text.AlignRight
                    text: vm.roomError ? (vm.nodeAvailable ? "列表异常" : "连接失败") :
                        vm.nodeIndex < 0 ? "未添加" : vm.loading ? "检查中" :
                        !vm.nodeAvailable ? "不可用" : vm.loadingMore ? "加载中" : "已连接"
                    color: nodeBar.statusColor; font.pixelSize: 11
                    elide: Text.ElideRight; wrapMode: Text.NoWrap
                }
            }
            Item { Layout.fillWidth: true }
            ActionButton {
                objectName: "refresh-rooms"; text: vm.loading ? "检查中…" : "刷新"
                enabled: vm.nodeIndex >= 0 && !vm.loading; quiet: true
                Layout.preferredWidth: 72; Layout.preferredHeight: 32
                onClicked: lobby.act("refresh", {})
            }
        }
    }
    RowLayout {
        objectName: "room-search-row"
        Layout.fillWidth: true; Layout.preferredHeight: 38; spacing: 8
        ActionButton {
            objectName: "open-create"; text: "创建房间"; primary: true
            Layout.preferredWidth: 100; Layout.preferredHeight: 32
            enabled: hall.canUseNode && !vm.busy
            onClicked: lobby.act("navigate", {page:"create"})
        }
        ActionButton {
            objectName: "open-join"; text: "加入房间"
            Layout.preferredWidth: 100; Layout.preferredHeight: 32
            enabled: hall.canUseNode && !vm.busy
            onClicked: lobby.act("navigate", {page:"join"})
        }
        ActionButton {
            objectName: "current-room-entry"
            visible: vm.connections.length > 0
            property var currentRoom: vm.connections[0] || ({})
            text: vm.connections.length > 1 ? "我的房间 · " + vm.connections.length + " →" :
                (currentRoom.role === "host" ? "我创建 · " : "我加入 · ") + (currentRoom.title || "房间") + " →"
            Layout.preferredWidth: 105; Layout.maximumWidth: 105; Layout.preferredHeight: 32
            onClicked: vm.connections.length > 1 ? lobby.act("navigate", {page:"connections"}) : lobby.act("selectConnection", {id:currentRoom.id})
        }
        Item { Layout.fillWidth: true }
        CopyText {
            objectName: "room-count"
            Layout.preferredWidth: 62; Layout.alignment: Qt.AlignVCenter
            horizontalAlignment: Text.AlignRight
            text: (vm.roomTotal === null || vm.roomTotal === undefined ? vm.rooms.length + (vm.roomNext !== null && vm.roomNext !== undefined ? "+" : "") : vm.roomTotal) + " 个房间"
            font.pixelSize: 11; color: "#aaa1ba"
            elide: Text.ElideRight; wrapMode: Text.NoWrap
        }
        InputField {
            objectName: "room-search"
            Layout.preferredWidth: 280; Layout.minimumWidth: 240; Layout.preferredHeight: 34
            Layout.alignment: Qt.AlignVCenter
            text: vm.roomQuery || ""; maximumLength: 100
            placeholderText: "搜索房间、版本或核心"
            onTextEdited: lobby.act("searchRooms", {text:text})
        }
    }

    Surface {
        Layout.fillWidth: true; Layout.fillHeight: true
        color: "#a91c1a25"
        border.color: "#52465e"
        ListView {
            id: rooms
            objectName: "rooms-list"
            anchors.fill: parent; anchors.margins: 7
            model: vm.rooms
            clip: true; spacing: 4
            reuseItems: true
            function loadNextPage() {
                if (atYEnd && vm.roomNext !== null && vm.roomNext !== undefined && !vm.roomError && !vm.loading && !vm.loadingMore)
                    lobby.act("loadMoreRooms", {})
            }
            onMovementEnded: loadNextPage()
            onContentYChanged: if (moving || dragging || roomScroll.pressed) loadNextPage()
            WheelHandler {
                acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
                onWheel: function(event) { event.accepted = false; scrollCheck.restart() }
            }
            Timer { id: scrollCheck; interval: 80; onTriggered: rooms.loadNextPage() }
            footer: Item {
                width: rooms.width; height: 42
                ActionButton {
                    objectName: "load-more-rooms"
                    anchors.centerIn: parent
                    visible: vm.roomNext !== null && vm.roomNext !== undefined
                    text: vm.loadingMore ? "加载中…" : vm.roomError ? "重试加载" : "加载更多"
                    enabled: !vm.loading && !vm.loadingMore; implicitHeight: 28; quiet: true
                    onClicked: lobby.act("loadMoreRooms", {})
                }
            }
            ScrollBar.vertical: ScrollBar { id: roomScroll }
            delegate: Rectangle {
                required property var modelData
                required property int index
                width: rooms.width; height: 58
                color: index % 2 ? "#282530" : "#24222c"
                border.color: "#3f3949"
                RowLayout {
                    anchors.fill: parent; anchors.leftMargin: 10; anchors.rightMargin: 9; spacing: 9
                    Rectangle {
                        width: 3; height: 32
                        color: "#75b995"
                    }
                    ColumnLayout {
                        Layout.fillWidth: true; spacing: 2
                        CopyText {
                            Layout.fillWidth: true; text: modelData.title
                            wrapMode: Text.NoWrap; elide: Text.ElideRight
                            font.pixelSize: 14; font.bold: true; color: "#f2edff"
                        }
                        CopyText {
                            Layout.fillWidth: true
                            text: (modelData.game.version || "版本未知") + "  ·  " +
                                (({vanilla:"原版",fabric:"Fabric",forge:"Forge",quilt:"Quilt",neoforge:"NeoForge"})[modelData.game.loader] || modelData.game.loader || "原版") + "  ·  " + (typeof modelData.members === "number" ? modelData.members + " / " + modelData.capacity + " 人在房间" : "人数暂未知")
                            font.pixelSize: 11; color: "#aaa4b3"
                            elide: Text.ElideRight; wrapMode: Text.NoWrap
                        }
                    }
                    CopyText {
                        objectName: "room-access-" + index
                        text: modelData.require_invite ? "需要邀请码" : "直接加入"
                        color: modelData.require_invite ? "#d0b895" : "#a7c9b5"; font.pixelSize: 11
                    }
                    ActionButton {
                        objectName: "join-public-" + index
                        text: "加入"; implicitHeight: 28
                        implicitWidth: 58
                        enabled: hall.canUseNode && !vm.busy
                        onClicked: lobby.act("joinPublic", {id:modelData.id})
                    }
                }
            }
        }
        ColumnLayout {
            anchors.centerIn: parent
            width: Math.min(parent.width - 36, 400)
            spacing: 8
            visible: rooms.count === 0
            Image {
                Layout.alignment: Qt.AlignHCenter
                Layout.preferredWidth: 190; Layout.preferredHeight: 42
                source: "../../images/user/MINECRAFT.png"
                fillMode: Image.PreserveAspectFit
                opacity: 0.82
            }
            Rectangle { Layout.alignment: Qt.AlignHCenter; width: 30; height: 2; color: "#8e75ce" }
            CopyText {
                objectName: "rooms-empty"
                Layout.fillWidth: true; horizontalAlignment: Text.AlignHCenter
                text: vm.roomError ? "房间列表暂时不可用" : vm.nodeIndex < 0 ? "连接一个联机节点" :
                    (vm.roomQuery || "").trim() ? "没有找到匹配的房间" : vm.loading ? "正在查找开放房间…" : "暂时没有开放房间"
                font.pixelSize: 15; color: "#f0eafa"; font.bold: true
            }
            CopyText {
                Layout.fillWidth: true; horizontalAlignment: Text.AlignHCenter
                text: vm.roomError || (vm.nodeIndex < 0 ? "从可信节点网页复制添加码，即可与朋友一起玩。" :
                    (vm.roomQuery || "").trim() ? "试试其他房间名称或游戏版本。" : "公开房间会出现在这里，私密房间通过邀请码加入。")
                font.pixelSize: 12; color: "#aaa4b3"
            }
            ActionButton {
                objectName: "empty-add-node"
                Layout.alignment: Qt.AlignHCenter
                visible: vm.nodeIndex < 0
                text: "添加联机节点"; implicitHeight: 30; primary: true
                onClicked: lobby.act("navigate", {page:"nodes"})
            }
        }
    }
}
