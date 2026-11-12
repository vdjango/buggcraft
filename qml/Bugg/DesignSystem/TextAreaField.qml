import QtQuick
import QtQuick.Controls

TextArea {
    id: root
    property bool flat: false
    implicitHeight: 112
    padding: 12
    wrapMode: TextEdit.Wrap
    font.family: DesignTokens.fontFamily
    font.pixelSize: 12
    color: DesignTokens.text
    placeholderTextColor: DesignTokens.muted
    selectByMouse: true
    background: Rectangle {
        radius: root.flat ? 0 : 10
        color: root.flat ? "transparent" : DesignTokens.surface
        border.color: root.activeFocus ? DesignTokens.quiet : "transparent"
    }
}
