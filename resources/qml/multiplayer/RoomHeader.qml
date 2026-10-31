import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../shared" as Shared

Surface {
    id: header
    property var roomView
    signal settingsRequested()
    signal preparationRequested()
    Layout.fillWidth: true; implicitHeight: body.implicitHeight + 16
    color: "#211d2b"; border.color: "#49415c"
    ColumnLayout {
        id: body
        anchors.fill: parent; anchors.margins: 8; spacing: 4
        RowLayout {
            Layout.fillWidth: true; spacing: 8
            Rectangle { implicitWidth: 6; implicitHeight: 6; radius: 3; color: header.roomView.waiting ? "#c1a2e1" : header.roomView.online ? "#aad4b9" : "#e3b48f" }
            CopyText {
                objectName: "connection-heading"; Layout.fillWidth: true
                text: header.roomView.waiting ? "准备房间 · 等待世界开放" : header.roomView.online ? "世界已开放" : header.roomView.record.state === "reconnecting" ? "正在重新连接…" : "正在连接房间…"
                color: "#eee8fa"; font.pixelSize: 14; font.bold: true; wrapMode: Text.NoWrap; elide: Text.ElideRight
                HoverHandler { id: statusHover }
                ToolTip.visible: statusHover.hovered && header.roomView.waiting
                ToolTip.text: header.roomView.host ? "朋友可以先准备，世界开放后自动连接。" : "先同步游戏，等待房主开放世界后自动连接。"
            }
            ActionButton {
                objectName: "room-settings"; visible: !!header.roomView.record.isManager || header.roomView.host && !header.roomView.record.lobby
                text: "房间设置"; implicitHeight: 28; enabled: header.roomView.online && !lobby.view.busy
                onClicked: { lobby.act("dismissPublicGuide", {}); header.settingsRequested() }
                Shared.AttentionFrame { objectName: "room-public-guide-glow"; active: header.roomView.showPublicGuide }
            }
            ActionButton {
            objectName: "room-submit-diagnostics"; text: "反馈问题"; quiet: true; implicitHeight: 28
                enabled: !!lobby.view.socialReady && !lobby.view.busy
                Accessible.name: "提交当前房间的联机诊断"
                onClicked: lobby.act("submitDiagnostics", {})
            }
            ActionButton {
                objectName: "room-info-toggle"; text: header.roomView.infoExpanded ? "收起信息" : "房间信息"
                quiet: true; implicitHeight: 28
                Accessible.name: header.roomView.infoExpanded ? "收起房间信息" : "展开房间信息"
                onClicked: header.roomView.infoExpanded = !header.roomView.infoExpanded
            }
            ActionButton {
                objectName: "room-quick-launch"; visible: !header.roomView.host && header.roomView.online
                text: header.roomView.preparing ? "正在准备…" : header.roomView.record.prepareFailed ? "重试下载" : header.roomView.record.compatibility ? "同步安装" : header.roomView.waiting ? "启动到主菜单" : "进入游戏"
                primary: true; implicitHeight: 28
                enabled: !header.roomView.preparing && (!lobby.view.instanceLoading || !!header.roomView.record.preparedSource)
                onClicked: {
                    if (header.roomView.record.prepareFailed) lobby.act("prepareRoom", {mode:header.roomView.record.prepareMode || "fresh"})
                    else if (!header.roomView.record.compatibility) lobby.act("launchRoom", {})
                    else if ((header.roomView.game.mods_count || 0) > 0) header.preparationRequested()
                    else lobby.act("prepareRoom", {})
                }
            }
            ActionButton {
                objectName: "host-start-game"; visible: header.roomView.host && header.roomView.waiting
                text: lobby.view.instanceLocked ? "游戏已运行" : "启动游戏"; primary: true; implicitHeight: 28
                enabled: !lobby.view.instanceLocked
                onClicked: lobby.act("launchRoom", {})
            }
        }
        RowLayout {
            Layout.fillWidth: true; spacing: 12; visible: header.roomView.infoExpanded
        CopyText {
            objectName: "room-owner-node"; Layout.fillWidth: true
            visible: !!header.roomView.record.nodeName || !!header.roomView.record.nodeRegion
            text: (header.roomView.record.nodeName || "未知节点") +
                (header.roomView.record.nodeRegion ? " · " + header.roomView.record.nodeRegion : "")
            color: "#a9c2be"; font.pixelSize: 10; wrapMode: Text.NoWrap; elide: Text.ElideRight
        }
            CopyText {
                objectName: "room-node-latency"
                text: "到联机节点 " + (header.roomView.online && typeof header.roomView.record.nodeLatencyMs === "number" ? Math.round(header.roomView.record.nodeLatencyMs) + " ms" : "—")
                font.pixelSize: 11; color: "#b9adca"
            }
            CopyText {
                objectName: "room-host-latency"
                text: "到房主 " + (header.roomView.online && typeof header.roomView.record.latency_ms === "number" ? header.roomView.record.latency_ms + " ms" : "—") + (header.roomView.host ? " · 本机" : "")
                font.pixelSize: 11; color: "#b9adca"
            }
            HeaderAction {
                text: "?"; iconSize: 13; implicitHeight: 20; implicitWidth: 22
                label: "到联机节点：你到本房间节点的往返时间。到房主：沿当前游戏线路到房主游戏的往返时间，包含游戏响应；直接连接时不经过中转节点，中转时包含两段线路。— 表示尚未测到。"
            }
            ActionButton { objectName: "copy-address"; visible: !header.roomView.host && !header.roomView.waiting; text: header.roomView.copiedKind === "address" ? "已复制 ✓" : "游戏地址"; quiet: true; implicitHeight: 22; onClicked: lobby.act("copyAddress", {id:lobby.view.selected}) }
            ActionButton { objectName: "room-details"; text: "连接详情"; quiet: true; implicitHeight: 22; onClicked: details.open() }
        }
        RowLayout {
            Layout.fillWidth: true; visible: header.roomView.waiting && !!header.roomView.record.worldChoiceRequired
            CopyText {
                objectName: "room-access-guidance"; Layout.fillWidth: true; font.pixelSize: 11; color: "#a99eb6"
                text: header.roomView.host ? "朋友可以先准备，世界开放后自动连接。" : "先同步游戏，等待房主开放世界。"
                wrapMode: Text.NoWrap; elide: Text.ElideRight
            }
            ActionButton { objectName: "choose-detected-world"; visible: header.roomView.host && !!header.roomView.record.worldChoiceRequired; text: "选择世界"; quiet: true; implicitHeight: 22; onClicked: lobby.act("reopenWorld", {}) }
        }
    }
    Popup {
        id: details; objectName: "room-details-popup"; parent: Overlay.overlay; anchors.centerIn: parent
        width: Math.min(340, parent.width - 40); padding: 16; modal: true; focus: true
        background: Rectangle { color: "#251f30"; radius: 7; border.color: "#665278" }
        contentItem: ColumnLayout {
            spacing: 12
            CopyText { text: "连接详情"; font.bold: true }
            CopyText { objectName: "room-member-count"; text: "房间内 " + (typeof header.roomView.record.members === "number" ? header.roomView.record.members + " / " + header.roomView.record.capacity + " 人" : "—"); font.pixelSize: 12 }
            CopyText { objectName: "game-player-count"; text: "游戏内 " + (typeof header.roomView.record.game_players === "number" ? header.roomView.record.game_players + " 人" : "—"); font.pixelSize: 12 }
            CopyText { objectName: "room-transport"; text: header.roomView.host ? "世界由本机提供" : header.roomView.record.transport === "p2p" ? "P2P 直连" : "节点中转"; font.pixelSize: 12 }
            CopyText { objectName: "game-latency"; text: "游戏延迟 " + (typeof header.roomView.record.latency_ms === "number" ? header.roomView.record.latency_ms + " ms" : "—") + (header.roomView.host ? " · 本地" : ""); font.pixelSize: 12 }
            CopyText { objectName: "room-access-summary"; text: header.roomView.record["public"] ? header.roomView.directJoin ? "公开房间 · 直接加入" : "公开房间 · 需要邀请码" : "私密房间 · 仅邀请好友"; font.pixelSize: 12 }
            ActionButton { Layout.alignment: Qt.AlignRight; text: "关闭"; onClicked: details.close() }
        }
    }
}
