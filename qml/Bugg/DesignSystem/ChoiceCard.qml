import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

AbstractButton {
    id: root
    property string caption: ""
    property string iconName: ""
    property bool selected: false
    hoverEnabled: true
    implicitHeight: DesignTokens.comfortable ? 72 : 82
    implicitWidth: 162
    padding: 12
    Accessible.role: Accessible.RadioButton
    Accessible.name: text + "，" + caption
    Accessible.checked: selected
    background: InteractiveSurface {
        control: root
        radius: 10
        selected: root.selected
        restingColor: DesignTokens.surface
        hoverColor: DesignTokens.surfaceHover
    }
    contentItem: RowLayout {
        spacing: DesignTokens.comfortable ? 16 : 8
        AppIcon {
            name: root.iconName
            visible: root.iconName.length > 0
            implicitWidth: DesignTokens.comfortable ? 22 : 16
            implicitHeight: implicitWidth
            color: root.selected ? DesignTokens.accent : DesignTokens.muted
        }
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 8
            UiText {
                text: root.text
                font.pixelSize: DesignTokens.comfortable ? 15 : 12
                font.weight: Font.DemiBold
                Layout.fillWidth: true
            }
            UiText {
                text: root.caption
                font.pixelSize: DesignTokens.comfortable ? 12 : 10
                color: DesignTokens.muted
                Layout.fillWidth: true
                wrapMode: Text.Wrap
                elide: Text.ElideNone
            }
        }
        AppIcon {
            visible: root.selected
            name: "check"
            implicitWidth: 13
            implicitHeight: 13
            color: DesignTokens.accent
        }
    }
}
