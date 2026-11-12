import QtQuick
import QtQuick.Controls

Control {
    id: root
    default property alias content: body.data
    property alias radius: backgroundShape.radius
    property color color: DesignTokens.surface
    property color borderColor: "transparent"
    property real borderWidth: 0
    padding: 16
    contentItem: Item {
        id: body
    }
    background: Rectangle {
        id: backgroundShape
        radius: DesignTokens.radius
        color: root.color
        border.color: root.borderColor
        border.width: root.borderWidth
    }
}
