import QtQuick
import QtQuick.Layouts
import Bugg.DesignSystem

PageLayout {
    id: root
    property real viewportHeight: 500
    property var identityStatus: ({})
    property bool locked: false
    property bool previewEnabled: false
    readonly property string authState: identityStatus.authState || "idle"
    signal beginRequested
    signal completeRequested
    signal cancelRequested
    maximumWidth: 400
    minimumHeight: DesignTokens.comfortable ? viewportHeight : 0
    centered: DesignTokens.comfortable
    PageHeader {
        Layout.fillWidth: true
        title: root.authState === "idle" ? qsTr("连接微软账号") : qsTr("等待完成授权")
        caption: root.previewEnabled ? qsTr("测试授权流程") : qsTr("在微软网页输入授权码，完成后自动返回")
        titleSize: 20
    }
    Surface {
        Layout.fillWidth: true
        visible: root.authState !== "idle"
        implicitHeight: codeContent.implicitHeight + padding * 2
        padding: 24
        Column {
            id: codeContent
            width: parent.width
            spacing: 12
            UiText {
                width: parent.width
                text: root.previewEnabled ? qsTr("演示授权码") : qsTr("微软授权码")
                horizontalAlignment: Text.AlignHCenter
                font.pixelSize: 12
                color: DesignTokens.muted
            }
            UiText {
                objectName: "microsoftDeviceCode"
                width: parent.width
                text: root.identityStatus.code || ""
                horizontalAlignment: Text.AlignHCenter
                font.pixelSize: 28
                font.letterSpacing: 2
            }
        }
    }
    ProgressItem {
        Layout.fillWidth: true
        visible: root.authState === "authorizing"
        title: qsTr("正在读取游戏身份")
        caption: qsTr("完成后自动返回")
        progress: -1
    }
    NoticeBanner {
        Layout.fillWidth: true
        text: root.identityStatus.error || ""
    }
    ActionButton {
        objectName: "microsoftAuthButton"
        Layout.fillWidth: true
        Layout.maximumWidth: Number.POSITIVE_INFINITY
        text: root.authState === "authorizing" ? qsTr("正在完成登录…") : root.authState === "waiting" ? (root.previewEnabled ? qsTr("模拟完成授权") : qsTr("复制授权码并打开微软网页")) : (root.previewEnabled ? qsTr("获取演示授权码") : qsTr("登录微软账号"))
        compact: true
        enabled: !root.locked && root.authState !== "authorizing"
        onClicked: {
            if (root.authState === "waiting")
                root.completeRequested();
            else
                root.beginRequested();
        }
    }
    ActionButton {
        objectName: "cancelMicrosoftAuthButton"
        Layout.fillWidth: true
        Layout.maximumWidth: Number.POSITIVE_INFINITY
        visible: root.authState !== "idle"
        variant: "ghost"
        compact: true
        text: qsTr("取消登录")
        onClicked: root.cancelRequested()
    }
}
