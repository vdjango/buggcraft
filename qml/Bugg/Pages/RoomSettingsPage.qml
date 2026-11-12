pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import Bugg.DesignSystem

PageLayout {
    id: root
    property var service: null
    property var status: service ? service.status : ({})
    property var room: status.room || ({})
    property var draft: ({})
    signal edited(string key, var value)
    maximumWidth: 540
    spacing: 18
    FormField {
        Layout.fillWidth: true
        label: qsTr("房间名称")
        text: root.draft.title === undefined ? root.room.title || "" : root.draft.title
        onTextEdited: value => root.edited("title", value)
    }
    SelectField {
        id: visibility
        objectName: "roomSettingsVisibility"
        Layout.fillWidth: true
        label: qsTr("可见范围")
        options: [
            {
                id: "private",
                name: qsTr("仅邀请")
            },
            {
                id: "public",
                name: qsTr("公开")
            },
            {
                id: "invite",
                name: qsTr("公开 · 需要邀请")
            }
        ]
        selection: root.draft.visibility || (root.room["public"] ? (root.room.requireInvite ? "invite" : "public") : "private")
        onChosen: id => root.edited("visibility", id)
    }
    CheckOption {
        objectName: "roomSharingOption"
        visible: root.room.role === "host"
        text: qsTr("加速缓存")
        checked: root.draft.sharing === undefined ? !!root.room.allowSharing : !!root.draft.sharing
        onToggled: root.edited("sharing", checked)
    }
    ActionButton {
        objectName: "saveRoomSettingsButton"
        Layout.alignment: Qt.AlignRight
        text: root.status.roomCommandBusy ? qsTr("正在保存…") : qsTr("保存")
        enabled: !!root.status.room && !root.status.roomCommandBusy
        onClicked: root.service.room_command("configure", Object.assign({
            title: root.draft.title === undefined ? root.room.title : root.draft.title,
            "public": visibility.selection !== "private",
            require_invite: visibility.selection !== "public"
        }, root.room.role === "host" ? {
            allow_mod_transfer: root.draft.sharing === undefined ? !!root.room.allowSharing : !!root.draft.sharing
        } : {}))
    }
    NoticeBanner {
        Layout.fillWidth: true
        visible: !!root.status.error
        text: root.status.error || ""
        color: DesignTokens.danger
    }
    ColumnLayout {
        Layout.fillWidth: true
        visible: ((root.room.lobby || {}).blocked || []).length > 0
        spacing: 10
        Divider {
            Layout.fillWidth: true
        }
        UiText {
            text: qsTr("移出记录")
            font.weight: Font.DemiBold
        }
        ListViewport {
            Layout.fillWidth: true
            Layout.preferredHeight: Math.min(220, contentHeight)
            model: (root.room.lobby || {}).blocked || []
            delegate: ListRow {
                required property var modelData
                width: ListView.view.width
                text: modelData.name
                value: qsTr("允许加入")
                iconName: "people"
                enabled: !root.status.roomCommandBusy
                onClicked: root.service.room_command("member_unblock", {
                    member: modelData.id
                })
            }
        }
    }
}
