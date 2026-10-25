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
    property bool gameChatEnabled: false
    spacing: 10
    Component.onCompleted: lobby.act("discover", {})
    RowLayout {
        Layout.fillWidth: true; Layout.maximumWidth: 620; Layout.alignment: Qt.AlignHCenter; spacing: 12
        Repeater {
            model: ["确认游戏世界", "设置房间"]
            delegate: RowLayout {
                required property string modelData
                required property int index
                Layout.fillWidth: true; spacing: 10
                Rectangle {
                    width: 28; height: 28; radius: 14; color: vm.step === index ? "#7859ef" : "#323142"
                    CopyText { anchors.centerIn: parent; text: index + 1; color: "#f3efff"; font.bold: true }
                }
                CopyText { text: modelData; color: vm.step === index ? "#f3efff" : "#8a849e" }
                Rectangle { Layout.fillWidth: true; Layout.leftMargin: 10; height: 1; color: "#3a354b"; visible: index === 0 }
            }
        }
    }
    ScrollView {
        objectName: "create-world-scroll"
        Layout.fillWidth: true; Layout.fillHeight: true; clip: true
        contentWidth: availableWidth
        ColumnLayout {
            width: parent.width; spacing: 10
            Item { Layout.preferredHeight: 2 }
            Surface {
                objectName: "create-game-config"
                visible: vm.step === 0
                Layout.fillWidth: true; Layout.maximumWidth: 620; Layout.alignment: Qt.AlignHCenter
                implicitHeight: gameConfig.implicitHeight + 28
                color: "#211d2b"; border.color: "#49415c"
                InstancePicker {
                    id: gameConfig
                    anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
                    anchors.leftMargin: 18; anchors.rightMargin: 18; anchors.topMargin: 14
                }
            }
            Surface {
                objectName: "create-world-discovery"
                visible: vm.step === 0
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
                        ActionButton { objectName: "discover-worlds"; text: vm.busy ? "正在查找…" : "重新查找"; enabled: !vm.busy; onClicked: { create.worldIndex = -1; lobby.act("discover", {}) } }
                    }
                    CopyText { Layout.fillWidth: true; text: "打开单人世界，在暂停菜单选择“对局域网开放”。本页会自动查找，无需手动刷新。" }
                    Rectangle {
                        objectName: "create-worlds-empty"
                        visible: vm.worlds.length === 0
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
                                CopyText { Layout.fillWidth: true; text: "Minecraft " + modelData.version; color: world.selected ? "#f2edff" : "#d5cede" }
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
                        visible: vm.worlds.length > 0 || create.manual
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
                visible: vm.step === 1
                Layout.fillWidth: true; Layout.maximumWidth: 620; Layout.alignment: Qt.AlignHCenter
                implicitHeight: details.implicitHeight + 24
                color: "#211d2b"; border.color: "#49415c"
                ColumnLayout {
                    id: details
                    anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 12
                    spacing: 8
                    CopyText { text: "设置房间"; font.pixelSize: 15; font.bold: true; color: "#f3efff" }
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
                    ColumnLayout { Layout.fillWidth: true; spacing: 5
                        CopyText { text: "房间名称"; color: "#d5cfe3" }
                        InputField {
                            id: title; objectName: "create-title"; Layout.fillWidth: true
                            text: "好友的世界"; maximumLength: 80; placeholderText: "例如 周末一起盖城堡"
                            onTextEdited: { if (vm.error) lobby.act("clearError", {}) }
                        }
                    }
                    Rectangle { Layout.fillWidth: true; height: 1; color: "#3a354b" }
                    RoomVisibility { id: publicRoom; objectName: "create-public"; text: "在大厅公开这个房间"; checked: create.makePublic; onToggled: create.makePublic = checked }
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
                }
            }
            Surface {
                visible: vm.step === 1
                Layout.fillWidth: true; Layout.maximumWidth: 620; Layout.alignment: Qt.AlignHCenter
                implicitHeight: chatOptions.implicitHeight + 24
                color: "#211d2b"; border.color: "#49415c"
                ColumnLayout {
                    id: chatOptions
                    anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 12
                    spacing: 6
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
        ActionButton { objectName: "create-back"; text: "上一步"; visible: vm.step === 1; onClicked: lobby.act("backCreate", {}) }
        ActionButton {
            objectName: "create-before-game"
            text: "先创建房间"; quiet: true; visible: vm.step === 0
            enabled: !!vm.nodeAvailable && !vm.busy && !vm.instanceLoading && !!vm.version
            ToolTip.visible: hovered
            ToolTip.delay: 500
            ToolTip.text: "先设置房间并邀请朋友，稍后再开放游戏世界。"
            Accessible.description: ToolTip.text
            onClicked: lobby.act("createWaiting", {})
        }
        Item { Layout.fillWidth: true }
        ActionButton { objectName: "cancel-create"; text: "取消"; quiet: true; onClicked: lobby.act("navigate", {page:"hall"}) }
        ActionButton {
            objectName: "create-next"
            text: vm.busy ? "正在确认…" : vm.step === 0 ? "确认世界，下一步 →" : "创建房间"
            primary: true; enabled: !!vm.nodeAvailable && !vm.busy && !vm.instanceLoading &&
                (vm.step === 0 ? (create.worldIndex >= 0 || (create.manual && port.acceptableInput)) : (!create.gameChatEnabled || chatName.acceptableInput))
            onClicked: vm.step === 0 ? lobby.act("probe", {port:port.text}) : lobby.act("create", {title:title.text, "public":publicRoom.checked, requireInvite:!publicRoom.checked || create.requireInvite, gameChatEnabled:create.gameChatEnabled, gameChatName:chatName.text, transport:vm.transportPolicy})
        }
    }
    Connections {
        target: lobby
        function onChanged() {
            if (vm.worlds.length && create.worldIndex < 0) {
                var requested = Number(vm.pendingOpenWorldPort || vm.worldPort || 0)
                var selected = vm.worlds.findIndex(function(world) { return Number(world.port) === requested })
                create.worldIndex = selected >= 0 ? selected : (vm.worlds.length === 1 ? 0 : -1)
                if (create.worldIndex >= 0) port.text = String(vm.worlds[create.worldIndex].port)
            }
        }
    }
}
