import QtQuick
import QtQuick.Controls

TextField {
    id: root
    default property alias trailingContent: trailing.data
    property string leadingIcon: ""
    implicitHeight: DesignTokens.controlHeight
    font.family: DesignTokens.fontFamily
    font.pixelSize: DesignTokens.controlTextSize
    color: DesignTokens.text
    placeholderTextColor: DesignTokens.muted
    selectByMouse: true
    leftPadding: leadingIcon.length ? 40 : 12
    rightPadding: trailing.childrenRect.width > 0 ? trailing.childrenRect.width + 16 : 12
    background: Rectangle {
        radius: 10
        color: DesignTokens.surface
        border.color: root.activeFocus ? DesignTokens.quiet : DesignTokens.controlBorder
    }
    AppIcon {
        visible: root.leadingIcon.length > 0
        name: root.leadingIcon
        width: 16
        height: 16
        x: 13
        anchors.verticalCenter: parent.verticalCenter
    }
    Item {
        id: trailing
        width: childrenRect.width
        height: childrenRect.height
        anchors.right: parent.right
        anchors.rightMargin: 7
        anchors.verticalCenter: parent.verticalCenter
    }
}
