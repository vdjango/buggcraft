import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../shared" as Shared

Item {
    id: root
    property var state: homePage.view
    Connections { target: homePage; function onChanged() { root.state = homePage.view } }
    Row {
        anchors.fill: parent
        anchors.leftMargin: 15; anchors.rightMargin: 15
        spacing: 6
        Sidebar {
            visible: !root.state.collapsed
            width: 199; height: parent.height
            entries: ["离线登录", "正版登录"]
            currentIndex: root.state.mode === "offline" ? 0 : 1
            resourceBase: root.state.resources
            onActivated: index => homePage.chooseMode(index === 0 ? "offline" : "online")
        }
        Item {
            width: 686; height: parent.height
            ColumnLayout {
                anchors.centerIn: parent
                width: Math.min(parent.width - 50, 440)
                spacing: 10
                Image { Layout.alignment: Qt.AlignHCenter; Layout.preferredWidth: implicitWidth; Layout.preferredHeight: implicitHeight; source: root.state.resources + "images/user/MINECRAFT.png" }
                Image { Layout.alignment: Qt.AlignHCenter; Layout.preferredWidth: 80; Layout.preferredHeight: 80; source: root.state.avatar; fillMode: Image.PreserveAspectCrop; smooth: false }
                Label { Layout.alignment: Qt.AlignHCenter; text: root.state.username; color: "#f8f8f8"; font.pixelSize: 13 }
                RowLayout {
                    visible: !root.state.authenticated && root.state.mode === "offline"
                    Layout.alignment: Qt.AlignHCenter
                    spacing: 0
                    InputField { id: username; Layout.preferredWidth: 192; Layout.preferredHeight: 40; placeholderText: "请输入用户名"; onAccepted: homePage.loginOffline(text) }
                    ActionButton { text: "确认"; primary: true; Layout.preferredWidth: 50; Layout.preferredHeight: 40; onClicked: homePage.loginOffline(username.text) }
                }
                ActionButton { visible: !root.state.authenticated && root.state.mode === "online"; text: "正版登录"; primary: true; Layout.preferredWidth: 235; Layout.alignment: Qt.AlignHCenter; onClicked: homePage.loginOnline() }
                ActionButton { visible: root.state.authenticated; text: "切换账号"; Layout.preferredWidth: 162; Layout.alignment: Qt.AlignHCenter; onClicked: homePage.switchAccount() }
                Item { Layout.preferredHeight: 10 }
                Button {
                    id: launchButton
                    objectName: "launch-game"
                    Layout.alignment: Qt.AlignHCenter
                    Layout.preferredWidth: 239; Layout.preferredHeight: 74
                    enabled: root.state.launchEnabled
                    background: Image { source: root.state.resources + "images/user/start_game_btn.png" }
                    contentItem: Item {
                        Column {
                            anchors.centerIn: parent
                            spacing: 2
                            Text { width: 220; text: root.state.launchTitle; color: "#6d6ffe"; font.pixelSize: 17; font.weight: Font.Bold; horizontalAlignment: Text.AlignHCenter }
                            Text { width: 220; text: root.state.launchSubtitle; color: "#6d6ffe"; font.pixelSize: 13; elide: Text.ElideMiddle; horizontalAlignment: Text.AlignHCenter }
                        }
                    }
                    onClicked: homePage.launch(root.state.allowMultiple)
                    ActionButton {
                        objectName: "game-session-actions"
                        anchors.right: parent.right; anchors.rightMargin: 9; anchors.verticalCenter: parent.verticalCenter
                        width: 25; height: 28; padding: 0; text: "⋮"
                        visible: root.state.allowMultiple; background: Item {}
                        onClicked: sessionMenu.open()
                    }
                    Menu {
                        id: sessionMenu
                        popupType: Popup.Item
                        y: launchButton.height; width: 239
                        background: Rectangle { color: "#211f2b"; border.color: "#8b85da" }
                        MenuItem { text: "停止当前游戏"; onTriggered: homePage.stopSelected() }
                    }
                }
                ChoiceBox {
                    visible: root.state.sessions.length > 1
                    Layout.fillWidth: true
                    model: root.state.sessions.map(item => item.label)
                    currentIndex: Math.max(0, root.state.sessions.findIndex(item => item.id === root.state.selectedSession))
                    onActivated: homePage.selectSession(root.state.sessions[currentIndex].id)
                }
                RowLayout {
                    Layout.alignment: Qt.AlignHCenter
                    spacing: 8
                    HeaderAction {
                        id: lobbyButton
                        objectName: "open-lobby-home"; Layout.preferredWidth: 160; Layout.preferredHeight: 35
                        text: root.state.multiplayerTitle
                        artwork: root.state.resources + "images/bar/version_Settings_background.png"
                        onClicked: { homePage.social("lobby"); tutorial.action("lobby") }
                        Shared.AttentionFrame { objectName: "home-multiplayer-glow"; active: root.state.multiplayerAttention }
                    }
                    HeaderAction {
                        objectName: "open-friends-home"; visible: root.state.friendsVisible
                        Layout.preferredWidth: 92; Layout.preferredHeight: 35
                        text: "好友"; artwork: root.state.resources + "images/bar/version_Settings_background.png"
                        onClicked: homePage.social("friends")
                        Shared.AttentionFrame { objectName: "home-friends-glow"; active: !!(root.state.friendNotifications || {}).homeAttention; tint: (root.state.friendNotifications || {}).urgent ? "#f283aa" : "#a68aff" }
                        Shared.NotificationBadge { objectName: "home-friends-badge"; anchors.right: parent.right; anchors.top: parent.top; anchors.rightMargin: -5; anchors.topMargin: -6; z: 6; count: (root.state.friendNotifications || {}).total || 0; urgent: !!(root.state.friendNotifications || {}).urgent }
                    }
                }
                Label { Layout.fillWidth: true; visible: !!root.state.status; text: root.state.status; color: "#dccded"; wrapMode: Text.Wrap; horizontalAlignment: Text.AlignHCenter; font.pixelSize: 11 }
            }
        }
    }
}
