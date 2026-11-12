import QtQuick

UiText {
    font.pixelSize: 11
    color: DesignTokens.accent
    wrapMode: Text.Wrap
    elide: Text.ElideNone
    visible: text.length > 0
}
