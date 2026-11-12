import QtQuick
import QtQuick.Layouts
import Bugg.DesignSystem

PageLayout {
    id: root
    signal noticeRequested(string message)
    Avatar {
        Layout.alignment: Qt.AlignHCenter
        initials: "B"
        implicitWidth: 72
        implicitHeight: 72
    }
    UiText {
        Layout.alignment: Qt.AlignHCenter
        text: qsTr("选择你喜欢的样子")
        font.pixelSize: DesignTokens.comfortable ? 15 : 13
    }
    ActionButton {
        Layout.fillWidth: true
        text: qsTr("选择皮肤文件")
        iconName: "folder"
        compact: true
        onClicked: root.noticeRequested(qsTr("交互预览 · 皮肤服务尚未接入"))
    }
    UiText {
        Layout.fillWidth: true
        text: qsTr("支持 Minecraft PNG 皮肤；正版皮肤由微软账号管理。")
        font.pixelSize: DesignTokens.comfortable ? 13 : 11
        color: DesignTokens.muted
        wrapMode: Text.Wrap
        elide: Text.ElideNone
    }
}
