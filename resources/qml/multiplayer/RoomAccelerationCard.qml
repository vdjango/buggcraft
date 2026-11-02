import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Surface {
    id: card
    property var flow: ({})
    property bool expanded: false
    readonly property var counts: flow.summary || ({})
    readonly property bool working: ["waiting", "scanning", "matching", "uploading"].indexOf(flow.state || "waiting") >= 0
    readonly property int totalFiles: counts.total || flow.total || 0
    readonly property int readyFiles: (counts.cached || 0) + (counts.redirect || 0)
    readonly property string stateText: flow.state === "complete" ? "已就绪" : flow.state === "pending" ? "稍后补齐" : flow.state === "uploading" ? "补充缓存" : flow.state === "matching" ? "匹配来源" : "核对文件"
    function bytes(n) {
        return n >= 1048576 ? (n / 1048576).toFixed(1) + " MiB" : n >= 1024 ? (n / 1024).toFixed(1) + " KiB" : n + " B"
    }
    color: "#231e30"; border.color: "#514465"
    implicitHeight: content.implicitHeight + 26
    ColumnLayout {
        id: content
        anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
        anchors.margins: 13; spacing: 9
        RowLayout {
            Layout.fillWidth: true; spacing: 8
            Rectangle { width: 6; height: 6; radius: 3; color: card.flow.state === "complete" ? "#92d6ba" : "#b89be8" }
            CopyText { text: "文件下载加速"; color: "#ece3f8"; font.pixelSize: 13; font.bold: true }
            CopyText { text: card.stateText; color: card.flow.state === "complete" ? "#92d6ba" : "#bdb0d3"; font.pixelSize: 11 }
            Item { Layout.fillWidth: true }
            ActionButton { objectName: "room-cache-details"; text: card.expanded ? "收起详情" : "查看详情"; quiet: true; implicitHeight: 24; onClicked: card.expanded = !card.expanded }
        }
        CopyText { Layout.fillWidth: true; text: "可选加速 · 不影响加入房间和正常下载"; color: "#a99dbb"; font.pixelSize: 10 }
        RowLayout {
            Layout.fillWidth: true; spacing: 18
            ColumnLayout {
                Layout.fillWidth: true; spacing: 3
                CopyText { objectName: "room-cache-confirmed"; text: (card.counts.cached || 0) + " 个"; color: "#a5ddc5"; font.pixelSize: 16; font.bold: true }
                CopyText { text: "源站已确认 · " + card.bytes(card.counts.cached_bytes || 0); color: "#aca0bf"; font.pixelSize: 10 }
            }
            ColumnLayout {
                Layout.fillWidth: true; spacing: 3
                CopyText { text: (card.counts.redirect || 0) + " 个"; color: "#ddd2ee"; font.pixelSize: 16; font.bold: true }
                CopyText { text: "公开来源直下"; color: "#aca0bf"; font.pixelSize: 10 }
            }
            ColumnLayout {
                Layout.fillWidth: true; spacing: 3
                CopyText { text: ((card.counts.upload || 0) + (card.counts.pending || 0)) + " 个"; color: "#ddd2ee"; font.pixelSize: 16; font.bold: true }
                CopyText { text: "等待补充缓存"; color: "#aca0bf"; font.pixelSize: 10 }
            }
        }
        ProgressBar {
            id: transferBar
            objectName: "room-cache-transfer-progress"
            Layout.fillWidth: true; implicitHeight: 4
            visible: card.working || card.totalFiles > 0
            from: 0; to: Math.max(1, card.flow.bytesTotal || card.flow.total || 0)
            value: card.flow.state === "uploading" ? (card.flow.bytesDone || 0) : card.flow.state === "complete" ? to : (card.flow.done || 0)
            indeterminate: card.working && (card.flow.state !== "uploading" || !(card.flow.bytesTotal > 0))
            background: Rectangle { color: "#393046"; radius: 2 }
            contentItem: Item { Rectangle {
                id: stripe
                width: parent.width * (transferBar.indeterminate ? .25 : transferBar.visualPosition)
                height: parent.height; radius: 2; color: "#a78ad6"
                NumberAnimation on x { running: transferBar.indeterminate && card.visible; from: 0; to: Math.max(0, transferBar.width-stripe.width); duration: 1100; loops: Animation.Infinite }
                Connections { target: transferBar; function onIndeterminateChanged() { if (!transferBar.indeterminate) stripe.x = 0 } }
            } }
        }
        CopyText {
            Layout.fillWidth: true; visible: card.totalFiles > 0
            text: card.flow.state === "scanning" ? "核对文件 " + (card.flow.done || 0) + " / " + card.totalFiles :
                "可加速下载 " + card.readyFiles + " / " + card.totalFiles + " 个" +
                (card.flow.state === "uploading" && card.flow.bytesTotal > 0 ? "   ·   补传 " + Math.min(100, Math.floor(100 * (card.flow.bytesDone || 0) / card.flow.bytesTotal)) + "%" : "")
            color: "#bdb0d0"; font.pixelSize: 10
        }
        CopyText {
            Layout.fillWidth: true; visible: card.flow.state === "uploading"
            text: "已发送 " + card.bytes(card.flow.bytesDone || 0) + " / " + card.bytes(card.flow.bytesTotal || 0) + "   ·   " + card.bytes(card.flow.bytesPerSecond || 0) + "/s"
            font.pixelSize: 10; color: "#b6a8ca"
        }
        ColumnLayout {
            Layout.fillWidth: true; visible: card.expanded; spacing: 6
            Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: "#41364f" }
            CopyText { Layout.fillWidth: true; text: card.flow.message || "连接源站后自动核对文件信息"; wrapMode: Text.Wrap; font.pixelSize: 11; color: "#d1c4e1" }
            CopyText { Layout.fillWidth: true; visible: (card.counts.receiving || 0) > 0; text: "源站接收中 " + (card.counts.receiving || 0) + " 个 · 已收到 " + card.bytes(card.counts.receiving_bytes || 0); font.pixelSize: 10; color: "#bdb0d0" }
            CopyText { Layout.fillWidth: true; visible: (card.counts.cloud_ready || 0) + (card.counts.cloud_pending || 0) > 0; text: "云端已就绪 " + (card.counts.cloud_ready || 0) + " 个 · 等待后台迁移 " + (card.counts.cloud_pending || 0) + " 个"; font.pixelSize: 10; color: "#bdb0d0" }
            CopyText { Layout.fillWidth: true; visible: (card.counts.pending || 0) > 0; text: (card.counts.pending || 0) + " 个暂不可缓存，正常下载仍可使用"; font.pixelSize: 10; color: "#dfbd92" }
            CopyText { Layout.fillWidth: true; visible: !!card.flow.file; text: card.flow.file || ""; font.pixelSize: 10; color: "#a79ab9"; elide: Text.ElideMiddle; wrapMode: Text.NoWrap }
        }
    }
}
