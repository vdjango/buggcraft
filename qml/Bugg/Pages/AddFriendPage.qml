pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import Bugg.DesignSystem

PageLayout {
    id: root
    property var service: null
    property var status: service ? service.status : ({})
    property string identifier: ""
    signal edited(string value)
    signal noticeRequested(string message)
    maximumWidth: 420
    spacing: 18
    FormField {
        objectName: "friendIdentifierField"
        Layout.fillWidth: true
        label: qsTr("好友码或用户名")
        placeholderText: qsTr("XXXX-XXXX-XXXX，或用户名")
        text: root.identifier
        enabled: !root.status.socialBusy
        onTextEdited: value => root.edited(value)
    }
    ActionButton {
        objectName: "sendFriendRequestButton"
        Layout.fillWidth: true
        Layout.maximumWidth: Number.POSITIVE_INFINITY
        text: root.status.socialBusy ? qsTr("正在发送…") : qsTr("发送好友申请")
        enabled: root.status.state === "ready" && !root.status.socialBusy && !!root.identifier.trim()
        onClicked: root.service.social("request", root.identifier, {})
    }
    Repeater {
        model: root.status.lookupResults || []
        ListRow {
            required property var modelData
            Layout.fillWidth: true
            text: modelData.username
            caption: modelData.friendCode
            iconName: "people"
            enabled: !root.status.socialBusy
            onClicked: root.service.social("request", modelData.account, {})
        }
    }
    NoticeBanner {
        Layout.fillWidth: true
        visible: !!root.status.error
        text: root.status.error || ""
        color: DesignTokens.danger
    }
    Divider {
        Layout.fillWidth: true
    }
    SettingRow {
        Layout.fillWidth: true
        text: qsTr("我的好友码")
        value: root.status.friendCode || "—"
        iconName: "copy"
        onClicked: {
            if (root.service.copy_friend_code())
                root.noticeRequested(qsTr("已复制好友码"));
        }
    }
}
