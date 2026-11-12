pragma ComponentBehavior: Bound
import QtQuick

Item {
    id: root
    default property alias content: body.data
    property real radius: 20
    property color color: DesignTokens.background
    property url backdropSource: ""
    property var backdropSources: []
    property bool backdropActive: true
    property bool backdropShade: false
    property real backdropOpacity: 1
    property bool backdropVisible: true
    readonly property alias contentItem: body
    readonly property alias backdropColor: carousel.averageColor
    Repeater {
        model: 3
        Rectangle {
            required property int index
            x: 7 - index * 2
            y: 10 + index
            width: root.width - x * 2
            height: root.height - 16
            radius: root.radius + index * 2
            color: DesignTokens.shadow
            opacity: 0.018 + (2 - index) * 0.005
        }
    }
    Rectangle {
        x: 8
        y: 5
        width: root.width - 16
        height: root.height - 16
        radius: root.radius
        color: root.color
        clip: true
        // 圆角底色与图片同步过渡，避免图片淡出时先露出白色底角。
        Behavior on color {
            ColorAnimation {
                duration: 180
                easing.type: Easing.OutCubic
            }
        }
        BackdropCarousel {
            id: carousel
            objectName: "windowBackdrop"
            anchors.fill: parent
            sources: root.backdropSources
            fallbackSource: root.backdropSource
            radius: root.radius
            shade: root.backdropShade
            active: root.backdropActive && root.backdropVisible && root.backdropOpacity > 0.99
            visible: root.backdropVisible
            opacity: root.backdropOpacity
            Behavior on opacity {
                NumberAnimation {
                    duration: 180
                    easing.type: Easing.OutCubic
                }
            }
        }
        Item {
            id: body
            anchors.fill: parent
        }
    }
}
