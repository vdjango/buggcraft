import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Rectangle {
    id: root
    width: 721
    height: 505
    color: "#17151f"
    border.color: "#9281d3"
    border.width: 2
    property var vm: lobby.view
    property string page: vm.page
    property var titles: ({hall:"BUGG·联机大厅", create:"创建房间", join:"加入房间",
        friends:"好友", friendForm:vm.editIndex >= 0 ? "编辑好友" : "添加好友",
        connections:"我的房间", connected:"房间详情", worldPicker:"重新开放世界", nodes:"联机节点"})
    property var selectedRoom: vm.connections.find(function(c) { return c.id === vm.selected }) || ({role:"client",state:"stopped"})
    property bool managingRoom: selectedRoom.isManager !== undefined ? selectedRoom.isManager : selectedRoom.role === "host"
    function goBack() {
        if (root.page === "connected") leavePopup.open()
        else lobby.act("navigate", {page:root.page === "friendForm" ? "friends" : root.page === "worldPicker" ? "connected" : "hall"})
    }

    Rectangle { anchors.fill: parent; anchors.margins: 2; color: "#17151f" }
    Image {
        anchors.fill: parent; anchors.margins: 2
        source: "../../images/multiplayer_bg.png"
        fillMode: Image.PreserveAspectCrop
        opacity: 0.9
    }
    Rectangle { anchors.fill: parent; anchors.margins: 2; color: "#8813111a" }

    WindowHeader {
        objectName: "window-header"
        x: 2; y: 2; width: parent.width - 4
        title: root.page === "connected" ? root.selectedRoom.title || "房间详情" : root.titles[root.page] || "BUGG·联机大厅"
        brandSource: root.page === "hall" ? "../../images/bugg-logo.png" : ""
        brandTitle: "· 联机大厅"
        navigationVisible: root.page !== "hall" && root.page !== "friends"
        navigationText: "‹"
        navigationName: root.page === "connected" ? "返回并断开连接" : "返回"
        closeName: "关闭窗口，保留联机"
        onNavigate: root.goBack()
        onMinimize: lobby.act("minimize", {})
        onCloseRequested: lobby.act("close", {})
        onDragRequested: lobby.act("drag", {})
    }

    ColumnLayout {
        id: content
        x: 14; y: 56
        width: parent.width - 28; height: parent.height - y - 14; spacing: 8
        Surface {
            objectName: "node-code-expired-banner"
            Layout.fillWidth: true; Layout.preferredHeight: renewalRow.implicitHeight + 20
            visible: !!vm.nodeAccessExpired
            color: "#352736"; border.color: "#b38a71"
            RowLayout {
                id: renewalRow
                anchors.fill: parent; anchors.margins: 10; spacing: 10
                ColumnLayout {
                    Layout.fillWidth: true; spacing: 3
                    CopyText { text: "个人接入码已过期"; color: "#ffdcc0"; font.bold: true; font.pixelSize: 13 }
                    CopyText { Layout.fillWidth: true; text: "在原节点网页登录并领取新码，替换后即可恢复好友和房间功能。"; font.pixelSize: 11; color: "#e4cad8" }
                }
                ActionButton { objectName: "replace-expired-node-code"; text: "更换接入码"; primary: true; implicitHeight: 30; onClicked: lobby.act("replaceNodeCode", {}) }
            }
        }
        Loader {
            id: pageLoader
            objectName: "page-loader"; Layout.fillWidth: true; Layout.fillHeight: true
            source: ({hall:"Hall.qml",create:"Create.qml",join:"Join.qml",friends:"Friends.qml",
                friendForm:"FriendForm.qml",connections:"ConnectionsPage.qml",connected:"Connected.qml",
                nodes:"Nodes.qml",worldPicker:"WorldPicker.qml"})[root.page] || "Hall.qml"
        }
    }
    Rectangle {
        id: feedbackBar
        objectName: "feedback-toast"
        z: 30
        width: Math.min(root.width - 48, 540); height: Math.max(38, statusText.implicitHeight + 16)
        anchors.horizontalCenter: parent.horizontalCenter
        y: root.height - height - 18
        visible: !vm.invitePrompt && (vm.error.length > 0 || vm.notice.length > 0)
        color: vm.error.length > 0 ? "#452830" : "#342943"
        border.color: vm.error.length > 0 ? "#925766" : "#625482"
        RowLayout {
            anchors.fill: parent; anchors.margins: 8; spacing: 8
            CopyText {
                id: statusText; objectName: "feedback"; Layout.fillWidth: true
                text: vm.error || vm.notice; font.pixelSize: 11; maximumLineCount: 2
                elide: Text.ElideRight; color: vm.error.length > 0 ? "#ffc2bd" : "#ddd3fa"
            }
            HeaderAction {
                objectName: "dismiss-feedback"; text: "×"
                label: vm.error ? "关闭错误提示" : "关闭提示"
                onClicked: lobby.act(vm.error ? "clearError" : "dismiss", {})
            }
        }
    }
    Timer {
        interval: 4000; running: vm.notice.length > 0 && !vm.error
        onTriggered: lobby.act("dismiss", {})
    }
    Popup {
        id: leavePopup; objectName: "leave-room-dialog"
        parent: Overlay.overlay; anchors.centerIn: parent
        width: Math.min(390, parent.width - 48); padding: 20; modal: true; focus: true
        closePolicy: Popup.CloseOnEscape
        background: Surface { color: "#251f30"; border.color: "#7e699e" }
        contentItem: ColumnLayout {
            spacing: 14
            CopyText { text: root.managingRoom ? "关闭房间并返回？" : "断开连接并返回？"; font.pixelSize: 16; font.bold: true; color: "#f3efff" }
            CopyText {
                Layout.fillWidth: true
                text: root.managingRoom ? "关闭房间会断开所有朋友的联机连接。" : root.selectedRoom.role === "host" ? "世界将停止开放，准备房间由新房主继续管理。" : "返回大厅会断开当前房间的游戏连接和聊天。"
                font.pixelSize: 12
            }
            RowLayout {
                Layout.fillWidth: true; spacing: 10
                Item { Layout.fillWidth: true }
                ActionButton { objectName: "cancel-leave-room"; text: "留在房间"; onClicked: leavePopup.close() }
                ActionButton {
                    objectName: "confirm-leave-room"; text: root.managingRoom ? "关闭房间" : "断开连接"; danger: true
                    onClicked: { leavePopup.close(); lobby.act("stop", {id:vm.selected}) }
                }
            }
        }
    }
    Popup {
        id: nodeUpdatePopup; objectName: "node-update-dialog"
        parent: Overlay.overlay; anchors.centerIn: parent
        width: Math.min(430, parent.width - 48); padding: 20; modal: true; focus: true
        visible: !!vm.nodeUpdatePrompt
        closePolicy: Popup.NoAutoClose
        background: Surface { color: "#251f30"; border.color: "#7e699e" }
        contentItem: ColumnLayout {
            spacing: 14
            CopyText { text: "更新已有节点？"; font.pixelSize: 16; font.bold: true; color: "#f3efff" }
            CopyText { Layout.fillWidth: true; text: vm.nodeUpdateMessage || ""; font.pixelSize: 12; wrapMode: Text.Wrap }
            RowLayout {
                Layout.fillWidth: true; spacing: 10
                Item { Layout.fillWidth: true }
                ActionButton { objectName: "cancel-node-update"; text: "保留原配置"; onClicked: lobby.act("cancelNodeUpdate", {}) }
                ActionButton { objectName: "confirm-node-update"; text: "确认更新"; primary: true; onClicked: lobby.act("confirmNodeUpdate", {}) }
            }
        }
        Shortcut { sequence: "Escape"; enabled: nodeUpdatePopup.visible; onActivated: lobby.act("cancelNodeUpdate", {}) }
    }
    onPageChanged: {
        if (page !== "connected") leavePopup.close()
    }
    Popup {
        id: openWorldPopup; objectName: "open-world-create-room-dialog"
        parent: Overlay.overlay; anchors.centerIn: parent
        width: Math.min(430, parent.width - 48); padding: 20; modal: true; focus: true
        visible: !!vm.openWorldPrompt
        closePolicy: Popup.NoAutoClose
        background: Surface { color: "#251f30"; border.color: "#8a72c7" }
        contentItem: ColumnLayout {
            spacing: 12
            CopyText { text: vm.openWorldMode === "associate" ? "找到可以关联的游戏世界" : "发现已开放的局域网世界"; color: "#f3efff"; font.pixelSize: 16; font.bold: true }
            CopyText { Layout.fillWidth: true; text: vm.openWorldMode === "associate" ? "要将这个世界关联到你已创建的房间吗？关联后，房间里的好友即可加入。" : "要把这个世界分享给好友吗？创建房间后，好友可通过邀请码或联机大厅加入。"; color: "#cfc3e0"; font.pixelSize: 12; wrapMode: Text.Wrap }
            CopyText { text: "游戏端口  " + vm.openWorldPort; color: "#a998d4"; font.pixelSize: 11 }
            RowLayout {
                Layout.fillWidth: true; spacing: 10
                Item { Layout.fillWidth: true }
                ActionButton { objectName: "dismiss-open-world-prompt"; text: "暂不创建"; onClicked: lobby.act("dismissOpenWorld", {}) }
                ActionButton { objectName: "create-room-for-open-world"; text: vm.openWorldMode === "associate" ? "关联房间" : "创建房间"; primary: true; onClicked: lobby.act("createFromOpenWorld", {port:vm.openWorldPort}) }
            }
        }
    }
    Popup {
        id: invitePopup; objectName: "room-invite-dialog"
        parent: Overlay.overlay; anchors.centerIn: parent
        width: Math.min(420, parent.width - 48); padding: 20; modal: true; focus: true
        visible: !!vm.invitePrompt
        closePolicy: Popup.NoAutoClose
        onOpened: { roomInvite.text = ""; roomInvite.forceActiveFocus() }
        background: Surface { color: "#251f30"; border.color: "#7e699e" }
        contentItem: ColumnLayout {
            spacing: 14
            CopyText { text: "加入房间"; color: "#f3efff"; font.pixelSize: 16; font.bold: true }
            CopyText { Layout.fillWidth: true; text: vm.joinRoomTitle || ""; color: "#cfc3e0"; font.pixelSize: 13; maximumLineCount: 2; elide: Text.ElideRight }
            InputField {
                id: roomInvite; objectName: "room-invite-input"
                Layout.fillWidth: true; placeholderText: "粘贴房主分享的邀请码"; maximumLength: 140
                echoMode: TextInput.PasswordEchoOnEdit
                enabled: !vm.busy
                onAccepted: if (vm.nodeAvailable && text.trim() && !vm.busy) lobby.act("join", {invite:text})
            }
            CopyText { Layout.fillWidth: true; text: "此房间已开启邀请保护，请向房主获取邀请码。"; font.pixelSize: 12 }
            CopyText { Layout.fillWidth: true; visible: !vm.nodeAvailable; text: "联机节点暂不可用，请取消后刷新节点。"; color: "#dfbd92"; font.pixelSize: 12 }
            CopyText { objectName: "room-invite-error"; Layout.fillWidth: true; visible: !!vm.error; text: vm.error; color: "#ffb5bb"; font.pixelSize: 12 }
            RowLayout {
                Layout.fillWidth: true; spacing: 10
                Item { Layout.fillWidth: true }
                ActionButton { objectName: "cancel-room-invite"; text: "取消"; onClicked: lobby.act("cancelInvite", {}) }
                ActionButton { objectName: "confirm-room-invite"; text: vm.busy ? "正在加入…" : "加入"; primary: true; enabled: !!vm.nodeAvailable && !vm.busy && roomInvite.text.trim().length > 0; onClicked: lobby.act("join", {invite:roomInvite.text}) }
            }
        }
        Shortcut { sequence: "Escape"; enabled: invitePopup.visible; onActivated: lobby.act("cancelInvite", {}) }
    }
    FloatingFriends {
        id: friendsFloat
        objectName: "open-friends-window"
        visible: root.page === "hall" && !!vm.friendEntryAvailable
        x: root.width - width - 25; y: maximumY - 11
        maximumX: root.width - width - 14
        minimumY: 160
        maximumY: feedbackBar.visible ? feedbackBar.y - height - 10 : root.height - height - 14
        onClicked: lobby.act("openFriends", {})
    }
    Shortcut {
        sequence: "Escape"
        enabled: !invitePopup.visible && !leavePopup.visible && !nodeUpdatePopup.visible
        onActivated: root.page === "hall" ? lobby.act("close", {}) : root.goBack()
    }
}
