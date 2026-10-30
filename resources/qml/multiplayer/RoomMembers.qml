import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

ColumnLayout {
    id: members
    property var record: ({})
    property var snapshot: record.lobby || ({})
    // Older bridge snapshots only carried the stable role ids. Normalize the
    // rows at the presentation boundary so the manager is still visible on
    // both host and guest clients while newer nodes can keep sending flags.
    property var memberRows: {
        var rows = members.snapshot.members || []
        var managerId = members.snapshot.manager_id || ""
        var providerId = members.snapshot.provider_id || ""
        return rows.filter(function(row) { return row.online !== false }).map(function(row) {
            var copy = {}
            for (var key in row) copy[key] = row[key]
            copy.manager = !!row.manager || (!!managerId && row.id === managerId)
            copy.provider = !!row.provider || (!!providerId && row.id === providerId)
            return copy
        })
    }
    property var selection: ({})
    property string operation: ""
    signal logsRequested()
    spacing: 8
    RowLayout {
        Layout.fillWidth: true
        CopyText { text: "成员"; font.pixelSize: 13; font.bold: true; color: "#eee8fa" }
        CopyText {
            objectName: "room-ready-count"; color: "#b5d3c4"; font.pixelSize: 11
            text: members.snapshot.online !== undefined ? members.snapshot.ready + " / " + members.snapshot.online + " 已准备" : ""
        }
        Item { Layout.fillWidth: true }
        ActionButton { objectName: "room-blocked-members"; text: "移出记录"; quiet: true; implicitHeight: 26; visible: !!members.record.isManager && (members.snapshot.blocked || []).length > 0; onClicked: blocked.open() }
    }
    Surface {
        Layout.fillWidth: true; implicitHeight: offerRow.implicitHeight + 18
        visible: !!members.snapshot.transfer
        color: "#30263f"; border.color: "#76628f"
        RowLayout {
            id: offerRow; anchors.fill: parent; anchors.margins: 9
            CopyText { Layout.fillWidth: true; font.pixelSize: 11; text: (members.snapshot.transfer || {}).to === members.snapshot.self_id ? "房主邀请你接管房间" : "等待对方接受房主转让…" }
            ActionButton { objectName: "room-owner-decline"; text: "拒绝"; implicitHeight: 26; visible: (members.snapshot.transfer || {}).to === members.snapshot.self_id; onClicked: lobby.act("answerOwner", {offer:members.snapshot.transfer.id, accept:false}) }
            ActionButton { objectName: "room-owner-accept"; text: "接受"; primary: true; implicitHeight: 26; visible: (members.snapshot.transfer || {}).to === members.snapshot.self_id; onClicked: lobby.act("answerOwner", {offer:members.snapshot.transfer.id, accept:true}) }
            ActionButton { objectName: "room-owner-cancel"; text: "取消转让"; implicitHeight: 26; visible: !!members.record.isManager; onClicked: lobby.act("cancelOwner", {}) }
        }
    }
    ListView {
        id: list; objectName: "room-members-list"
        Layout.fillWidth: true; Layout.fillHeight: true; clip: true; spacing: 5
        model: members.memberRows
        ScrollBar.vertical: ScrollBar {}
        delegate: Rectangle {
            id: memberRow
            required property var modelData
            objectName: "room-member-" + modelData.id
            width: list.width - 12; height: modelData.total > 0 && modelData.state !== "ready" && modelData.online ? 60 : 48
            radius: 6; color: modelData.id === members.snapshot.self_id ? "#30283e" : "#272230"
            border.color: modelData.id === members.snapshot.self_id ? "#605171" : "#3b3349"
            opacity: modelData.online ? 1 : 0.55
            RowLayout {
                anchors.fill: parent; anchors.margins: 8; spacing: 10
                Rectangle {
                    implicitWidth: 32; implicitHeight: 32; radius: 8; color: "#544167"
                    CopyText { anchors.centerIn: parent; text: (memberRow.modelData.name || "?").charAt(0); font.pixelSize: 15; color: "#eee8fa" }
                }
                ColumnLayout {
                    Layout.fillWidth: true; spacing: 4
                    RowLayout {
                        Layout.fillWidth: true; spacing: 6
                        CopyText { Layout.fillWidth: true; text: memberRow.modelData.name + (memberRow.modelData.id === members.snapshot.self_id ? "（我）" : ""); color: "#eee8fa"; font.pixelSize: 12; elide: Text.ElideRight; wrapMode: Text.NoWrap }
                        CopyText { objectName: "member-role-" + memberRow.modelData.id; text: memberRow.modelData.manager ? "房主" : memberRow.modelData.provider ? "世界提供者" : ""; font.pixelSize: 10; color: "#b9a2dc"; visible: text.length > 0 }
                    }
                    ProgressBar {
                        objectName: "member-progress-" + memberRow.modelData.id
                        Layout.fillWidth: true; implicitHeight: 4
                        visible: memberRow.modelData.total > 0 && memberRow.modelData.state !== "ready" && memberRow.modelData.online
                        from: 0; to: Math.max(1, memberRow.modelData.total || 0); value: memberRow.modelData.done || 0
                        background: Rectangle { color: "#43384f"; radius: 2 }
                        contentItem: Item { Rectangle { width: parent.width * parent.parent.visualPosition; height: parent.height; radius: 2; color: "#ad91dd" } }
                    }
                    CopyText {
                        Layout.fillWidth: true; font.pixelSize: 10; color: "#a89ab6"; elide: Text.ElideRight; wrapMode: Text.NoWrap
                        text: memberRow.modelData.path === "local" ? "本机" :
                            (memberRow.modelData.path === "p2p" ? "P2P 直连" : memberRow.modelData.path === "relay" ? "节点中转" : "连接测量中") +
                            (typeof memberRow.modelData.rtt_ms === "number" ? " · " + Math.round(memberRow.modelData.rtt_ms) + " ms" + (memberRow.modelData.rtt_kind === "node" ? "（节点）" : "") : " · —")
                    }
                }
                CopyText {
                    objectName: "member-state-" + memberRow.modelData.id
                    Layout.preferredWidth: 105; horizontalAlignment: Text.AlignRight; font.pixelSize: 11
                    color: memberRow.modelData.state === "ready" ? "#add4bb" : memberRow.modelData.state === "failed" ? "#ffb5bb" : "#c5b5dc"
                    text: memberRow.modelData.online && !memberRow.modelData.stale && memberRow.modelData.state === "downloading" && memberRow.modelData.speed > 0 ? (memberRow.modelData.speed / 1048576).toFixed(2) + " MiB/s" : !memberRow.modelData.online ? "已离线" : memberRow.modelData.stale ? "连接中断" :
                        ({idle:"等待准备",checking:"核对配置",downloading:"下载中",installing:"安装中",verifying:"校验中",ready:"已准备好",failed:"准备失败",cancelled:"已取消",starting:"启动游戏中",playing:"游戏中"})[memberRow.modelData.state] || "等待准备"
                }
                ActionButton {
                    objectName: "member-menu-" + memberRow.modelData.id; text: "管理"; implicitWidth: 52; implicitHeight: 28; quiet: true
                    visible: !!members.record.isManager && memberRow.modelData.id !== members.snapshot.self_id && memberRow.modelData.online
                    onClicked: { members.selection = memberRow.modelData; actions.open() }
                }
            }
        }
        CopyText { anchors.centerIn: parent; visible: list.count === 0; text: "当前节点尚未提供成员准备信息"; font.pixelSize: 12; color: "#a89ab6" }
    }
    CopyText { Layout.fillWidth: true; visible: (members.record.roomResults || []).length > 0; text: ((members.record.roomResults || []).slice(-1)[0] || {}).text || ""; font.pixelSize: 11; color: "#b5d3c4" }
    ActionButton {
        objectName: "room-members-more"; Layout.alignment: Qt.AlignHCenter
        visible: typeof members.snapshot.next === "number"
        text: "查看更多成员"; quiet: true; implicitHeight: 26
        onClicked: lobby.act("moreMembers", {})
    }
    Popup {
        id: actions; objectName: "member-actions-popup"; parent: Overlay.overlay; anchors.centerIn: parent
        width: 240; padding: 14; modal: true; focus: true
        background: Rectangle { color: "#251f30"; radius: 7; border.color: "#665278" }
        contentItem: ColumnLayout {
            spacing: 8
            CopyText { Layout.fillWidth: true; text: members.selection.name || ""; font.bold: true; elide: Text.ElideRight; wrapMode: Text.NoWrap }
            ActionButton {
                objectName: "member-install-logs"; Layout.fillWidth: true
                property bool allowed: (((members.snapshot.logs || {}).allowed) || []).indexOf(members.selection.id) >= 0
                text: allowed ? "查看安装日志" : "请求查看安装日志"
                onClicked: {
                    lobby.act(allowed ? "viewMemberLogs" : "requestMemberLogs", {member:members.selection.id})
                    actions.close()
                    if (allowed) members.logsRequested()
                }
            }
            ActionButton { objectName: "member-offer-owner"; Layout.fillWidth: true; text: "转让房主"; onClicked: { members.operation = "offerOwner"; actions.close(); confirm.open() } }
            ActionButton { objectName: "member-kick"; Layout.fillWidth: true; text: "移出房间"; visible: !members.selection.provider; onClicked: { members.operation = "kickMember"; actions.close(); confirm.open() } }
            ActionButton { Layout.fillWidth: true; text: "取消"; quiet: true; onClicked: actions.close() }
        }
    }
    Popup {
        id: confirm; objectName: "member-confirm-popup"; parent: Overlay.overlay; anchors.centerIn: parent
        width: Math.min(360, parent.width - 40); padding: 16; modal: true; focus: true
        background: Rectangle { color: "#251f30"; radius: 7; border.color: "#665278" }
        contentItem: ColumnLayout {
            spacing: 14
            CopyText { Layout.fillWidth: true; text: members.operation === "offerOwner" ? "转让给 " + members.selection.name + "？" : "将 " + members.selection.name + " 移出房间？"; font.bold: true; wrapMode: Text.Wrap }
            CopyText { Layout.fillWidth: true; font.pixelSize: 12; wrapMode: Text.Wrap; text: members.operation === "offerOwner" ? "对方接受后负责房间管理。当前世界仍由原提供者运行。" : "对方将断开连接，停止房间传输。你可以在移出记录中解除限制。" }
            RowLayout {
                Item { Layout.fillWidth: true }
                ActionButton { objectName: "member-confirm-cancel"; text: "取消"; onClicked: confirm.close() }
                ActionButton { objectName: "member-confirm-submit"; text: "确认"; primary: true; onClicked: { lobby.act(members.operation, {member:members.selection.id}); confirm.close() } }
            }
        }
    }
    Popup {
        id: blocked; parent: Overlay.overlay; anchors.centerIn: parent; width: 320; padding: 16; modal: true; focus: true
        background: Rectangle { color: "#251f30"; radius: 7; border.color: "#665278" }
        contentItem: ColumnLayout {
            spacing: 8
            CopyText { text: "移出记录"; font.bold: true }
            Repeater {
                model: members.snapshot.blocked || []
                RowLayout {
                    required property var modelData
                    CopyText { Layout.fillWidth: true; text: modelData.name; elide: Text.ElideRight; wrapMode: Text.NoWrap }
                    ActionButton { text: "允许加入"; onClicked: lobby.act("unblockMember", {member:modelData.id}) }
                }
            }
            ActionButton { Layout.alignment: Qt.AlignRight; text: "关闭"; onClicked: blocked.close() }
        }
    }
}
