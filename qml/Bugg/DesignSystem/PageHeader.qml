import QtQuick
import QtQuick.Layouts

ColumnLayout {
    id: root
    property string title: ""
    property string caption: ""
    property int titleSize: 22
    property bool wrapCaption: true
    property color captionColor: DesignTokens.muted
    property int horizontalAlignment: Text.AlignLeft
    spacing: 7
    UiText {
        Layout.fillWidth: true
        text: root.title
        horizontalAlignment: root.horizontalAlignment
        font.pixelSize: root.titleSize
        font.weight: Font.DemiBold
    }
    UiText {
        visible: text.length > 0
        Layout.fillWidth: true
        text: root.caption
        horizontalAlignment: root.horizontalAlignment
        font.pixelSize: DesignTokens.comfortable ? 13 : 11
        color: root.captionColor
        wrapMode: root.wrapCaption ? Text.Wrap : Text.NoWrap
        elide: root.wrapCaption ? Text.ElideNone : Text.ElideRight
    }
}
