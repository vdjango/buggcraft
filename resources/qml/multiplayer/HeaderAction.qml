import QtQuick
import QtQuick.Controls.Basic

Button {
    id: control
    property string label: text
    property bool danger: false
    property int iconSize: 20
    property bool backArrow: false
    property string iconName: ""
    implicitWidth: backArrow ? 32 : Math.max(32, contentItem.implicitWidth + 16)
    implicitHeight: 32
    padding: 0
    focusPolicy: Qt.StrongFocus
    Accessible.name: label
    contentItem: Item {
        implicitWidth: control.backArrow || control.iconName ? 16 : labelText.implicitWidth
        implicitHeight: 32
        Text {
            id: labelText
            visible: !control.backArrow && !control.iconName
            anchors.centerIn: parent
            text: control.text
            font.family: Qt.application.font.family
            font.pixelSize: control.iconSize
            color: control.danger ? "#f2acb7" : control.hovered ? "#ffffff" : "#d8d0e6"
        }
        Canvas {
            objectName: control.backArrow ? "header-back-arrow" : ""
            visible: control.backArrow || !!control.iconName
            width: 16; height: 16
            anchors.centerIn: parent
            property color strokeColor: control.hovered ? "#ffffff" : "#d8d0e6"
            onStrokeColorChanged: requestPaint()
            onPaint: {
                var context = getContext("2d")
                context.clearRect(0, 0, width, height)
                context.strokeStyle = strokeColor
                context.lineWidth = 1.8
                context.lineCap = "round"
                context.lineJoin = "round"
                if (control.iconName === "more") {
                    context.fillStyle = strokeColor
                    for (var x = 3; x <= 13; x += 5) context.fillRect(x - 1, 7, 2, 2)
                    return
                }
                if (control.iconName === "copy") {
                    context.strokeRect(6, 2, 7, 9)
                    context.beginPath(); context.moveTo(4, 5); context.lineTo(2, 5); context.lineTo(2, 14); context.lineTo(9, 14); context.lineTo(9, 13); context.stroke()
                    return
                }
                if (control.iconName === "refresh") {
                    context.beginPath(); context.arc(8, 8, 5, 0.25 * Math.PI, 1.85 * Math.PI); context.stroke()
                    context.beginPath(); context.moveTo(10, 2); context.lineTo(13, 5); context.lineTo(14, 1); context.stroke()
                    return
                }
                context.beginPath()
                context.moveTo(7.5, 3)
                context.lineTo(2.5, 8)
                context.lineTo(7.5, 13)
                context.moveTo(2.5, 8)
                context.lineTo(13.5, 8)
                context.stroke()
            }
        }
    }
    background: Rectangle {
        radius: 4
        color: control.down ? "#493a5d" : control.hovered ? "#393044" : "transparent"
        border.width: control.visualFocus ? 1 : 0
        border.color: "#c8b5ff"
    }
    ToolTip.visible: hovered
    ToolTip.delay: 650
    ToolTip.text: label
    HoverHandler { cursorShape: Qt.PointingHandCursor }
}
