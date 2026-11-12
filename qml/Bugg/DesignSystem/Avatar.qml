pragma ComponentBehavior: Bound
import QtQuick

Rectangle {
    id: root
    property string initials: "J"
    property color tint: DesignTokens.accent
    property bool online: false
    property bool showStatus: false
    property int badgeCount: 0
    implicitWidth: 36
    implicitHeight: 36
    radius: width * 0.32
    color: Qt.rgba(tint.r, tint.g, tint.b, 0.13)
    UiText {
        anchors.centerIn: parent
        text: root.initials
        color: root.tint
        font.pixelSize: root.width * 0.36
        font.weight: Font.DemiBold
    }
    Rectangle {
        visible: root.showStatus || root.badgeCount > 0
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        width: root.badgeCount > 0 ? Math.max(16, count.implicitWidth + 6) : 10
        height: root.badgeCount > 0 ? 16 : 10
        radius: height / 2
        border.width: 2
        border.color: DesignTokens.background
        color: root.badgeCount > 0 || root.online ? DesignTokens.accent : DesignTokens.quiet
        UiText {
            id: count
            anchors.centerIn: parent
            visible: root.badgeCount > 0
            text: root.badgeCount > 99 ? "99+" : String(root.badgeCount)
            font.pixelSize: 9
            color: DesignTokens.accentInk
        }
    }
}
