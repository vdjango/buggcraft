import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

AbstractButton {
    id: root
    property string value: ""
    property string iconName: "chevron"
    property bool selected: false
    property bool compact: false
    implicitHeight: compact ? DesignTokens.controlHeight : DesignTokens.comfortable ? 50 : 39
    hoverEnabled: true
    background: InteractiveSurface {
        control: root
        radius: 7
        selected: root.selected
    }
    contentItem: RowLayout {
        UiText {
            Layout.leftMargin: 10
            text: root.text
            Layout.fillWidth: true
            font.pixelSize: DesignTokens.comfortable ? 14 : 11
            color: root.selected ? DesignTokens.accent : DesignTokens.text
        }
        UiText {
            text: root.value
            font.pixelSize: DesignTokens.comfortable ? 12 : 10
            color: DesignTokens.muted
        }
        AppIcon {
            Layout.rightMargin: 10
            Layout.leftMargin: 6
            implicitWidth: 11
            implicitHeight: 11
            name: root.iconName
            visible: root.iconName.length > 0
            color: root.selected ? DesignTokens.accent : DesignTokens.quiet
        }
    }
}
