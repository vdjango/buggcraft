pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts

ColumnLayout {
    id: root

    property var status: ({})
    signal loginRequested
    signal logoutRequested
    signal settingsRequested

    objectName: "nodeLogin"
    spacing: 14

    Avatar {
        Layout.alignment: Qt.AlignHCenter
        implicitHeight: 56
        implicitWidth: 56
        initials: "B"
    }
    UiText {
        Layout.alignment: Qt.AlignHCenter
        font.pixelSize: 20
        font.weight: Font.DemiBold
        text: root.status.authorized ? qsTr("账号已授权") : qsTr("登录联机账号")
    }
    UiText {
        Layout.fillWidth: true
        horizontalAlignment: Text.AlignHCenter
        text: qsTr("登录后，与好友创建房间、同步游戏。")
        font.pixelSize: 12
        color: DesignTokens.muted
        wrapMode: Text.Wrap
    }
    ActionButton {
        Layout.alignment: Qt.AlignHCenter
        enabled: root.status.state !== "connecting" && (root.status.state !== "authorizing" || !!root.status.verificationUrl)
        objectName: "nodeBrowserLoginButton"
        text: root.status.state === "connecting" ? qsTr("正在连接…") : root.status.authorized ? qsTr("重试连接") : root.status.state === "authorizing" ? qsTr("重新打开授权页面") : qsTr("浏览器登录")

        onClicked: root.loginRequested()
    }
    UiText {
        Layout.alignment: Qt.AlignHCenter
        color: DesignTokens.muted
        text: qsTr("等待浏览器授权…")
        visible: root.status.state === "authorizing"
    }
    ActionButton {
        Layout.alignment: Qt.AlignHCenter
        text: qsTr("取消")
        variant: "ghost"
        visible: ["authorizing", "connecting"].includes(root.status.state)

        onClicked: root.logoutRequested()
    }
    ActionButton {
        objectName: "nodeServiceSettingsButton"
        Layout.alignment: Qt.AlignHCenter
        text: qsTr("联机服务设置")
        iconName: "settings"
        compact: true
        variant: "ghost"
        enabled: !["authorizing", "connecting"].includes(root.status.state)
        onClicked: root.settingsRequested()
    }
    NoticeBanner {
        Layout.fillWidth: true
        horizontalAlignment: Text.AlignHCenter
        color: DesignTokens.danger
        text: root.status.error || ""
        visible: !!root.status.error
    }
}
