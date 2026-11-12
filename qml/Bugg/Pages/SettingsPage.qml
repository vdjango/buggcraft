pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import Bugg.DesignSystem

PageLayout {
    id: root
    required property string theme
    property string downloadSource: qsTr("BUGG 优先")
    property string languageName: qsTr("简体中文")
    property var updateStatus: ({})
    signal noticeRequested(string message)
    signal themeRequested(string theme)
    signal openRequested(string route)
    spacing: 0
    verticalPadding: 12
    Repeater {
        model: [
            {
                label: qsTr("外观"),
                value: root.theme === "panel" ? qsTr("悬浮面板") : qsTr("常规页面"),
                route: "appearance"
            },
            {
                label: qsTr("语言"),
                value: root.languageName,
                route: "language"
            },
            {
                label: qsTr("游戏"),
                value: qsTr("内存与窗口"),
                route: "gameSettings"
            },
            {
                label: qsTr("下载"),
                value: root.downloadSource,
                route: "downloads"
            },
            {
                label: qsTr("常规"),
                value: qsTr("启动后行为"),
                route: "general"
            },
            {
                label: qsTr("账号"),
                value: qsTr("登录与管理"),
                route: "account"
            },
            {
                label: qsTr("联机服务"),
                value: qsTr("登录服务设置"),
                route: "multiplayerSettings"
            },
            {
                label: qsTr("存储位置"),
                value: qsTr("配置与游戏目录"),
                route: "storage"
            },
            {
                label: qsTr("日志与调试"),
                value: qsTr("级别、模组与搜索"),
                route: "logs"
            },
            {
                label: qsTr("问题反馈"),
                value: qsTr("诊断与帮助"),
                route: "feedback"
            },
            {
                label: qsTr("关于与更新"),
                value: root.updateStatus.state === "ready" ? qsTr("重启安装更新") : root.updateStatus.state === "available" ? qsTr("新版本 %1").arg(root.updateStatus.version) : "Bugg",
                route: "update"
            }
        ]
        SettingRow {
            compact: true
            required property var modelData
            objectName: modelData.route + "SettingsRow"
            Layout.fillWidth: true
            text: modelData.label
            value: modelData.value
            onClicked: root.openRequested(modelData.route)
        }
    }
}
