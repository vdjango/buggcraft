import QtQuick
import QtQuick.Layouts
import Bugg.DesignSystem

PageLayout {
    id: root
    property real viewportHeight: 440
    signal cancelRequested
    objectName: "joiningRoomPage"
    maximumWidth: 420
    minimumHeight: DesignTokens.comfortable ? viewportHeight : 300
    centered: true
    spacing: DesignTokens.comfortable ? 20 : 16
    Avatar {
        Layout.alignment: Qt.AlignHCenter
        implicitWidth: DesignTokens.comfortable ? 64 : 52
        implicitHeight: implicitWidth
        initials: "B"
    }
    PageHeader {
        Layout.fillWidth: true
        title: qsTr("正在加入房间")
        caption: qsTr("正在与房主建立连接，马上就好。")
        titleSize: DesignTokens.comfortable ? 23 : 19
        horizontalAlignment: Text.AlignHCenter
    }
    LoadingIndicator {
        objectName: "roomJoinProgress"
        Layout.alignment: Qt.AlignHCenter
        Layout.fillWidth: false
        text: qsTr("连接中…")
    }
    ActionButton {
        objectName: "cancelRoomJoinButton"
        Layout.alignment: Qt.AlignHCenter
        text: qsTr("取消加入")
        compact: true
        variant: "ghost"
        onClicked: root.cancelRequested()
    }
}
