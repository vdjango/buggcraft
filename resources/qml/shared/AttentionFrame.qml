import QtQuick

Item {
    id: frame
    property bool active: false
    property color tint: "#a68aff"
    property real phase: 0
    readonly property real pulse: 0.5 + 0.5 * Math.sin(phase * Math.PI * 2)
    anchors.fill: parent
    anchors.margins: -3
    visible: active
    z: 5
    NumberAnimation on phase {
        from: 0; to: 1; duration: 2200; loops: Animation.Infinite
        running: frame.active && frame.visible
    }
    Rectangle {
        anchors.fill: parent; anchors.margins: -2
        color: "transparent"; border.width: 5; border.color: frame.tint
        opacity: 0.08 + frame.pulse * 0.13
    }
    Rectangle {
        anchors.fill: parent; color: frame.tint
        opacity: 0.04 + frame.pulse * 0.12
    }
    Rectangle {
        anchors.fill: parent; color: "transparent"
        border.width: 2; border.color: "#e5ceff"
        opacity: 0.45 + frame.pulse * 0.55
    }
    Repeater {
        model: 5
        Item {
            required property int index
            width: 9; height: 9
            x: frame.width * [0.08, 0.38, 0.91, 0.73, 0.19][index] - width / 2
            y: (index % 2 === 0 ? 0 : frame.height) - height / 2
            opacity: Math.max(0, Math.sin(frame.phase * Math.PI * 2 + index * 1.7))
            Rectangle { anchors.centerIn: parent; width: 9; height: 3; color: index % 2 ? "#e9dcff" : "#ffe5a3" }
            Rectangle { anchors.centerIn: parent; width: 3; height: 9; color: index % 2 ? "#e9dcff" : "#ffe5a3" }
        }
    }
}
