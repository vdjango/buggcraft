import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../shared" as Shared

ColumnLayout {
    id: connected
    property var vm: lobby.view
    property var record: vm.connections.find(function(c) { return c.id === vm.selected }) || ({state:"stopped", title:"房间", role:"client", detail:"", warning:""})
    property bool online: record.state === "online"
    property bool host: record.role === "host"
    property bool directJoin: record["public"] === true && record.requireInvite === false
    property bool ended: record.state === "stopped" || record.state === "error"
    property bool waiting: online && record.availability === "waiting"
    readonly property bool showPublicGuide: host && online && !waiting && !record["public"] && record.publicGuide === true
    property var game: record.game || ({})
    property bool preparing: !!record.preparing
    property string copiedKind: ""
    property string prepareSuggestionRoom: ""
    function fileSize(bytes) {
        return bytes >= 1048576 ? (bytes / 1048576).toFixed(1) + " MiB"
            : bytes >= 1024 ? (bytes / 1024).toFixed(1) + " KiB" : bytes + " B"
    }
    Connections {
        target: lobby
        ignoreUnknownSignals: true
        function onCopied(kind) { connected.copiedKind = kind; copiedTimer.restart() }
        function onRoomSettingsSaved() { roomSettings.close() }
        function onChanged() {
            if (!connected.host && connected.online && !connected.preparing && !!connected.record.compatibility &&
                    connected.prepareSuggestionRoom !== vm.selected) {
                connected.prepareSuggestionRoom = vm.selected
                preparePopup.open()
            }
        }
    }
    Timer { id: copiedTimer; interval: 2200; onTriggered: connected.copiedKind = "" }
    spacing: 7
    FriendInviteProgress { objectName: "room-friend-invite-progress"; flow: vm.friendInviteFlow || ({}); onAction: function(name, data) { lobby.act(name, data) } }
    Surface {
        objectName: "room-summary"
        Layout.fillWidth: true; implicitHeight: summary.implicitHeight + 24
        color: "#211d2b"; border.color: "#49415c"
        ColumnLayout {
            id: summary
            anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 12; spacing: 8
            RowLayout {
                Layout.fillWidth: true; spacing: 10
                ColumnLayout {
                    Layout.fillWidth: true; spacing: 2
                    CopyText {
                        objectName: "connection-heading"; Layout.fillWidth: true
                        text: connected.waiting ? (connected.host ? "等待开放世界" : "等待房主开放世界") : connected.online ? (connected.host ? "房间已创建" : "已加入房间") : connected.record.state === "error" ? "连接失败" : connected.record.state === "stopped" ? "已离开房间" : connected.record.state === "reconnecting" ? "正在重新连接…" : "正在连接房间…"
                        color: "#eee8fa"; font.pixelSize: 15; font.bold: true
                    }
                }
                ActionButton { objectName: "reopen-world"; visible: connected.waiting && connected.host; text: "重新选择世界"; primary: true; implicitHeight: 30; onClicked: lobby.act("reopenWorld", {}) }
                ActionButton {
                    objectName: "room-settings"; visible: connected.host && connected.online
                    text: "房间设置"; implicitHeight: 30; enabled: !vm.busy
                    onClicked: { lobby.act("dismissPublicGuide", {}); roomSettings.open() }
                    Shared.AttentionFrame { objectName: "room-public-guide-glow"; active: connected.showPublicGuide }
                }
            }
            RowLayout {
                objectName: "room-player-metrics"
                Layout.fillWidth: true; spacing: 16
                visible: connected.online
                CopyText {
                    objectName: "room-member-count"; font.pixelSize: 12; color: "#d8cfea"
                    text: "房间内 " + (typeof connected.record.members === "number" ? connected.record.members + " / " + connected.record.capacity + " 人" : "—")
                }
                CopyText {
                    objectName: "game-player-count"; font.pixelSize: 12; color: "#b5d3c4"
                    text: "游戏内 " + (typeof connected.record.game_players === "number" ? connected.record.game_players + " 人" : "—")
                }
                Item { Layout.fillWidth: true }
                CopyText {
                    objectName: "room-transport"; font.pixelSize: 11; color: "#b5d3c4"
                    text: connected.host ? (connected.record.transport === "auto" ? "P2P / 中转" : "节点中转") :
                        connected.record.transport === "p2p" ? "P2P 直连" : connected.record.transport === "relay" ? "节点中转" : "协商路径…"
                }
                CopyText {
                    objectName: "game-latency"; font.pixelSize: 12; color: "#bcb0d3"
                    text: "游戏延迟 " + (typeof connected.record.latency_ms === "number" ? connected.record.latency_ms + " ms" :
                        connected.record.latency_state === "timeout" ? "测量超时" :
                        connected.waiting ? "等待世界开放" : "测量中…") + (connected.host ? " · 本地" : "")
                    ToolTip.visible: latencyHover.hovered
                    ToolTip.text: "通过游戏连接发送 Minecraft 服务器列表 Ping/Pong；与游戏内玩家列表的统计可能不同。"
                    HoverHandler { id: latencyHover }
                }
            }
            CopyText {
                objectName: "room-access-guidance"
                Layout.fillWidth: true; font.pixelSize: 11
                text: connected.waiting ? (connected.host ? "进入单人世界，选择“对局域网开放”。" : "世界开放后即可进入游戏。") : connected.online ? (connected.host ? (connected.directJoin ? "好友可从大厅直接加入，保持世界开放即可。" : "复制邀请码发给好友，保持世界开放即可。") : "启动游戏，在多人游戏中进入房间。") : ""
                visible: text.length > 0
            }
            RowLayout {
                objectName: "room-connection-actions"
                visible: connected.online; Layout.fillWidth: true; spacing: 8
                CopyText {
                    objectName: "room-access-summary"
                    Layout.fillWidth: true; font.pixelSize: 11; color: "#a99eb6"
                    text: connected.host ? (connected.record["public"] ? connected.directJoin ? "公开房间 · 直接加入" : "公开房间 · 需要邀请码" : "私密房间 · 仅邀请好友") : "多人游戏中也可使用地址直连"
                }
                ActionButton {
                    objectName: "copy-invite"; visible: connected.host
                    text: connected.copiedKind === "invite" ? "已复制 ✓" : "复制邀请码"
                    primary: true
                    implicitHeight: 28; implicitWidth: 104
                    onClicked: lobby.act("copyInvite", {id:vm.selected})
                }
                ActionButton {
                    objectName: "copy-address"; visible: !connected.host; enabled: !connected.waiting
                    text: connected.copiedKind === "address" ? "已复制 ✓" : "复制游戏地址"
                    implicitHeight: 28; implicitWidth: 116
                    onClicked: lobby.act("copyAddress", {id:vm.selected})
                }
            }
        }
    }
    Surface {
        objectName: "room-public-guide"
        visible: connected.showPublicGuide
        Layout.fillWidth: true; implicitHeight: 48
        color: "#30263f"; border.color: "#a58ad7"
        RowLayout {
            anchors.fill: parent; anchors.margins: 9; spacing: 10
            CopyText { Layout.fillWidth: true; text: "让其他玩家在大厅看到这个房间？"; font.pixelSize: 12; color: "#eee2ff"; wrapMode: Text.Wrap }
            ActionButton {
                objectName: "room-public-guide-private"; text: "仅邀请好友"; quiet: true; implicitHeight: 28
                onClicked: lobby.act("dismissPublicGuide", {})
            }
            ActionButton {
                objectName: "room-public-guide-settings"; text: "去设置"; primary: true; implicitHeight: 28
                enabled: !vm.busy
                onClicked: { lobby.act("dismissPublicGuide", {}); roomSettings.open() }
            }
        }
    }
    CopyText { Layout.fillWidth: true; visible: connected.online && !!connected.record.warning; text: "版本提示：" + connected.record.warning; color: "#dfbd92"; font.pixelSize: 11 }
    Surface {
        objectName: "room-game-requirements"
        color: "#211d2b"; border.color: "#49415c"
        Layout.fillWidth: true
        visible: connected.online
        implicitHeight: requirements.implicitHeight + 16
        ColumnLayout {
            id: requirements
            anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 8
            spacing: 5
            RowLayout {
                Layout.fillWidth: true; spacing: 8
                CopyText {
                    objectName: "room-version-summary"; Layout.fillWidth: true
                    text: (connected.game.version || "读取中…") + "  ·  " +
                        ((connected.game.loader || "vanilla") === "vanilla" ? "原版" : connected.game.loader + " " + (connected.game.loader_version || "")) +
                        "  ·  " + (connected.game.mods_count || 0) + " 个模组"
                    font.pixelSize: 11; color: "#d8cfea"; elide: Text.ElideRight; wrapMode: Text.NoWrap
                }
                ActionButton {
                    objectName: "show-room-mods"; text: "模组列表"; implicitHeight: 27
                    onClicked: { lobby.act("loadMods", {}); modsPopup.open() }
                }
                ActionButton {
                    objectName: "room-quick-launch"; visible: !connected.host
                    text: connected.preparing ? "正在准备…" : connected.record.compatibility ? "准备配置并启动" : "快速启动"
                    primary: true; implicitHeight: 27
                    enabled: !connected.waiting && !connected.preparing && !vm.instanceLoading
                    onClicked: {
                        if (!connected.record.compatibility) lobby.act("launchRoom", {})
                        else if ((connected.game.mods_count || 0) > 0) preparePopup.open()
                        else lobby.act("prepareRoom", {})
                    }
                }
                ActionButton {
                    objectName: "room-select-configuration"
                    visible: !connected.host && !connected.record.compatibility && !connected.preparing
                    text: "选择配置"; implicitHeight: 27
                    onClicked: preparePopup.open()
                }
                ActionButton {
                    objectName: "host-start-game"; visible: connected.host && connected.waiting
                    text: vm.instanceLocked ? "游戏已运行" : "启动游戏"; primary: true; implicitHeight: 27
                    enabled: !vm.instanceLocked
                    onClicked: lobby.act("launchRoom", {})
                }
                ActionButton {
                    objectName: "host-change-configuration"; visible: connected.host && connected.waiting && !vm.instanceLocked
                    text: "更换配置"; implicitHeight: 27
                    onClicked: hostConfigPopup.open()
                }
            }
            CopyText {
                objectName: "room-compatibility"; Layout.fillWidth: true
                visible: !connected.host && !!connected.record.compatibility
                text: connected.record.compatibility
                color: "#dfbd92"; font.pixelSize: 11
            }
            CopyText {
                Layout.fillWidth: true; visible: !!connected.record.prepareStatus
                text: connected.record.prepareStatus || ""; font.pixelSize: 11
            }
            CopyText {
                Layout.fillWidth: true; visible: !!connected.record.loaderWarning
                text: connected.record.loaderWarning || ""; font.pixelSize: 11; color: "#dfbd92"
            }
            RowLayout {
                Layout.fillWidth: true; visible: connected.preparing && !!connected.record.prepareFile
                CopyText {
                    objectName: "room-download-file"; Layout.fillWidth: true
                    text: (connected.record.prepareIndex || 1) + "/" + (connected.record.prepareCount || 0) + "  " + (connected.record.prepareFile || "")
                    font.pixelSize: 11; wrapMode: Text.NoWrap; elide: Text.ElideMiddle
                }
                CopyText {
                    objectName: "room-download-bytes"; font.pixelSize: 11; color: "#b5d3c4"
                    text: connected.fileSize(connected.record.prepareFileDone || 0) + " / " + connected.fileSize(connected.record.prepareFileTotal || 0) + "  " + (connected.record.prepareSpeed || "")
                }
            }
            RowLayout {
                visible: connected.preparing; Layout.fillWidth: true
                ProgressBar {
                    objectName: "room-install-progress"; Layout.fillWidth: true
                    from: 0; to: Math.max(1, connected.record.prepareMaximum || 0)
                    value: connected.record.prepareProgress || 0
                    indeterminate: !(connected.record.prepareMaximum > 0)
                }
                ActionButton { objectName: "cancel-room-install"; text: "取消安装"; implicitHeight: 26; onClicked: lobby.act("cancelPreparation", {}) }
            }
        }
    }
    Popup {
        id: preparePopup
        objectName: "prepare-room-dialog"
        parent: Overlay.overlay
        anchors.centerIn: parent
        width: Math.min(430, parent.width - 40)
        modal: true; focus: true; padding: 16
        background: Rectangle { color: "#251f30"; border.color: "#7e699e"; radius: 7 }
        contentItem: ColumnLayout {
            spacing: 12
            CopyText { text: "准备匹配的游戏配置"; font.bold: true; color: "#f3efff" }
            InstancePicker { Layout.fillWidth: true }
            CopyText {
                Layout.fillWidth: true
                text: (connected.record.compatibility.indexOf("模组集合不一致") >= 0 ?
                    "房主使用 " + (connected.game.mods_count || 0) + " 个模组，你当前实例有 " + (vm.localModsCount || 0) + " 个，模组文件不完全一致。\n" : "当前游戏配置与房主要求不一致。\n") +
                    "可以全新安装匹配配置，或按文件校验补齐已有配置。启动器只会把缺少或不同的房主模组放入新的房间配置，原配置和存档会保留。"
            }
            CopyText { Layout.fillWidth: true; text: "模组来自房主，请仅在信任房主时安装。"; color: "#dfbd92"; font.pixelSize: 11 }
            RowLayout {
                Layout.fillWidth: true
                ActionButton {
                    objectName: "incremental-room-install"; text: "在已有配置中补齐"; enabled: !vm.instanceLoading
                    onClicked: { preparePopup.close(); lobby.act("prepareRoom", {mode:"existing"}) }
                }
                Item { Layout.fillWidth: true }
                ActionButton { objectName: "confirm-room-install"; text: "全新下载配置"; primary: true; onClicked: { preparePopup.close(); lobby.act("prepareRoom", {mode:"fresh"}) } }
            }
        }
    }
    Popup {
        id: hostConfigPopup
        parent: Overlay.overlay; anchors.centerIn: parent
        width: Math.min(430, parent.width - 40); padding: 16; modal: true; focus: true
        background: Rectangle { color: "#251f30"; border.color: "#7e699e"; radius: 7 }
        contentItem: ColumnLayout {
            spacing: 12
            CopyText { text: "更换房间游戏配置"; font.bold: true; color: "#f3efff" }
            InstancePicker { Layout.fillWidth: true }
            CopyText { Layout.fillWidth: true; text: "房间版本与模组清单将同步更新。"; font.pixelSize: 11 }
            ActionButton { Layout.alignment: Qt.AlignRight; text: "完成"; onClicked: hostConfigPopup.close() }
        }
    }
    Popup {
        id: modsPopup
        objectName: "room-mods-dialog"
        parent: Overlay.overlay; anchors.centerIn: parent
        width: Math.min(620, parent.width - 40)
        height: Math.min(Math.max(230, 150 + (connected.record.mods || []).length * 64), 500, parent.height - 60)
        modal: true; focus: true; padding: 18
        background: Rectangle { color: "#251f30"; border.color: "#7e699e"; radius: 7 }
        contentItem: ColumnLayout {
            objectName: "room-mods-body"
            spacing: 12
            RowLayout {
                Layout.fillWidth: true
                CopyText { Layout.fillWidth: true; text: "房间模组（" + (connected.game.mods_count || 0) + "）"; font.bold: true; color: "#f3efff" }
                ActionButton { text: "关闭"; implicitHeight: 28; onClicked: modsPopup.close() }
            }
            CopyText {
                Layout.fillWidth: true; color: "#bcb0d3"; font.pixelSize: 11
                text: "Minecraft " + (connected.game.version || "—") + "  ·  " + (connected.game.loader || "vanilla") + " " + (connected.game.loader_version || "")
            }
            Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: "#544763" }
            CopyText { Layout.fillWidth: true; visible: !!connected.record.modError; text: connected.record.modError || ""; color: "#ffb5bb" }
            ListView {
                objectName: "room-mods-list"; Layout.fillWidth: true; Layout.fillHeight: true; clip: true
                model: connected.record.mods || []
                ScrollBar.vertical: ScrollBar {}
                spacing: 6
                delegate: Rectangle {
                    required property var modelData
                    width: ListView.view.width - 12; height: 58; radius: 5
                    color: modelData.state === "downloading" ? "#383049" : "#2c2538"
                    border.color: modelData.state === "downloading" ? "#9b88c7" : "#493d5b"
                    RowLayout {
                        anchors.fill: parent; anchors.margins: 10; spacing: 12
                        Rectangle {
                            implicitWidth: 30; implicitHeight: 30; radius: 5; color: "#514165"
                            CopyText { anchors.centerIn: parent; text: modelData.state === "verified" ? "✓" : "JAR"; color: modelData.state === "verified" ? "#bce1c9" : "#ddd2ed"; font.pixelSize: modelData.state === "verified" ? 18 : 9 }
                        }
                        ColumnLayout {
                            Layout.fillWidth: true; spacing: 3
                            CopyText { Layout.fillWidth: true; text: modelData.name; color: "#eee8fb"; font.pixelSize: 12; wrapMode: Text.NoWrap; elide: Text.ElideMiddle }
                            CopyText { text: connected.fileSize(modelData.size); font.pixelSize: 10; color: "#bcb0d3" }
                        }
                        CopyText {
                            text: modelData.state === "verified" ? "已校验" : modelData.state === "failed" ? "失败" : modelData.state === "downloading" ? "下载中" : modelData.state === "pending" ? "等待下载" : "房主共享"
                            color: modelData.state === "verified" ? "#bce1c9" : "#c4b7f1"; font.pixelSize: 11
                        }
                    }
                }
                CopyText { anchors.centerIn: parent; text: connected.record.modLoading ? "正在读取完整模组清单…" : connected.record.modError ? "模组清单读取失败，请关闭后重试" : "原版房间，无需安装模组"; visible: !(connected.record.mods || []).length }
            }
            CopyText { Layout.fillWidth: true; text: "模组来自房主，下载完成后核对文件完整性。安装明细可在启动器下载记录中查看。"; color: "#aaa1b5"; font.pixelSize: 10 }
        }
    }
    Surface {
        objectName: "room-chat"; visible: connected.online
        Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumHeight: 145
        color: "#211d2b"; border.color: "#49415c"
        ColumnLayout {
            anchors.fill: parent; anchors.margins: 9; spacing: 6
            RowLayout {
                Layout.fillWidth: true
                CopyText { text: "房间聊天"; color: "#eee8fb"; font.bold: true; font.pixelSize: 13 }
                Item { Layout.fillWidth: true }
                CopyText { objectName: "room-chat-state"; text: vm.chatState; color: vm.chatState === "在线" ? "#a7d5b7" : "#d2c2e5"; font.pixelSize: 11 }
            }
            CopyText {
                objectName: "game-chat-bridge-status"; Layout.fillWidth: true
                text: vm.bridgeStatus; color: "#b5adc0"; font.pixelSize: 11
                wrapMode: Text.NoWrap; maximumLineCount: 1; elide: Text.ElideRight
                ToolTip.visible: bridgeHover.hovered
                ToolTip.text: vm.bridgeStatus
                HoverHandler { id: bridgeHover }
            }
            ListView {
                id: messages; objectName: "room-chat-messages"
                Layout.fillWidth: true; Layout.fillHeight: true; clip: true; spacing: 5
                model: vm.chatMessages; ScrollBar.vertical: ScrollBar {}
                property bool followEnd: true
                onMovementEnded: followEnd = atYEnd
                delegate: CopyText {
                    required property var modelData
                    width: messages.width - 12
                    text: "[" + (modelData.source === "game" ? "游戏" : "大厅") + "] " + modelData.sender +
                          (modelData.source !== "game" && modelData.identityLabel ? "（" + modelData.identityLabel + "）" : "") + "：" + modelData.text
                    textFormat: Text.PlainText
                    color: modelData.source === "game" ? "#bce1c9" : "#ddd2ed"
                    font.pixelSize: 12; wrapMode: Text.Wrap
                }
                onCountChanged: if (followEnd) Qt.callLater(function() { positionViewAtEnd() })
                CopyText { anchors.centerIn: parent; visible: messages.count === 0; text: "在这里和房间里的朋友聊天"; color: "#aaa1b5"; font.pixelSize: 12 }
            }
            RowLayout {
                Layout.fillWidth: true; spacing: 7
                InputField {
                    id: draft; objectName: "room-chat-input"; Layout.fillWidth: true
                    text: vm.chatDraft || ""
                    implicitHeight: 30; maximumLength: 256; placeholderText: "输入房间消息，Enter 发送"
                    enabled: !vm.chatSending
                    onTextEdited: lobby.act("chatDraft", {text:text})
                    onAccepted: sendChat()
                    function sendChat() {
                        if (!text.trim() || !connected.online || vm.chatState !== "在线" || vm.chatSending) return
                        lobby.act("sendChat", {text:text})
                    }
                }
                ActionButton {
                    objectName: "room-chat-send"; text: vm.chatSending ? "发送中" : "发送"; primary: true
                    implicitWidth: 66; implicitHeight: 30
                    enabled: draft.text.trim().length > 0 && vm.chatState === "在线" && !vm.chatSending
                    onClicked: draft.sendChat()
                }
            }
            CopyText { objectName: "room-chat-error"; Layout.fillWidth: true; visible: !!vm.chatError; text: vm.chatError; color: "#ffb5bb"; font.pixelSize: 11 }
        }
    }
    Item { Layout.fillHeight: true; visible: !connected.online }
    Popup {
        id: roomSettings; objectName: "room-settings-dialog"
        parent: Overlay.overlay; anchors.centerIn: parent
        width: Math.min(420, parent.width - 40); padding: 16; modal: true; focus: true
        closePolicy: vm.busy ? Popup.NoAutoClose : Popup.CloseOnEscape | Popup.CloseOnPressOutside
        onOpened: {
            roomTitle.text = connected.record.title || ""
            access.currentIndex = !connected.record["public"] ? 0 : connected.record.requireInvite ? 1 : 2
            allowModTransfer.checked = !!connected.record.allowModTransfer
        }
        background: Rectangle { color: "#211d2b"; border.color: "#7e699e" }
        contentItem: ColumnLayout {
            spacing: 12
            CopyText { text: "房间设置"; color: "#eee8fa"; font.pixelSize: 15; font.bold: true }
            GridLayout {
                Layout.fillWidth: true; columns: 2; columnSpacing: 12; rowSpacing: 12
                CopyText { text: "房间名称"; Layout.preferredWidth: 64 }
                InputField { id: roomTitle; objectName: "room-settings-title"; Layout.fillWidth: true; maximumLength: 80; enabled: !vm.busy }
                CopyText { text: "加入方式"; Layout.preferredWidth: 64 }
                ChoiceBox {
                    id: access; objectName: "room-settings-access"; Layout.fillWidth: true; enabled: !vm.busy
                    model: ["仅邀请好友", "大厅公开，凭邀请码加入", "大厅公开，直接加入"]
                }
            }
            CheckBox {
                id: allowModTransfer; objectName: "allow-mod-transfer"
                text: "允许房间成员从本机接收模组"
                enabled: !vm.busy; checked: false
            }
            CopyText {
                Layout.fillWidth: true
                text: "资源库找不到房主模组时，启动器会尝试从房间传输；关闭后只会使用公开资源。"
                font.pixelSize: 11; color: "#bcb0d3"; wrapMode: Text.Wrap
            }
            CopyText { Layout.fillWidth: true; visible: !!vm.error; text: vm.error || ""; color: "#e8b3b3"; font.pixelSize: 11 }
            RowLayout {
                Layout.fillWidth: true; spacing: 8
                ActionButton {
                    objectName: "room-settings-world"; text: "更换世界"; enabled: !vm.busy
                    onClicked: { roomSettings.close(); lobby.act("reopenWorld", {}) }
                }
                Item { Layout.fillWidth: true }
                ActionButton { text: "取消"; enabled: !vm.busy; onClicked: roomSettings.close() }
                ActionButton {
                    objectName: "save-room-settings"; text: vm.busy ? "保存中…" : "保存"; primary: true
                    enabled: !vm.busy && roomTitle.text.trim().length > 0
                    onClicked: lobby.act("updateRoomSettings", {title:roomTitle.text.trim(), "public":access.currentIndex > 0, requireInvite:access.currentIndex !== 2, allowModTransfer:allowModTransfer.checked})
                }
            }
        }
    }
}
