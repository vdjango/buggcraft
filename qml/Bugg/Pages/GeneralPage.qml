import QtQuick
import QtQuick.Layouts
import Bugg.DesignSystem

PageLayout {
    id: root
    property string afterLaunch: "keep"
    property bool startCollapsed: false
    property bool showOverlayInFullscreen: false
    signal afterLaunchEdited(string value)
    signal startCollapsedEdited(bool value)
    signal showOverlayInFullscreenEdited(bool value)
    CheckOption {
        objectName: "fullscreenOverlayToggle"
        text: qsTr("游戏全屏时显示悬浮入口")
        checked: root.showOverlayInFullscreen
        onToggled: root.showOverlayInFullscreenEdited(checked)
    }
    UiText {
        Layout.fillWidth: true
        text: qsTr("关闭后，全屏游戏中隐藏同一屏幕的贴边入口，退出全屏后恢复。")
        color: DesignTokens.muted
        wrapMode: Text.Wrap
    }
    SelectField {
        objectName: "startupPresentationSelector"
        Layout.fillWidth: true
        label: qsTr("启动时贴边收起")
        selection: root.startCollapsed ? "collapse" : "keep"
        options: [
            {
                id: "keep",
                name: qsTr("保持显示")
            },
            {
                id: "collapse",
                name: qsTr("收起启动器")
            }
        ]
        onChosen: value => root.startCollapsedEdited(value === "collapse")
    }
    SelectField {
        objectName: "afterLaunchSelector"
        Layout.fillWidth: true
        label: qsTr("游戏启动后")
        selection: root.afterLaunch
        options: [
            {
                id: "keep",
                name: qsTr("保持显示")
            },
            {
                id: "collapse",
                name: qsTr("收起启动器")
            }
        ]
        onChosen: value => root.afterLaunchEdited(value)
    }
}
