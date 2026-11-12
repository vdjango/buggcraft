import QtQuick
import QtQuick.Controls

CheckBox {
    id: root
    padding: 0
    implicitHeight: 22 + DesignTokens.densityStep * 2
    contentItem: UiText {
        text: root.text
        leftPadding: 27
        font.pixelSize: DesignTokens.comfortable ? 13 : 11
        color: DesignTokens.text
    }
    indicator: Rectangle {
        x: 0
        y: (root.height - height) / 2
        width: 14 + DesignTokens.densityStep
        height: width
        radius: 4
        color: root.checked ? DesignTokens.accentWash : "transparent"
        border.color: root.visualFocus ? DesignTokens.quiet : DesignTokens.line
        AppIcon {
            anchors.centerIn: parent
            visible: root.checked
            width: 11
            height: 11
            name: "check"
            color: DesignTokens.accent
        }
    }
}
