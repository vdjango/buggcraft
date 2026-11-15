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
    property var backdropEffects: ({})
    property bool backdropPageMode: false
    property bool backdropSoundEnabled: false
    property real backdropPageOverlayOpacity: 0.10
    property real backdropOpacity: 1
    property bool backdropVisible: true
    readonly property alias contentItem: body
    readonly property alias backdropColor: carousel.averageColor
    readonly property alias backdropVideoPlaying: carousel.videoPlaying
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
        // Page backgrounds keep the media visible; readability comes from one light veil below.
        color: root.backdropPageMode ? "transparent" : root.color
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
            blurStyle: root.backdropPageMode ? "full" : root.backdropEffects.backgroundStyle || "edges"
            blurAmount: (root.backdropEffects.backgroundBlur === undefined ? 0.35 : root.backdropEffects.backgroundBlur) * (root.backdropPageMode ? 2 : 1)
            vignette: root.backdropEffects.backgroundVignette === undefined ? 0.35 : root.backdropEffects.backgroundVignette
            soundEnabled: root.backdropSoundEnabled
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
        Rectangle {
            objectName: "pageBackdropVeil"
            anchors.fill: parent
            radius: root.radius
            // The page overlay is configurable and only shown in page mode.
            color: Qt.rgba(1, 1, 1, root.backdropPageOverlayOpacity)
            visible: root.backdropPageMode && root.backdropVisible
            opacity: root.backdropOpacity
        }
        Item {
            id: body
            anchors.fill: parent
        }
    }
}
