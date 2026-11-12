import QtQuick
import QtQuick.Layouts

// 有界列表的空态；调用方提供真实状态，组件只负责统一对齐和留白。
ColumnLayout {
    id: root
    property string title: ""
    property string caption: ""
    property string iconName: "people"
    spacing: 10
    AppIcon {
        Layout.alignment: Qt.AlignHCenter
        implicitWidth: 30
        implicitHeight: 30
        name: root.iconName
        color: DesignTokens.quiet
    }
    UiText {
        Layout.alignment: Qt.AlignHCenter
        text: root.title
        font.pixelSize: 15
        font.weight: Font.DemiBold
    }
    UiText {
        Layout.fillWidth: true
        visible: root.caption.length > 0
        text: root.caption
        color: DesignTokens.muted
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.Wrap
        font.pixelSize: 12
    }
}
