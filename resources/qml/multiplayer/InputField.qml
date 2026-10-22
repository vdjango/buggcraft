import QtQuick
import QtQuick.Controls.Basic

TextField {
    id: field
    implicitHeight: 34
    leftPadding: 10
    rightPadding: 10
    font.family: Qt.application.font.family
    font.pixelSize: 13
    color: "#f4f2ff"
    placeholderTextColor: "#868499"
    selectionColor: "#7859ef"
    selectByMouse: true
    maximumLength: 140
    background: Rectangle {
        color: "#211a2c"
        radius: 0
        border.color: field.activeFocus ? "#a88cff" : "#424054"
    }
}
