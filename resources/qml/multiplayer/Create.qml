import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

ColumnLayout {
    id: create
    property var vm: lobby.view
    property int worldIndex: -1
    property bool manual: false
    property bool makePublic: false
    property bool requireInvite: false
    property bool advanced: false
    property bool gameChatEnabled: false
    readonly property bool scanning: !!vm.worldScanning
    spacing: 10
    FriendInviteProgress { objectName: "create-friend-invite-progress"; flow: vm.friendInviteFlow || ({}); onAction: function(name, data) { lobby.act(name, data) } }
    function selectDiscoveredWorld() {
        if (!vm.worlds.length) {
            create.worldIndex = -1
            return
        }
        var requested = Number(vm.pendingOpenWorldPort || vm.worldPort || port.text || 0)
        var selected = vm.worlds.findIndex(function(world) { return Number(world.port) === requested })
        create.worldIndex = selected >= 0 ? selected : (vm.worlds.length === 1 ? 0 : -1)
        if (create.worldIndex >= 0) port.text = String(vm.worlds[create.worldIndex].port)
    }
    Component.onCompleted: Qt.callLater(function() {
        if (lobby.view.page === "create") {
            selectDiscoveredWorld()
            lobby.act("discover", {})
        }
    })
    ScrollView {
        objectName: "create-world-scroll"
        Layout.fillWidth: true; Layout.fillHeight: true; clip: true
        contentWidth: availableWidth
        ColumnLayout {
            width: parent.width; spacing: 10
            Item { Layout.preferredHeight: 2 }
            Surface {
                Layout.fillWidth: true; Layout.maximumWidth: 620; Layout.alignment: Qt.AlignHCenter
                implicitHeight: details.implicitHeight + 24
                color: "#211d2b"; border.color: "#49415c"
                ColumnLayout {
                    id: details
                    anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 12
                    spacing: 8
                    ColumnLayout { Layout.fillWidth: true; spacing: 5
                        RowLayout {
                            Layout.fillWidth: true
                            CopyText { Layout.fillWidth: true; text: "房间名称"; color: "#d5cfe3" }
                            CopyText { text: create.makePublic ? "公开房间" : "仅邀请好友"; color: "#b6a3d7"; font.pixelSize: 11 }
                        }
                        InputField {
                            id: title; objectName: "create-title"; Layout.fillWidth: true
                            text: vm.defaultRoomTitle || "玩家的房间"; maximumLength: 80; placeholderText: "例如 周末一起盖城堡"
                            onTextEdited: { if (vm.error) lobby.act("clearError", {}) }
                        }
                    }
                    InstancePicker { objectName: "create-game-config"; Layout.fillWidth: true }
                }
            }
            Surface {
                objectName: "create-world-discovery"
                Layout.fillWidth: true; Layout.maximumWidth: 620; Layout.alignment: Qt.AlignHCenter
                implicitHeight: discovery.implicitHeight + 28
                color: "#211d2b"; border.color: "#49415c"
                ColumnLayout {
                    id: discovery
                    anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
                    anchors.leftMargin: 18; anchors.rightMargin: 18; anchors.topMargin: 14
                    spacing: 8
                    RowLayout {
                        Layout.fillWidth: true
                        CopyText { Layout.fillWidth: true; text: "局域网世界"; font.pixelSize: 14; font.bold: true; color: "#f4f0ff" }
                        ActionButton { objectName: "discover-worlds"; text: create.scanning ? "正在扫描…" : "重新查找"; enabled: !vm.busy; onClicked: { create.worldIndex = -1; lobby.act("discover", {}) } }
                    }
                    CopyText { Layout.fillWidth: true; text: "进入单人世界，打开暂停菜单，选择“对局域网开放”。启动器会自动找到它。" }
                    Rectangle {
                        objectName: "create-world-scanning"
                        visible: create.scanning
                        Layout.fillWidth: true; implicitHeight: scanningContent.implicitHeight + 24
                        color: "#352947"; border.color: "#a28aef"
                        ColumnLayout {
                            id: scanningContent
                            anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
                            anchors.margins: 12; spacing: 10
                            RowLayout {
                                Layout.fillWidth: true; spacing: 12
                                BusyIndicator {
                                    objectName: "create-world-scan-spinner"
                                    Layout.preferredWidth: 32; Layout.preferredHeight: 32
                                    running: create.scanning; palette.dark: "#d0bbff"
                                }
                                ColumnLayout {
                                    Layout.fillWidth: true; spacing: 4
                                    CopyText { text: "正在扫描局域网世界"; color: "#f2eaff"; font.bold: true; font.pixelSize: 14 }
                                    CopyText { Layout.fillWidth: true; text: "请保持世界开放，通常几秒内完成。"; color: "#c6b6df"; font.pixelSize: 11 }
                                }
                            }
                            ProgressBar {
                                Layout.fillWidth: true; implicitHeight: 4
                                indeterminate: true; palette.highlight: "#bba3ff"; palette.dark: "#514568"
                            }
                        }
                    }
                    Rectangle {
                        objectName: "create-worlds-empty"
                        visible: vm.worlds.length === 0 && !create.scanning
                        Layout.fillWidth: true; implicitHeight: 44
                        color: "#241e30"; border.color: "#42384f"
                        CopyText { anchors.centerIn: parent; text: vm.busy ? "正在查找本机开放的世界…" : "暂未发现开放的世界"; color: "#91899f" }
                    }
                    Repeater {
                        model: vm.worlds
                        delegate: Button {
                            id: world
                            required property var modelData
                            required property int index
                            Layout.fillWidth: true
                            implicitHeight: 42
                            objectName: "world-" + index
                            property bool selected: create.worldIndex === index
                            Accessible.name: modelData.version + "，端口 " + modelData.port
                            Accessible.description: selected ? "已选择" : "点击选择这个世界"
                            contentItem: RowLayout {
                                spacing: 10
                                Rectangle {
                                    Layout.leftMargin: 8; width: 16; height: 16; radius: 8
                                    color: world.selected ? "#a28aef" : "transparent"
                                    border.color: world.selected ? "#d2c4ff" : "#786b8f"
                                    Rectangle { anchors.centerIn: parent; width: 6; height: 6; radius: 3; color: "#251f35"; visible: world.selected }
                                }
                                CopyText { Layout.fillWidth: true; text: "游戏世界 · " + modelData.version; color: world.selected ? "#f2edff" : "#d5cede" }
                                CopyText { Layout.rightMargin: 10; text: "端口 " + modelData.port; font.pixelSize: 11 }
                            }
                            background: Rectangle {
                                color: world.selected ? "#3a2c52" : world.hovered ? "#2d2539" : "#231e2d"
                                border.color: world.activeFocus ? "#dbceff" : world.selected ? "#a28aef" : "#42384f"
                            }
                            HoverHandler { cursorShape: Qt.PointingHandCursor }
                            onClicked: { create.worldIndex = index; port.text = String(modelData.port) }
                        }
                    }
                    ColumnLayout {
                        visible: vm.worlds.length === 0 && !vm.busy
                        Layout.fillWidth: true; spacing: 3
                        CopyText { Layout.fillWidth: true; text: "还没进入世界？可以先创建房间，再启动游戏并开放局域网。"; color: "#c7bdd8"; font.pixelSize: 11; wrapMode: Text.Wrap }
                    }
                    Button {
                        visible: create.advanced && (vm.worlds.length > 0 || create.manual)
                        objectName: "show-manual"
                        implicitHeight: 28
                        text: create.manual ? "收起手动填写 ↑" : "高级选项：手动填写端口 ↓"
                        contentItem: CopyText { text: parent.text; color: parent.hovered ? "#d0baff" : "#b4a1cc"; verticalAlignment: Text.AlignVCenter }
                        background: Rectangle { color: "transparent"; border.width: parent.activeFocus ? 1 : 0; border.color: "#a28aef" }
                        HoverHandler { cursorShape: Qt.PointingHandCursor }
                        onClicked: create.manual = !create.manual
                    }
                    RowLayout {
                        visible: create.manual; Layout.fillWidth: true; spacing: 12
                        CopyText { text: "游戏显示的端口" }
                        InputField {
                            id: port; objectName: "create-port"; Layout.fillWidth: true
                            placeholderText: "例如 51234"; maximumLength: 5
                            inputMethodHints: Qt.ImhDigitsOnly
                            validator: IntValidator { bottom: 1; top: 65535 }
                            onTextEdited: { if (vm.error) lobby.act("clearError", {}) }
                        }
                    }
                }
            }
            Surface {
                visible: create.advanced
                Layout.fillWidth: true; Layout.maximumWidth: 620; Layout.alignment: Qt.AlignHCenter
                implicitHeight: chatOptions.implicitHeight + 24
                color: "#211d2b"; border.color: "#49415c"
                ColumnLayout {
                    id: chatOptions
                    anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 12
                    spacing: 6
                    Rectangle { Layout.fillWidth: true; height: 1; color: "#3a354b" }
                        RoomVisibility { id: publicRoom; objectName: "create-public"; text: "在大厅公开这个房间"; checked: create.makePublic; onToggled: { create.makePublic = checked; if (typeof tutorial !== "undefined") tutorial.action("privacy") } }
                    RoomVisibility {
                        objectName: "create-require-invite"; Layout.leftMargin: 27
                        visible: publicRoom.checked; text: "加入需要邀请码"
                        checked: create.requireInvite; onToggled: create.requireInvite = checked
                    }
                    CopyText {
                        objectName: "create-access-description"; Layout.fillWidth: true
                        text: !publicRoom.checked ? "不出现在大厅，仅持有邀请码的玩家可以加入。" :
                            create.requireInvite ? "大厅可见，玩家需填写房主提供的邀请码才能加入。" : "大厅可见，玩家可以直接加入，无需填写邀请码。"
                        font.pixelSize: 11
                    }
                    CopyText { text: "玩家连接方式"; color: "#d5cfe3" }
                    ChoiceBox {
                        objectName: "create-transport"
                        Layout.fillWidth: true
                        model: ["优先 P2P，失败时自动中转", "仅通过节点中转"]
                        currentIndex: vm.transportPolicy === "relay" ? 1 : 0
                        onActivated: function(index) { lobby.act("transport", {policy:index === 1 ? "relay" : "auto"}) }
                    }
                    CopyText {
                        Layout.fillWidth: true; font.pixelSize: 11
                        text: vm.transportPolicy === "relay" ? "房间内所有玩家使用节点中转。" : "每位玩家分别建立连接：能直连的走 P2P，失败后只让该玩家回落到中转。"
                    }
                    RoomVisibility {
                        objectName: "create-game-chat"; text: "同步大厅与游戏聊天"
                        checked: create.gameChatEnabled; onToggled: create.gameChatEnabled = checked
                    }
                    CopyText {
                        objectName: "create-game-chat-explanation"
                        Layout.fillWidth: true
                        text: "开启后，会多一个虚拟玩家进入游戏，占用 1 个人数名额。关闭时仍可在房间大厅聊天。"
                    }
                    RowLayout {
                        visible: create.gameChatEnabled; Layout.fillWidth: true; spacing: 12
                        CopyText { text: "虚拟玩家名称"; color: "#d5cfe3" }
                        InputField {
                            id: chatName; objectName: "create-game-chat-name"; Layout.fillWidth: true
                            text: "BuggChat"; maximumLength: 16
                            validator: RegularExpressionValidator { regularExpression: /[A-Za-z][A-Za-z0-9_]{2,15}/ }
                            inputMethodHints: Qt.ImhLatinOnly | Qt.ImhNoPredictiveText
                            onTextEdited: { if (vm.error) lobby.act("clearError", {}) }
                        }
                    }
                    CopyText {
                        visible: create.gameChatEnabled; Layout.fillWidth: true; font.pixelSize: 11
                        text: "3–16 位，以英文字母开头，可含数字、下划线；请勿与真实玩家重名。"
                    }
                }
            }
        }
    }
    CopyText {
        objectName: "create-node-unavailable"; Layout.fillWidth: true
        visible: !vm.nodeAvailable; color: "#dfbd92"; font.pixelSize: 12
        text: "联机节点暂不可用，请返回大厅刷新节点后继续。"
    }
    RowLayout {
        objectName: "create-footer"
        Layout.fillWidth: true; Layout.maximumWidth: 620; Layout.alignment: Qt.AlignHCenter
        ActionButton {
            objectName: "create-advanced"; quiet: true
            text: create.advanced ? "收起高级选项" : "高级选项"
            onClicked: {
                create.advanced = !create.advanced
                if (!create.advanced) create.manual = false
                if (typeof tutorial !== "undefined") tutorial.action("privacy")
            }
        }
        Item { Layout.fillWidth: true }
        ActionButton { objectName: "cancel-create"; text: "取消"; quiet: true; onClicked: lobby.act("navigate", {page:"hall"}) }
        ActionButton {
            objectName: "create-next"
            text: create.scanning ? "正在查找世界…" : vm.busy ? "正在创建…" : create.worldIndex >= 0 || (create.manual && port.acceptableInput) ? "创建房间" : vm.worlds.length > 1 ? "请选择游戏世界" : "先创建房间"
            primary: true
            enabled: !!vm.nodeAvailable && !vm.busy && !vm.instanceLoading && !!vm.version &&
                (vm.worlds.length <= 1 || create.worldIndex >= 0 || (create.manual && port.acceptableInput)) &&
                (!create.manual || port.acceptableInput) &&
                (!create.scanning || (create.manual && port.acceptableInput)) && (!create.gameChatEnabled || chatName.acceptableInput)
            onClicked: {
                lobby.act("quickCreate", {port:create.worldIndex >= 0 || create.manual ? port.text : 0, title:title.text, "public":publicRoom.checked, requireInvite:!publicRoom.checked || create.requireInvite, gameChatEnabled:create.gameChatEnabled, gameChatName:chatName.text, transport:vm.transportPolicy})
                if (typeof tutorial !== "undefined") tutorial.action("create-world")
            }
        }
    }
    Connections {
        target: lobby
        function onChanged() {
            create.selectDiscoveredWorld()
        }
    }
}
