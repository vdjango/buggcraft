pragma ComponentBehavior: Bound
import QtQuick

Text {
    color: DesignTokens.text
    font.family: DesignTokens.fontFamily
    font.pixelSize: 13
    renderType: Text.QtRendering
    verticalAlignment: Text.AlignVCenter
    elide: Text.ElideRight
}
