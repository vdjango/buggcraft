pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import Bugg.DesignSystem

PageLayout {
    id: root
    property var service: null
    property var status: service ? service.status : ({})
    property string inviteText: ""
    signal edited(string value)
    maximumWidth: 460
    spacing: 18
    UiText {
        Layout.fillWidth: true
        text: qsTr("需要房主邀请的房间，请粘贴邀请码后加入。")
        wrapMode: Text.Wrap
        color: DesignTokens.muted
    }
    FormField {
        objectName: "roomInviteField"
        Layout.fillWidth: true
        label: qsTr("房间邀请")
        placeholderText: qsTr("粘贴房主分享的邀请码")
        text: root.inviteText
        enabled: !root.status.roomBusy
        onTextEdited: value => root.edited(value)
    }
    NoticeBanner {
        Layout.fillWidth: true
        visible: !!root.status.error
        text: root.status.error || ""
        color: DesignTokens.danger
    }
    ActionButton {
        objectName: "joinRoomButton"
        Layout.fillWidth: true
        Layout.maximumWidth: Number.POSITIVE_INFINITY
        text: root.status.roomBusy ? qsTr("正在加入…") : qsTr("加入房间")
        enabled: root.status.state === "ready" && !root.status.roomBusy && !root.status.room && !!root.inviteText.trim()
        onClicked: root.service.join_room(root.inviteText)
    }
}
