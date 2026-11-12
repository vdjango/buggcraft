pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls

AbstractButton {
    id: root
    property bool selected: false
    property bool drawSelection: true
    property string iconName: ""
    implicitWidth: 55
    implicitHeight: 34
    hoverEnabled: true
    Accessible.role: Accessible.Button
    Accessible.name: text
    background: InteractiveSurface {
        control: root
        selected: root.selected && root.drawSelection
    }
    contentItem: Item {
        AppIcon {
            visible: root.iconName.length > 0
            anchors.centerIn: parent
            width: 17
            height: 17
            name: root.iconName
            color: root.selected ? DesignTokens.accent : DesignTokens.text
        }
        UiText {
            visible: !root.iconName.length
            anchors.fill: parent
            text: root.text
            color: root.selected ? DesignTokens.accent : DesignTokens.text
            font.pixelSize: DesignTokens.comfortable ? 14 : 12
            horizontalAlignment: Text.AlignHCenter
            font.weight: root.selected ? Font.DemiBold : Font.Normal
        }
    }
}
