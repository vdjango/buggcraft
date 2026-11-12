import QtQuick
import QtQuick.Layouts
import Bugg.DesignSystem

PageLayout {
    id: root
    property var identityStatus: ({})
    property bool locked: false
    signal microsoftLogoutRequested
    signal noticeRequested(string message)
    signal openRequested(string route)
    ListRow {
        Layout.fillWidth: true
        text: qsTr("Bugg 账号")
        caption: qsTr("联机、好友与邀请")
        iconName: "people"
        onClicked: root.openRequested("buggLogin")
    }
    ListRow {
        objectName: "accountIdentityRow"
        Layout.fillWidth: true
        text: qsTr("Minecraft 游戏身份")
        caption: root.identityStatus.name ? root.identityStatus.name + " · " + root.identityStatus.caption : qsTr("微软账号或离线玩家")
        iconName: "shield"
        onClicked: root.openRequested("identity")
    }
    SettingRow {
        visible: !!root.identityStatus.microsoftName
        Layout.fillWidth: true
        text: qsTr("已保留微软账号")
        value: root.identityStatus.microsoftName || ""
        iconName: ""
        enabled: false
    }
    ActionButton {
        objectName: "logoutMicrosoftButton"
        visible: !!root.identityStatus.microsoftName
        enabled: !root.locked
        text: qsTr("登出微软账号")
        variant: "outline"
        onClicked: root.microsoftLogoutRequested()
    }
}
