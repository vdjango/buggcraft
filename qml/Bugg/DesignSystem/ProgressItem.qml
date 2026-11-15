import QtQuick
import QtQuick.Layouts

ColumnLayout {
    id: root
    property string title: ""
    property string state: ""
    property string caption: ""
    property string source: ""
    property real progress: 0
    property int titleSize: 12
    property int captionSize: 10
    property int titleWeight: Font.DemiBold
    property bool showBar: true
    spacing: 9
    RowLayout {
        Layout.fillWidth: true
        UiText {
            Layout.fillWidth: true
            text: root.title
            font.pixelSize: root.titleSize
            font.weight: root.titleWeight
        }
        UiText {
            text: root.state
            color: DesignTokens.muted
            font.pixelSize: 10
        }
    }
    ProgressSurface {
        Layout.fillWidth: true
        implicitHeight: 4
        visible: root.showBar
        active: true
        progress: root.progress
        cornerRadius: 2
        trackColor: DesignTokens.surfaceHover
    }
    UiText {
        Layout.fillWidth: true
        text: [root.source ? qsTr("来源：%1").arg(root.source) : "", root.caption].filter(Boolean).join("\n")
        font.pixelSize: root.captionSize
        color: DesignTokens.muted
        wrapMode: Text.Wrap
        elide: Text.ElideNone
    }
}
