import QtQuick
import QtQuick.Controls.Basic

AbstractButton {
    id: control
    width: 56; height: 56; z: 20
    property real minimumX: 14
    property real maximumX: parent.width - width - 14
    property real minimumY: 100
    property real maximumY: parent.height - height - 14
    property bool manuallyPositioned: false
    onMaximumYChanged: Qt.callLater(function() {
        // Wait for the surrounding layout before clamping a dragged position.
        // The default position remains bound to the bottom edge.
        if (control.manuallyPositioned && control.y > control.maximumY)
            control.y = control.maximumY
    })
    Accessible.name: "打开好友窗口"
    Accessible.description: "点击打开好友，按住拖动可调整位置"
    focusPolicy: Qt.StrongFocus
    hoverEnabled: true
    topPadding: 6; bottomPadding: 6
    background: Rectangle {
        radius: 16
        color: pointer.pressed ? "#584180" : control.hovered ? "#7754b7" : "#614496"
        border.width: control.activeFocus ? 2 : 1
        border.color: control.activeFocus ? "#e3d4ff" : "#a28ac8"
        Rectangle { x: 8; y: 1; width: parent.width - 16; height: 1; color: "#c6a9ed"; opacity: 0.5 }
    }
    contentItem: Column {
        spacing: 2
        Canvas {
            width: parent.width; height: 23
            onPaint: {
                var ctx = getContext("2d")
                ctx.strokeStyle = "#eee5ff"; ctx.lineWidth = 1.6
                var mid = width / 2
                ctx.beginPath(); ctx.arc(mid - 3, 6, 3.5, 0, Math.PI * 2); ctx.stroke()
                ctx.beginPath(); ctx.arc(mid + 6, 8, 2.8, -Math.PI / 2, Math.PI / 2); ctx.stroke()
                ctx.beginPath(); ctx.arc(mid - 3, 20, 7, Math.PI, 0); ctx.stroke()
                ctx.beginPath(); ctx.arc(mid + 5, 20, 5, -Math.PI / 2, 0); ctx.stroke()
            }
        }
        Text {
            width: parent.width
            text: "好友"; color: "#faf6ff"; font.family: "Source Han Sans CN"; font.pixelSize: 11
            horizontalAlignment: Text.AlignHCenter
        }
    }
    MouseArea {
        id: pointer
        anchors.fill: parent
        cursorShape: drag.active ? Qt.ClosedHandCursor : Qt.PointingHandCursor
        drag.target: control
        drag.minimumX: control.minimumX; drag.maximumX: control.maximumX
        drag.minimumY: control.minimumY; drag.maximumY: control.maximumY
        onPositionChanged: { if (drag.active) control.manuallyPositioned = true }
        onClicked: { control.forceActiveFocus(); control.clicked() }
    }
    ToolTip.visible: hovered && !pointer.pressed
    ToolTip.delay: 700
    ToolTip.text: "打开好友 · 按住可拖动"
}
