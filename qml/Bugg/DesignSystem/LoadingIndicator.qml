import QtQuick
import QtQuick.Layouts

// Indeterminate waiting has no numeric progress or expanding progress track.
RowLayout {
    id: root
    property string text: qsTr("加载中…")
    spacing: 8
    AppIcon {
        name: "refresh"
        color: DesignTokens.accent
        implicitWidth: 22
        implicitHeight: 22
        Accessible.name: root.text
        NumberAnimation on rotation {
            from: 0
            to: 360
            duration: 900
            loops: Animation.Infinite
            running: root.visible
        }
    }
    UiText {
        Layout.fillWidth: true
        text: root.text
        color: DesignTokens.muted
        font.pixelSize: DesignTokens.controlTextSize
    }
}
