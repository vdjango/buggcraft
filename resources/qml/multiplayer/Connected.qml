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
    property int panel: 1
    property string copiedKind: ""
    property string prepareSuggestionRoom: ""
    property string logRequestSeen: ""
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
            connected.checkLogConsent()
            if (!connected.host && connected.online && !connected.preparing && !!connected.record.compatibility &&
                    connected.prepareSuggestionRoom !== vm.selected) {
                connected.prepareSuggestionRoom = vm.selected
                preparePopup.open()
            }
        }
    }
    function checkLogConsent() {
        var request = ((connected.record.lobby || {}).logs || {}).request
        if (request && request.id !== logRequestSeen) {
            logRequestSeen = request.id
            logConsent.open()
        }
        if (!request) logConsent.close()
    }
    onRecordChanged: Qt.callLater(checkLogConsent)
    Timer { id: copiedTimer; interval: 2200; onTriggered: connected.copiedKind = "" }
    spacing: 7
    FriendInviteProgress { objectName: "room-friend-invite-progress"; flow: vm.friendInviteFlow || ({}); onAction: function(name, data) { lobby.act(name, data) } }
    RoomHeader {
        objectName: "room-summary"; roomView: connected
        onSettingsRequested: roomSettings.open()
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
                    text: connected.preparing ? "正在准备…" : connected.record.prepareFailed ? "重试下载" : connected.record.compatibility ? "同步安装" : connected.waiting ? "启动到主菜单" : "进入游戏"
                    primary: true; implicitHeight: 27
                    enabled: !connected.preparing && (!vm.instanceLoading || !!connected.record.preparedSource)
                    onClicked: {
                        if (connected.record.prepareFailed) lobby.act("prepareRoom", {mode: connected.record.prepareMode || "fresh"})
                        else if (!connected.record.compatibility) lobby.act("launchRoom", {})
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
                    objectName: "host-change-configuration"; visible: connected.host && connected.waiting && !vm.instanceLocked && (!connected.record.lobby || connected.record.isManager)
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
                    text: ((connected.record.prepareCount || 0) > 0 ? connected.record.prepareIndex + "/" + connected.record.prepareCount + "  " : "") + (connected.record.prepareFile || "")
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
            CopyText { Layout.fillWidth: true; text: "更新后，正在准备的玩家需要重新同步。"; font.pixelSize: 11 }
            ActionButton { objectName: "confirm-room-configuration"; Layout.alignment: Qt.AlignRight; text: "更新房间"; primary: true; enabled: !vm.instanceLoading && !!vm.version; onClicked: { lobby.act("syncRoomVersion", {}); hostConfigPopup.close() } }
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
    RowLayout {
        visible: connected.online; Layout.fillWidth: true; spacing: 6
        ActionButton { objectName: "room-tab-chat"; text: "聊天"; primary: connected.panel === 1; quiet: connected.panel !== 1; implicitHeight: 28; onClicked: connected.panel = 1 }
        ActionButton { objectName: "room-tab-members"; text: "成员"; primary: connected.panel === 0; quiet: connected.panel !== 0; implicitHeight: 28; onClicked: connected.panel = 0 }
        ActionButton { objectName: "room-tab-install"; text: "安装日志"; primary: connected.panel === 2; quiet: connected.panel !== 2; implicitHeight: 28; onClicked: connected.panel = 2 }
        Item { Layout.fillWidth: true }
        ActionButton {
            objectName: "revoke-room-log-access"; visible: !!(((connected.record.lobby || {}).logs || {}).sharing)
            text: "停止共享日志"; quiet: true; implicitHeight: 28
            onClicked: lobby.act("revokeLogAccess", {})
        }
    }
    StackLayout {
        Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumHeight: 150
        visible: connected.online; currentIndex: connected.panel
        Surface {
            Layout.fillWidth: true; Layout.fillHeight: true; color: "#211d2b"; border.color: "#49415c"
            RoomMembers { anchors.fill: parent; anchors.margins: 10; record: connected.record; onLogsRequested: remoteLogs.open() }
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
        Surface {
            Layout.fillWidth: true; Layout.fillHeight: true; color: "#211d2b"; border.color: "#49415c"
            RoomInstallLog { anchors.fill: parent; anchors.margins: 10; record: connected.record }
        }
    }
    Item { Layout.fillHeight: true; visible: !connected.online }
    Popup {
        id: logConsent; objectName: "room-log-consent"; parent: Overlay.overlay; anchors.centerIn: parent
        width: Math.min(390, parent.width - 40); padding: 18; modal: true; focus: true
        background: Rectangle { color: "#251f30"; border.color: "#7e699e"; radius: 7 }
        contentItem: ColumnLayout {
            spacing: 14
            CopyText { text: "允许房主查看安装日志？"; font.bold: true; font.pixelSize: 15 }
            CopyText {
                Layout.fillWidth: true; font.pixelSize: 12; wrapMode: Text.Wrap
                text: ((((connected.record.lobby || {}).logs || {}).request || {}).name || "房主") +
                    " 希望协助排查游戏安装和模组问题。允许后，会共享本次房间的安装日志。你随时可以停止共享，退出房间或转让房主后授权自动失效。"
            }
            RowLayout {
                Item { Layout.fillWidth: true }
                ActionButton { objectName: "room-log-deny"; text: "暂不允许"; onClicked: { lobby.act("answerLogRequest", {request:connected.logRequestSeen, allow:false}); logConsent.close() } }
                ActionButton { objectName: "room-log-allow"; text: "允许本次共享"; primary: true; onClicked: { lobby.act("answerLogRequest", {request:connected.logRequestSeen, allow:true}); logConsent.close() } }
            }
        }
    }
    Popup {
        id: remoteLogs; objectName: "room-remote-log-popup"; parent: Overlay.overlay; anchors.centerIn: parent
        width: Math.min(640, parent.width - 32); height: Math.min(420, parent.height - 40)
        padding: 15; modal: true; focus: true
        background: Rectangle { color: "#251f30"; border.color: "#7e699e"; radius: 7 }
        contentItem: ColumnLayout {
            spacing: 10
            RowLayout {
                Layout.fillWidth: true
                CopyText { Layout.fillWidth: true; text: (connected.record.remoteLogName || "玩家") + " · 安装日志"; font.bold: true }
                ActionButton { objectName: "close-remote-log"; text: "关闭"; implicitHeight: 28; onClicked: remoteLogs.close() }
            }
            CopyText { Layout.fillWidth: true; text: connected.record.remoteLogMember ? "玩家已授权共享，可协助排查安装问题" : "玩家尚未授权或已停止共享"; font.pixelSize: 11; color: "#bcb0d3" }
            RoomInstallLog { Layout.fillWidth: true; Layout.fillHeight: true; remote: true; record: ({prepareLogs:connected.record.remoteLogs || []}) }
        }
        Timer { interval: 3500; running: remoteLogs.visible && !!connected.record.remoteLogMember && connected.online; repeat: true; onTriggered: lobby.act("viewMemberLogs", {}) }
    }
    Popup {
        id: roomSettings; objectName: "room-settings-dialog"
        parent: Overlay.overlay; anchors.centerIn: parent
        width: Math.min(420, parent.width - 40); padding: 16; modal: true; focus: true
        closePolicy: vm.busy ? Popup.NoAutoClose : Popup.CloseOnEscape | Popup.CloseOnPressOutside
        onOpened: {
            roomTitle.text = connected.record.title || ""
            access.currentIndex = !connected.record["public"] ? 0 : connected.record.requireInvite ? 1 : 2
            allowModTransfer.checked = !!connected.record.allowModTransfer
            modTransferLimit.currentIndex = [128, 256, 512, 1024, 2048, 5120].indexOf(connected.record.modTransferLimitKib || 512)
            if (modTransferLimit.currentIndex < 0) modTransferLimit.currentIndex = 2
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
                visible: connected.host; enabled: !vm.busy; checked: false
            }
            RowLayout {
                visible: connected.host; Layout.fillWidth: true; spacing: 10
                CopyText { text: "房主上传限速"; Layout.preferredWidth: 96 }
                ChoiceBox {
                    id: modTransferLimit; objectName: "mod-transfer-limit"; Layout.fillWidth: true
                    model: ["128 KiB/s", "256 KiB/s", "512 KiB/s", "1 MiB/s", "2 MiB/s", "5 MiB/s"]
                    enabled: !vm.busy && allowModTransfer.checked
                }
            }
            CopyText {
                Layout.fillWidth: true
                text: "优先从下载源获取文件，缺少的文件仅在直连成功后向房主获取。限速按房主所有玩家合计计算。"
                font.pixelSize: 11; color: "#bcb0d3"; wrapMode: Text.Wrap
            }
            CopyText { Layout.fillWidth: true; visible: !!vm.error; text: vm.error || ""; color: "#e8b3b3"; font.pixelSize: 11 }
            RowLayout {
                Layout.fillWidth: true; spacing: 8
                ActionButton {
                    objectName: "room-settings-world"; visible: connected.host; text: "更换世界"; enabled: !vm.busy
                    onClicked: { roomSettings.close(); lobby.act("reopenWorld", {}) }
                }
                Item { Layout.fillWidth: true }
                ActionButton { text: "取消"; enabled: !vm.busy; onClicked: roomSettings.close() }
                ActionButton {
                    objectName: "save-room-settings"; text: vm.busy ? "保存中…" : "保存"; primary: true
                    enabled: !vm.busy && roomTitle.text.trim().length > 0
                    onClicked: lobby.act("updateRoomSettings", {title:roomTitle.text.trim(), "public":access.currentIndex > 0, requireInvite:access.currentIndex !== 2, allowModTransfer:allowModTransfer.checked, modTransferLimitKib:[128, 256, 512, 1024, 2048, 5120][modTransferLimit.currentIndex]})
                }
            }
        }
    }
}
