import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Rectangle {
    id: root
    required property var file
    property bool complete: ["verified", "cached"].indexOf(file.state) >= 0
    property bool active: ["downloading", "verifying", "retrying"].indexOf(file.state) >= 0
    property real total: file.total || file.size || 0
    property real done: file.done || (complete ? total : 0)
    property string statusText: ({pending:"等待下载", downloading:"下载中", verifying:"校验中",
        verified:"已完成", cached:"已复用", retrying:"正在重试", failed:"下载失败",
        cancelled:"已取消", interrupted:"已中断", skipped:"已跳过"})[file.state] || "等待下载"
    function bytes(value) {
        if (value >= 1073741824) return (value / 1073741824).toFixed(2) + " GB"
        if (value >= 1048576) return (value / 1048576).toFixed(1) + " MB"
        if (value >= 1024) return (value / 1024).toFixed(1) + " KB"
        return value + " B"
    }
    height: file.source ? 112 : 88; radius: 5
    color: active ? "#30283f" : "#272332"
    border.color: active ? "#655288" : "#3d344d"
    ColumnLayout {
        anchors.fill: parent; anchors.margins: 10; spacing: 5
        RowLayout {
            Layout.fillWidth: true; spacing: 10
            Label {
                objectName: "download-file-name"
                Layout.fillWidth: true; Layout.minimumWidth: 0
                text: root.file.name || "资源文件"; textFormat: Text.PlainText
                elide: Text.ElideMiddle; color: "#eee8fb"; font.pixelSize: 12; font.bold: true
                ToolTip.visible: fileHover.hovered
                ToolTip.text: root.file.path || text
                HoverHandler { id: fileHover }
            }
            Label {
                text: root.statusText; font.pixelSize: 11
                color: root.file.state === "failed" ? "#e1a3ae" : root.active ? "#c1aaff" : "#a89abb"
            }
            Label {
                objectName: "download-file-percent"
                text: root.complete ? "100%" : root.total > 0 ? Math.min(100, Math.floor(root.done * 100 / root.total)) + "%" : "—"
                font.pixelSize: 11; color: "#cfbff0"; horizontalAlignment: Text.AlignRight
                Layout.preferredWidth: 38
            }
        }
        DownloadAddress {
            objectName: "download-file-address"
            Layout.fillWidth: true
            address: root.file.source || ""
        }
        ProgressBar {
            id: progress; objectName: "download-file-progress"
            Layout.fillWidth: true; implicitHeight: 5
            from: 0; to: Math.max(1, root.total)
            value: root.complete ? to : Math.min(to, root.done)
            indeterminate: root.active && root.total <= 0
            background: Rectangle { color: "#17131f"; radius: 3 }
            contentItem: Item {
                clip: true
                Rectangle {
                    property real sweep: 0
                    height: parent.height; radius: 3
                    width: parent.width * (progress.indeterminate ? .22 : progress.visualPosition)
                    x: progress.indeterminate ? sweep * (parent.width + width) - width : 0
                    color: root.file.state === "failed" ? "#bd7f91" : root.complete ? "#8c7aaf" : "#aa85f5"
                    NumberAnimation on sweep { from: 0; to: 1; duration: 1300; loops: Animation.Infinite; running: progress.indeterminate }
                }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            Label {
                Layout.fillWidth: true; Layout.minimumWidth: 0
                text: root.file.error || root.file.path || root.file.name || ""
                textFormat: Text.PlainText; elide: Text.ElideMiddle; color: "#9e90ae"; font.pixelSize: 10
            }
            Label { text: (root.file.state === "downloading" ? root.bytes(root.file.speed || 0) + "/s · " : "") + root.bytes(root.done) + (root.total > 0 ? " / " + root.bytes(root.total) : ""); color: "#b6a8c6"; font.pixelSize: 10 }
        }
    }
}
