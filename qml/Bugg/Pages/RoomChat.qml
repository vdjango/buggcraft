pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import Bugg.DesignSystem

// 房间与首页入口共用同一服务消息快照；输入草稿归 PageStateStore。
ColumnLayout {
    id: root
    property var service: null
    property var status: service ? service.status : ({})
    property string draft: ""
    property bool available: true
    property string emptyTitle: qsTr("房间聊天")
    property string emptyCaption: qsTr("和房间成员聊一聊")
    signal edited(string value)
    spacing: 10
    Connections {
        target: root.service
        function onChat_sent() {
            root.edited("");
        }
    }
    ListViewport {
        objectName: "roomChatViewport"
        Layout.fillWidth: true
        Layout.fillHeight: true
        Layout.minimumHeight: 100
        model: root.status.messages || []
        spacing: 16
        onCountChanged: positionViewAtEnd()
        delegate: ColumnLayout {
            required property var modelData
            width: ListView.view.width - 12
            spacing: 4
            UiText {
                Layout.fillWidth: true
                text: parent.modelData.sender || qsTr("玩家")
                font.pixelSize: 11
                color: DesignTokens.accent
            }
            UiText {
                Layout.fillWidth: true
                text: parent.modelData.text || ""
                Accessible.role: Accessible.StaticText
                Accessible.name: text
                Accessible.description: parent.modelData.sender || qsTr("玩家")
                textFormat: Text.PlainText
                wrapMode: Text.Wrap
                elide: Text.ElideNone
                font.pixelSize: 13
            }
        }
        EmptyState {
            anchors.centerIn: parent
            visible: parent.count === 0
            title: root.emptyTitle
            caption: root.emptyCaption
            iconName: "chat"
        }
    }
    NoticeBanner {
        Layout.fillWidth: true
        visible: !!root.status.chatError
        text: root.status.chatError || ""
        color: DesignTokens.danger
    }
    RowLayout {
        Layout.fillWidth: true
        Layout.bottomMargin: 16
        spacing: 8
        InputField {
            id: message
            objectName: "roomChatInput"
            Layout.fillWidth: true
            text: root.draft
            placeholderText: qsTr("发送消息")
            maximumLength: 256
            enabled: root.available && !root.status.chatBusy
            onTextEdited: root.edited(text)
            onAccepted: {
                if (text.trim().length && root.service)
                    root.service.send_chat(text);
            }
        }
        ActionButton {
            objectName: "roomChatSendButton"
            text: qsTr("发送")
            compact: true
            enabled: root.available && !!root.draft.trim().length && !root.status.chatBusy
            onClicked: root.service.send_chat(message.text)
        }
    }
}
