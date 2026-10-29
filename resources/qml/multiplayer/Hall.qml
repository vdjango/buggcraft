import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

ColumnLayout {
    id: hall
    property var vm: lobby.view
    property bool canUseNode: vm.nodeIndex >= 0 && !!vm.nodeAvailable
    spacing: 4
    Surface {
        objectName: "lobby-loading-status"
        Layout.fillWidth: true; Layout.preferredHeight: 46
        visible: !!vm.socialLoading || !!vm.loading
        color: "#272238"; border.color: "#5d4c79"
        RowLayout {
            anchors.fill: parent; anchors.margins: 9; spacing: 8
            BusyIndicator { implicitWidth: 18; implicitHeight: 18; running: parent.parent.visible }
            CopyText { Layout.fillWidth: true; text: vm.socialLoading ? "正在登录好友服务…" : "正在连接联机节点并加载房间…"; color: "#ded3f3"; font.pixelSize: 12 }
        }
    }
    Surface {
        objectName: "hall-network-profile"; visible: true
        Layout.fillWidth: true; Layout.preferredHeight: 28; color: "#24202c"; border.color: "#51445d"
        RowLayout {
            anchors.fill: parent; anchors.leftMargin: 9; anchors.rightMargin: 6; spacing: 6
            CopyText {
                objectName: "hall-network-type"; Layout.fillWidth: true
                text: "你的网络类型：" + (!vm.playerNetworkProfileReady ? "正在判断…" : (vm.playerNetworkProfile || {}).type === "direct_easier" ? "较容易直连" : (vm.playerNetworkProfile || {}).type === "relay_likely" ? "可能需要中转" : "暂时无法判断") +
                    (!vm.playerNetworkProfileReady ? " · 正在读取近7天联机记录…" : " · 近7天：直连成功 " + ((vm.playerNetworkProfile || {}).direct_successes || 0) + " 次 · 中转成功 " + ((vm.playerNetworkProfile || {}).relay_successes || 0) + " 次")
                font.pixelSize: 11; color: "#e1d7e9"; elide: Text.ElideRight
            }
            HeaderAction {
                objectName: "hall-network-profile-help"; text: "?"; iconSize: 13
                label: "网络类型是按当前网络情况给出的参考，不能保证和每位好友都能直接连接；还要看好友当时的网络和本次连接。失败时会自动尝试中转。同步的只有网络类型和近 7 天成功次数，不包含网络地址。次数是与所有玩家的总记录，不代表和某位好友单独联机的次数。"
            }
        }
    }
    RowLayout {
        Layout.fillWidth: true
        visible: !!vm.socialError
        CopyText { objectName: "lobby-social-error"; Layout.fillWidth: true; text: vm.socialError || ""; color: "#e8b3b3"; font.pixelSize: 11; wrapMode: Text.Wrap; maximumLineCount: 2; elide: Text.ElideRight }
        ActionButton { objectName: "retry-social-login"; text: (vm.nodeAccessExpired || vm.nodeCredentialRequired) ? (vm.deviceManaged ? "重新登录" : "更换接入码") : "重试账号验证"; quiet: true; implicitHeight: 28; onClicked: lobby.act((vm.nodeAccessExpired || vm.nodeCredentialRequired) ? "replaceNodeCode" : "refreshFriends", {}) }
    }
    Rectangle {
        id: nodeBar
        objectName: "room-node-row"
        Layout.fillWidth: true
        Layout.preferredHeight: 70
        color: "#201c29"
        border.color: "#40384a"
        property color statusColor: vm.roomError ? "#d9aa7a" :
            vm.nodeIndex < 0 || !vm.nodeAvailable ? "#c99b74" : "#83c39f"
        GridLayout {
            columns: 4; rowSpacing: 6; columnSpacing: 8
            anchors.fill: parent
            anchors.leftMargin: 9; anchors.rightMargin: 9
            CopyText {
                objectName: "node-picker-label"
                text: "联机节点"
                Layout.preferredWidth: 64; Layout.alignment: Qt.AlignVCenter
                color: "#b9adca"; font.pixelSize: 12
            }
            ChoiceBox {
                objectName: "node-picker"
                enabled: vm.connections.length === 0
                Layout.preferredWidth: 250; Layout.preferredHeight: 32
                tutorialHighlight: typeof tutorial !== "undefined" && tutorial.demoStep === "node"
                tutorialLockedIndex: typeof tutorial !== "undefined" && tutorial.demoStep === "node" ? vm.nodes.length : -1
                model: vm.nodes.map(function(node) { return node.title }).concat(["＋ 添加与管理节点"])
                currentIndex: vm.nodeIndex
                displayText: vm.nodeIndex >= 0 && vm.nodes[vm.nodeIndex] ? vm.nodes[vm.nodeIndex].title : "＋ 添加联机节点"
                Accessible.name: "切换节点或添加与管理节点"
                onActivated: function(index) {
                    if (typeof tutorial !== "undefined" && tutorial.demoStep === "node") {
                        currentIndex = Qt.binding(function() { return vm.nodeIndex })
                        return
                    }
                    if (index < vm.nodes.length) lobby.act("node", {index:index})
                    else {
                        currentIndex = Qt.binding(function() { return vm.nodeIndex })
                        lobby.act("navigate", {page:"nodes"})
                    }
                }
            }
            RowLayout {
                objectName: "node-status"
                Layout.fillWidth: true; Layout.minimumWidth: 80
                spacing: 6
                Rectangle {
                    objectName: "node-status-indicator"
                    width: 7; height: 7; radius: 4
                    color: nodeBar.statusColor
                }
                CopyText {
                    objectName: "hall-node-latency"
                    property bool measured: !!vm.nodeAvailable && typeof vm.nodeLatencyMs === "number" && isFinite(vm.nodeLatencyMs) && vm.nodeLatencyMs >= 0
                    text: "到大厅节点 " + (measured ? Math.round(vm.nodeLatencyMs) + " ms" : "—")
                    font.pixelSize: 11; color: !measured ? "#aaa4b3" : vm.nodeLatencyMs < 100 ? "#a7c9b5" : vm.nodeLatencyMs < 250 ? "#d0b895" : "#e8b3b3"
                    ToolTip.visible: nodeLatencyHover.hovered
                    ToolTip.text: "你到当前大厅节点的小消息往返时间，不包含连接、登录和房间列表加载；不是到房主的延迟。"
                    HoverHandler { id: nodeLatencyHover }
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
            ActionButton {
                objectName: "refresh-rooms"; text: vm.loading ? "检查中…" : "刷新"
                enabled: vm.nodeIndex >= 0 && !vm.loading; quiet: true
                Layout.preferredWidth: 72; Layout.preferredHeight: 32
                onClicked: lobby.act("refresh", {})
            }
            CopyText {
                objectName: "hall-transport-label"
                text: "联机方式"; color: "#b9adca"; font.pixelSize: 12
                Layout.preferredWidth: 64; Layout.alignment: Qt.AlignVCenter
            }
            ChoiceBox {
                objectName: "hall-transport"
                Layout.preferredWidth: 250; Layout.preferredHeight: 32
                enabled: !vm.busy && vm.connections.length === 0
                model: ["优先直连，自动中转", "仅通过节点中转"]
                currentIndex: vm.transportPolicy === "relay" ? 1 : 0
                Accessible.name: "加入房间的连接方式"
                onActivated: function(index) { lobby.act("transport", {policy:index === 1 ? "relay" : "auto"}) }
            }
            CopyText {
                objectName: "lobby-identity"; Layout.fillWidth: true
                text: vm.nodeAccessExpired ? (vm.deviceManaged ? "登录已失效" : "接入码已过期") : vm.socialReady ? "已登录 · " + vm.socialName : vm.deviceManaged ? "账号待验证" : (vm.nodeIndex >= 0 && vm.nodes[vm.nodeIndex] && vm.nodes[vm.nodeIndex].personalCode ? "个人码待验证" : "匿名接入")
                font.pixelSize: 11; color: vm.socialReady ? "#8edbb0" : "#c1b7ce"
                wrapMode: Text.NoWrap; elide: Text.ElideRight; horizontalAlignment: Text.AlignRight
            }
            ActionButton {
                objectName: "export-diagnostics"; text: "导出日志"; quiet: true
                Layout.preferredWidth: 72; Layout.preferredHeight: 32
                onClicked: lobby.act("exportDiagnostics", {})
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
            onClicked: { lobby.act("navigate", {page:"create"}); if (typeof tutorial !== "undefined") tutorial.action("create") }
        }
        ActionButton {
            objectName: "open-join"; text: "加入房间"
            Layout.preferredWidth: 100; Layout.preferredHeight: 32
            enabled: hall.canUseNode && !vm.busy
            onClicked: lobby.act("navigate", {page:"join"})
        }
        ActionButton {
            objectName: "submit-diagnostics"; text: "提交诊断"; quiet: true
            Layout.preferredWidth: 76; Layout.preferredHeight: 32
            enabled: vm.socialReady && !vm.busy
            Accessible.name: "提交联机诊断日志到当前节点反馈系统"
            onClicked: lobby.act("submitDiagnostics", {})
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
                id: roomRow
                required property var modelData
                required property int index
                readonly property string worldState: modelData.availability || ""
                readonly property var connection: (vm.connections || []).find(function(item) { return item.roomId === roomRow.modelData.id && item.state === "online" }) || null
                width: rooms.width; height: 68
                color: index % 2 ? "#282530" : "#24222c"
                border.color: "#3f3949"
                RowLayout {
                    anchors.fill: parent; anchors.leftMargin: 10; anchors.rightMargin: 9; spacing: 9
                    Rectangle {
                        width: 3; height: 32
                        color: roomRow.worldState === "waiting" ? "#d0b895" : roomRow.worldState === "ready" ? "#75b995" : "#aaa4b3"
                    }
                    ColumnLayout {
                        Layout.fillWidth: true; spacing: 2
                        CopyText {
                            Layout.fillWidth: true; text: modelData.title
                            wrapMode: Text.NoWrap; elide: Text.ElideRight
                            font.pixelSize: 14; font.bold: true; color: "#f2edff"
                        }
                        CopyText {
                            objectName: "room-node-location-" + index
                            Layout.fillWidth: true
                            text: [modelData.node_name || "", modelData.node_region || ""].filter(function(value) { return value.length > 0 }).join(" · ") || "所属节点未知"
                            wrapMode: Text.NoWrap; elide: Text.ElideRight
                            font.pixelSize: 10; color: "#9faab3"
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8
                            CopyText {
                                objectName: "room-availability-" + index
                                text: roomRow.worldState === "waiting" ? "准备中" : roomRow.worldState === "ready" ? "世界已开放" : "状态未知"
                                color: roomRow.worldState === "waiting" ? "#d0b895" : roomRow.worldState === "ready" ? "#a7c9b5" : "#aaa4b3"
                                font.pixelSize: 11
                                wrapMode: Text.NoWrap
                                Accessible.name: text
                                ToolTip.visible: roomStateHover.hovered
                                ToolTip.text: roomRow.worldState === "waiting" ? "房间已创建，世界尚未开放；可以先加入聊天、下载和准备客户端。" : roomRow.worldState === "ready" ? "世界已开放；加入房间并准备好客户端后即可进入游戏。" : "节点尚未提供世界状态，请刷新后重试。"
                                HoverHandler { id: roomStateHover }
                            }
                            CopyText {
                                Layout.fillWidth: true
                                text: (modelData.game.version || "版本未知") + "  ·  " +
                                    (({vanilla:"原版",fabric:"Fabric",forge:"Forge",quilt:"Quilt",neoforge:"NeoForge"})[modelData.game.loader] || modelData.game.loader || "原版") + "  ·  " + (typeof modelData.members === "number" ? modelData.members + " / " + modelData.capacity + " 人在房间" : "人数暂未知")
                                font.pixelSize: 11; color: "#aaa4b3"
                                elide: Text.ElideRight; wrapMode: Text.NoWrap
                            }
                        }
                    }
                    CopyText {
                        objectName: "room-latency-" + index
                        property var latency: roomRow.connection ? roomRow.connection.latency_ms : null
                        property bool measured: typeof latency === "number" && isFinite(latency) && latency >= 0
                        text: measured ? "到房主 " + Math.round(latency) + " ms" + (roomRow.connection.role === "host" ? " · 本机" : "") : roomRow.connection ? "到房主 —" : "加入后测量"
                        color: !measured ? "#aaa4b3" : latency < 100 ? "#a7c9b5" : latency < 250 ? "#d0b895" : "#e8b3b3"
                        font.pixelSize: 11
                        Layout.preferredWidth: 112
                        horizontalAlignment: Text.AlignRight
                        ToolTip.visible: roomLatencyHover.hovered
                        ToolTip.text: "加入房间后，沿实际游戏线路测量你到房主游戏的往返时间。直接连接时不经过中转节点；中转时包含你到节点、节点到房主及游戏响应时间。没有测到就显示 —。"
                        HoverHandler { id: roomLatencyHover }
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
                enabled: !(typeof tutorial !== "undefined" && tutorial.demoStep === "node")
                onClicked: {
                    if (typeof tutorial !== "undefined" && tutorial.demoStep === "node") return
                    lobby.act("navigate", {page:"nodes"})
                }
            }
        }
    }
}
