pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

AbstractButton {
    id: root
    property string iconName: ""
    property string variant: "primary"
    property bool trailingIcon: false
    property bool compact: false
    property real cornerRadius: 8
    Layout.maximumWidth: DesignTokens.comfortable ? Math.max(120, implicitWidth + 24) : Number.POSITIVE_INFINITY
    implicitWidth: row.implicitWidth + (compact ? 24 : 36)
    implicitHeight: DesignTokens.controlHeight - (compact ? 4 : 0)
    hoverEnabled: true
    scale: down ? 0.97 : 1
    Behavior on scale {
        NumberAnimation {
            duration: 110
            easing.type: Easing.OutCubic
        }
    }
    Accessible.role: Accessible.Button
    Accessible.name: text
    background: Rectangle {
        radius: root.cornerRadius
        color: {
            if (!root.enabled)
                return DesignTokens.line;
            if (root.variant === "danger")
                return DesignTokens.danger;
            if (root.variant === "primary")
                return root.down ? DesignTokens.accentPressed : root.hovered ? DesignTokens.accentHover : DesignTokens.accent;
            if (root.variant === "soft")
                return root.hovered ? DesignTokens.line : DesignTokens.surfaceHover;
            return root.hovered ? root.palette.midlight : "transparent";
        }
        border.color: root.activeFocus ? DesignTokens.accent : root.variant === "outline" ? DesignTokens.line : "transparent"
        border.width: root.activeFocus ? 2 : 1
        Behavior on color {
            ColorAnimation {
                duration: DesignTokens.motionFast
            }
        }
    }
    contentItem: Item {
        RowLayout {
            id: row
            anchors.centerIn: parent
            spacing: 9
            layoutDirection: root.trailingIcon ? Qt.RightToLeft : Qt.LeftToRight
            AppIcon {
                visible: root.iconName !== ""
                name: root.iconName
                implicitWidth: 17
                implicitHeight: 17
                color: root.variant === "primary" || root.variant === "danger" ? DesignTokens.accentInk : root.palette.buttonText
            }
            UiText {
                visible: root.text.length > 0
                text: root.text
                font.pixelSize: DesignTokens.comfortable ? 14 : root.compact ? 12 : 13
                font.weight: Font.DemiBold
                color: root.variant === "primary" || root.variant === "danger" ? DesignTokens.accentInk : root.palette.buttonText
            }
        }
    }
}
