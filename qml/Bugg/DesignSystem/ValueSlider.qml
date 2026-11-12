import QtQuick
import QtQuick.Controls

// 受控数值滑块；仅用户移动时发 edited，业务值和持久化归调用方。
Slider {
    id: root
    signal edited(real value)
    implicitHeight: 30
    horizontalPadding: 0
    verticalPadding: 8
    onMoved: edited(value)
    background: Rectangle {
        x: root.leftPadding
        y: (root.height - height) / 2
        width: root.availableWidth
        height: 4
        radius: 2
        color: DesignTokens.surfaceHover
        Rectangle {
            width: root.visualPosition * parent.width
            height: parent.height
            radius: parent.radius
            color: root.enabled ? DesignTokens.accent : DesignTokens.quiet
        }
    }
    handle: Rectangle {
        x: root.leftPadding + root.visualPosition * (root.availableWidth - width)
        y: (root.height - height) / 2
        width: 16
        height: 16
        radius: 8
        color: root.enabled ? DesignTokens.accent : DesignTokens.quiet
        border.width: root.visualFocus ? 3 : 0
        border.color: DesignTokens.accentWash
    }
}
