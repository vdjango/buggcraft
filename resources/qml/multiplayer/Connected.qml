import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

ColumnLayout {
    id: connected
    property var vm: lobby.view
    property var record: vm.connections.find(function(c) { return c.id === vm.selected }) || ({state:"stopped", title:"房间", role:"client", detail:"", warning:""})
    property bool online: record.state === "online"
    property bool host: record.role === "host"
    property bool directJoin: record["public"] === true && record.requireInvite === false
    property bool ended: record.state === "stopped" || record.state === "error"
    property bool waiting: online && record.availability === "waiting"
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
    Surface {
        Layout.fillWidth: true; implicitHeight: summary.implicitHeight + 18
        color: connected.online ? "#242c2c" : "#252431"
        ColumnLayout {
            id: summary
            anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 9; spacing: 5
            RowLayout {
                Layout.fillWidth: true; spacing: 10
                ColumnLayout {
                    Layout.fillWidth: true; spacing: 2
                    CopyText {
                        objectName: "connection-heading"; Layout.fillWidth: true
                        text: connected.waiting ? (connected.host ? "世界暂未开放，房间为你保留" : "房主不在游戏内，请等待") : connected.online ? (connected.host ? (connected.directJoin ? "房间已公开，朋友可直接加入" : "房间已创建，邀请朋友吧") : "连接成功，去游戏里见吧") : connected.record.state === "error" ? "连接失败" : connected.record.state === "stopped" ? "已离开房间" : connected.record.state === "reconnecting" ? "连接中断，正在重新连接…" : "正在连接房间…"
                        color: connected.online ? "#c1e8d2" : "#e1d5f0"; font.pixelSize: 14; font.bold: true
                    }
                }
                ActionButton { objectName: "reopen-world"; visible: connected.waiting && connected.host; text: "重新选择世界"; primary: true; implicitHeight: 30; onClicked: lobby.act("reopenWorld", {}) }
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
                text: connected.waiting ? (connected.host ? "回到世界并对局域网开放；端口变化时点“重新选择世界”，邀请码不用换。" : "房主恢复世界后会通知你，请稍候再进入游戏。") : connected.online ? (connected.host ? (connected.directJoin ? "朋友可从大厅直接加入，无需邀请码；请保持游戏世界对局域网开放。" : connected.record["public"] ? "大厅可见，加入需要邀请码；把邀请码发给朋友并保持世界开放。" : "把邀请码发给朋友，并保持游戏世界对局域网开放。") : "打开游戏 → 多人游戏 → 选择房间；未显示时复制地址直接连接。") : "连接完成后会显示下一步。"
            }
            RowLayout {
                objectName: "room-connection-actions"
                visible: connected.online; Layout.fillWidth: true; spacing: 8
                CopyText {
                    Layout.fillWidth: true; font.pixelSize: 11; color: "#a99eb6"
                    text: connected.host ? "邀请朋友" : "游戏内未找到房间？可用地址直接连接"
                }
                ActionButton {
                    objectName: "copy-invite"; visible: connected.host
                    text: connected.copiedKind === "invite" ? "已复制 ✓" : "复制邀请码"
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
    CopyText { Layout.fillWidth: true; visible: connected.online && !!connected.record.warning; text: "版本提示：" + connected.record.warning; color: "#dfbd92"; font.pixelSize: 11 }
    Surface {
        objectName: "room-game-requirements"
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
                    text: "Minecraft " + (connected.game.version || "读取中…") + "  ·  " +
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
                text: connected.record.compatibility + "。可以选择已有配置，或新建隔离配置自动安装。"
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
                    "可以创建一个独立配置，启动器会自动安装房主共享的模组并校验文件。现有实例、存档和模组会保留。"
            }
            CopyText { Layout.fillWidth: true; text: "模组来自房主，请仅在信任房主时安装。"; color: "#dfbd92"; font.pixelSize: 11 }
            RowLayout {
                Layout.fillWidth: true
                ActionButton { text: "选择已有配置"; onClicked: preparePopup.close() }
                Item { Layout.fillWidth: true }
                ActionButton { objectName: "confirm-room-install"; text: "创建匹配配置并下载"; primary: true; onClicked: { preparePopup.close(); lobby.act("prepareRoom", {}) } }
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
            CopyText { Layout.fillWidth: true; text: "选择与首页同步，房间版本和模组清单也会自动通知已加入的玩家。"; font.pixelSize: 11 }
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
        color: "#a91c1a25"
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
                wrapMode: Text.Wrap; maximumLineCount: 2; elide: Text.ElideRight
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
    CopyText { Layout.fillWidth: true; text: connected.waiting ? "房间聊天仍可使用；世界恢复后会自动通知，无需反复重连。" : "返回大厅前会确认断开连接；关闭窗口仍保留联机。"; font.pixelSize: 11 }
}
