pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls

AbstractButton {
    id: root
    property string iconName: "settings"
    property string accessibleName: ""
    property bool selected: false
    // 窗口操作等轻量入口可关闭底色反馈，保持命中区与无障碍名称。
    property bool feedbackEnabled: true
    implicitWidth: DesignTokens.iconButtonSize
    implicitHeight: DesignTokens.iconButtonSize
    hoverEnabled: true
    padding: 0
    Accessible.role: Accessible.Button
    Accessible.name: accessibleName
    background: InteractiveSurface {
        visible: root.feedbackEnabled
        control: root
        selected: root.selected
    }
    contentItem: Item {
        AppIcon {
            anchors.centerIn: parent
            width: 16
            height: 16
            name: root.iconName
            color: root.selected ? DesignTokens.accent : DesignTokens.muted
        }
    }
}
