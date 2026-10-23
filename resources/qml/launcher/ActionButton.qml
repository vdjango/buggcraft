import QtQuick
import QtQuick.Controls

Button {
    id: control
    implicitHeight: 36
    padding: 8
    font.pixelSize: 13
    font.weight: Font.DemiBold
    property bool primary: false
    background: Rectangle {
        opacity: control.enabled ? 1 : 0.5
        radius: 5
        color: control.down ? "#5e44d0" : control.primary ? "#7859ff" : "#2f2e4b"
        border.color: control.activeFocus ? "#cabdff" : control.primary ? "#9b85ff" : "#625277"
        border.width: 1
    }
    contentItem: Text {
        text: control.text
        color: control.enabled ? "#f3f5fb" : "#a8a6b5"
        font: control.font
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        wrapMode: Text.Wrap
    }
}
