import QtQuick
import QtQuick.Layouts
import Bugg.DesignSystem

PageLayout {
    id: root
    property real viewportHeight: 500
    property var identityStatus: ({})
    property bool locked: false
    maximumWidth: 840
    minimumHeight: DesignTokens.comfortable ? viewportHeight : 0
    centered: DesignTokens.comfortable
    signal openRequested(string route)
    signal noticeRequested(string message)
    GridLayout {
        Layout.fillWidth: true
        columns: DesignTokens.comfortable ? 2 : 1
        columnSpacing: 48
        ColumnLayout {
            objectName: "identitySummary"
            visible: DesignTokens.comfortable
            // 摘要窄列居中，剩余宽度交给登录选项；不靠位移抵消外层留白。
            Layout.fillWidth: false
            Layout.preferredWidth: 264
            Layout.alignment: Qt.AlignCenter
            spacing: 16
            Avatar {
                objectName: "identityAvatar"
                Layout.alignment: Qt.AlignHCenter
                initials: root.identityStatus.initials || "?"
                implicitWidth: 68
                implicitHeight: 68
            }
            UiText {
                objectName: "identityName"
                Layout.fillWidth: true
                horizontalAlignment: Text.AlignHCenter
                text: root.identityStatus.name || qsTr("尚未选择身份")
                font.pixelSize: 23
                font.weight: Font.DemiBold
            }
            UiText {
                Layout.fillWidth: true
                horizontalAlignment: Text.AlignHCenter
                text: qsTr(root.identityStatus.caption || "") || qsTr("选择一种方式，进入游戏")
                font.pixelSize: 12
                color: DesignTokens.muted
            }
        }
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 12
            Surface {
                Layout.fillWidth: true
                implicitHeight: methods.implicitHeight + padding * 2
                padding: DesignTokens.comfortable ? 10 : 6
                color: DesignTokens.canvas
                Column {
                    id: methods
                    width: parent.width
                    spacing: 2
                    ListRow {
                        objectName: "microsoftLoginOption"
                        width: parent.width
                        text: qsTr("微软账号")
                        caption: root.identityStatus.microsoftName ? qsTr(root.identityStatus.microsoftCaption || "") + " · " + root.identityStatus.microsoftName : qsTr("使用已购买 Minecraft Java 版的账号")
                        iconName: "shield"
                        enabled: !root.locked
                        selected: root.identityStatus.kind === "microsoft"
                        onClicked: root.openRequested("deviceAuth")
                    }
                    ListRow {
                        objectName: "offlineLoginOption"
                        width: parent.width
                        text: qsTr("离线身份")
                        caption: qsTr("使用自己的玩家名称")
                        iconName: "people"
                        enabled: !root.locked
                        selected: root.identityStatus.kind === "offline"
                        onClicked: root.openRequested("offlineIdentity")
                    }
                    ListRow {
                        objectName: "thirdPartyLoginOption"
                        width: parent.width
                        text: qsTr("第三方登录（待更新）")
                        caption: qsTr("更多账号登录方式")
                        iconName: "link"
                        enabled: false
                        opacity: 0.5
                    }
                }
            }
            SettingRow {
                objectName: "identitySkinOption"
                Layout.fillWidth: true
                Layout.topMargin: 12
                text: qsTr("皮肤")
                value: qsTr("待更新")
                iconName: ""
                enabled: false
                opacity: 0.6
            }
        }
    }
}
