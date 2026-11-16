import QtQuick
import QtQuick.Layouts
import Bugg.DesignSystem

PageLayout {
    id: root
    property string afterLaunch: "keep"
    property bool showOverlayInFullscreen: false
    property bool autoDependencies: true
    property bool anonymousUsage: true
    signal afterLaunchEdited(string value)
    signal showOverlayInFullscreenEdited(bool value)
    signal autoDependenciesEdited(bool value)
    signal anonymousUsageEdited(bool value)
    SelectField {
        objectName: "afterLaunchSelector"
        Layout.fillWidth: true
        label: qsTr("启动行为")
        selection: root.afterLaunch
        options: [
            {
                id: "collapse",
                name: qsTr("吸附")
            },
            {
                id: "keep",
                name: qsTr("无动作")
            },
            {
                id: "hide",
                name: qsTr("隐藏")
            },
            {
                id: "close",
                name: qsTr("关闭")
            }
        ]
        onChosen: value => root.afterLaunchEdited(value)
    }
    SelectField {
        objectName: "fullscreenOverlayToggle"
        Layout.fillWidth: true
        visible: root.afterLaunch === "collapse"
        label: qsTr("吸附入口 · 游戏启动后")
        selection: root.showOverlayInFullscreen ? "show" : "hide"
        options: [
            {
                id: "hide",
                name: qsTr("隐藏 · 不显示好友和联机通知")
            },
            {
                id: "show",
                name: qsTr("显示 · 及时了解伙伴动态")
            }
        ]
        onChosen: value => root.showOverlayInFullscreenEdited(value === "show")
    }
    UiText {
        Layout.fillWidth: true
        visible: root.afterLaunch === "collapse"
        text: qsTr("游戏全屏时同样生效；隐藏后可从托盘恢复。")
        color: DesignTokens.muted
        wrapMode: Text.Wrap
    }
    CheckOption {
        objectName: "automaticDependencyToggle"
        text: qsTr("自动解决缺失依赖")
        checked: root.autoDependencies
        onToggled: root.autoDependenciesEdited(checked)
    }
    UiText {
        Layout.fillWidth: true
        visible: root.afterLaunch === "close"
        text: qsTr("联机期间会自动改为隐藏，保持房间连接；游戏结束后恢复窗口。")
        color: DesignTokens.muted
        wrapMode: Text.Wrap
    }
    UiText {
        Layout.fillWidth: true
        text: qsTr("关闭后仅安装所选文件；发现缺失依赖时由你决定是否处理。整合包仍遵循作者清单。")
        color: DesignTokens.muted
        wrapMode: Text.Wrap
    }
    CheckOption {
        objectName: "anonymousUsageToggle"
        text: qsTr("发送匿名使用统计")
        checked: root.anonymousUsage
        onToggled: root.anonymousUsageEdited(checked)
    }
    UiText {
        Layout.fillWidth: true
        text: qsTr("仅统计随机安装标识和启动次数，不发送用户名、角色名或游戏内容。")
        color: DesignTokens.muted
        wrapMode: Text.Wrap
    }
}
