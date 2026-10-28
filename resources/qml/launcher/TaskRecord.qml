import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

ListRow {
    id: root
    required property var modelData
    property bool active: ["等待中", "进行中", "正在取消"].indexOf(modelData.state) >= 0
    property string actionText: modelData.state === "正在取消" ? "正在取消" : active ? "取消"
        : modelData.kind === "room" ? (modelData.state === "已完成" ? "已准备" : "返回房间重试")
        : modelData.modpack && modelData.state === "已完成" ? "已导入"
        : modelData.modpack ? "继续安装"
        : modelData.content && modelData.content.kind === "modpack" && modelData.state === "已完成" ? "继续安装"
        : modelData.state === "已完成" ? "重新安装" : "重试"
    signal viewLog(string taskId)
    width: ListView.view.width
    height: implicitHeight
    title: (modelData.kind === "room" ? "房间配置 " : modelData.modpack ? "整合包 " : modelData.content && modelData.content.kind
        ? ({mod:"模组 ", resourcepack:"资源包 ", shader:"光影包 ", modpack:"整合包 "})[modelData.content.kind] || "资源 " : "Minecraft ") + (modelData.version || "")
    description: modelData.kind === "room"
        ? "Minecraft " + (modelData.base_version || "") + "  ·  " + (modelData.loader || "") + " " + (modelData.loader_version || "") + "  ·  " + (modelData.game_dir || "")
        : modelData.game_dir || ""
    icon: "../../images/user/offline_login.png"
    actions: Component {
        RowLayout {
            spacing: 8
            Label { text: root.modelData.state || "未知"; color: root.modelData.state === "失败" ? "#ff9b91" : "#c4b7f1"; font.pixelSize: 12 }
            Rectangle { implicitWidth: 1; implicitHeight: 30; color: "#4dffffff" }
            ActionButton { objectName: "task-log-" + root.modelData.id; text: "日志"; implicitWidth: 50; implicitHeight: 28; onClicked: root.viewLog(root.modelData.id) }
            ActionButton {
                objectName: "task-action-" + root.modelData.id
                visible: root.modelData.kind !== "room" || root.active
                implicitHeight: 28; text: root.actionText
                enabled: root.modelData.state !== "正在取消" && !(root.modelData.kind === "room" && !root.active) && !(root.modelData.modpack && root.modelData.state === "已完成")
                onClicked: taskHistory.taskAction(root.modelData.id)
            }
        }
    }
    footer: Component {
        ColumnLayout {
            spacing: 5
            RowLayout {
                Layout.fillWidth: true
                Label { Layout.fillWidth: true; text: root.modelData.error || root.modelData.status || ""; color: root.modelData.error ? "#ff9b91" : "#b3ffffff"; font.pixelSize: 11; elide: Text.ElideRight }
                Label { objectName: "task-speed-" + root.modelData.id; visible: root.active; text: (root.modelData.speed || 0) >= 1048576 ? (root.modelData.speed / 1048576).toFixed(2) + " MiB/s" : ((root.modelData.speed || 0) / 1024).toFixed(1) + " KiB/s"; color: "#b9d5c5"; font.pixelSize: 11 }
                Label { objectName: "task-progress-" + root.modelData.id; text: root.active && root.modelData.maximum > 0 ? "阶段进度 " + Math.max(0, Math.min(100, Math.round((root.modelData.progress || 0) * 100 / root.modelData.maximum))) + "%" : (root.modelData.created_at || "").substring(0, 10); color: "#a99fb8"; font.pixelSize: 11 }
            }
            ProgressBar {
                id: progress
                Layout.fillWidth: true; implicitHeight: 3
                from: 0; to: Math.max(1, root.modelData.maximum || 0)
                value: root.modelData.state === "已完成" ? to : Math.min(to, root.modelData.progress || 0)
                indeterminate: root.active && !(root.modelData.maximum > 0)
                background: Rectangle { implicitHeight: 3; color: "#4d000000" }
                contentItem: Item {
                    clip: true
                    Rectangle {
                        height: parent.height; width: parent.width * (progress.indeterminate ? .25 : progress.visualPosition)
                        color: root.modelData.error ? "#c67581" : "#8b85da"
                        SequentialAnimation on x {
                            running: progress.visible && progress.indeterminate; loops: Animation.Infinite
                            NumberAnimation { from: -progress.width / 4; to: progress.width; duration: 1500 }
                        }
                    }
                }
            }
            Item { Layout.preferredHeight: 8 }
        }
    }
}
