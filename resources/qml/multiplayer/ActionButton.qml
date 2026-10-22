import QtQuick
import QtQuick.Controls.Basic

Button {
    id: control
    property bool primary: false
    property bool quiet: false
    property bool danger: false
    implicitHeight: 34
    implicitWidth: Math.max(64, contentItem.implicitWidth + 24)
    leftPadding: 8
    rightPadding: 8
    focusPolicy: Qt.StrongFocus
    Accessible.name: text
    contentItem: Text {
        text: control.text
        font.family: "Source Han Sans CN"
        font.pixelSize: 13
        font.weight: Font.DemiBold
        color: !control.enabled ? "#77758e" : control.danger ? "#ffb5bb" : control.primary ? "#ffffff" : "#eeeaff"
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
    background: Rectangle {
        radius: 0
        color: !control.enabled ? "#242536" : control.down ? "#463b75" :
            control.primary ? (control.hovered ? "#9372f5" : "#7859db") :
            control.hovered ? "#4a3d62" : control.quiet ? "#291f3770" : "#31263f"
        border.width: control.activeFocus ? 2 : 1
        border.color: control.activeFocus ? "#d4c9ff" : control.primary ? "#a99bf8" : "#625b83"
        Rectangle { x:2; y:2; width:parent.width-4; height:1; color:"#ffffff"; opacity:control.down?0.04:0.16 }
    }
    HoverHandler { cursorShape: control.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor }
}
