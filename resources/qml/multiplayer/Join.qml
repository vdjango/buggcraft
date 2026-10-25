import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

ScrollView {
    id: join
    property var vm: lobby.view
    property bool canJoin: !!vm.nodeAvailable && !vm.busy && !vm.instanceLoading
                           && !vm.needsVersion && invite.text.trim().length > 0
    clip: true
    contentWidth: availableWidth
    ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
    function submit() {
        if (canJoin) lobby.act("join", {invite:invite.text.trim(), transport:vm.transportPolicy})
    }
    ColumnLayout {
        width: join.availableWidth; spacing: 14
        Item { Layout.preferredHeight: 4 }
        Surface {
            objectName: "join-form-card"
            Layout.fillWidth: true; Layout.maximumWidth: 548; Layout.alignment: Qt.AlignHCenter
            implicitHeight: form.implicitHeight + 40
            color: "#e6221c2f"; border.color: "#685581"
            Rectangle { anchors.left: parent.left; anchors.top: parent.top; anchors.bottom: parent.bottom; width: 3; color: "#9875dc" }
            ColumnLayout {
                id: form
                anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
                anchors.margins: 20; spacing: 14
                RowLayout {
                    Layout.fillWidth: true; spacing: 12
                    Rectangle {
                        Layout.preferredWidth: 40; Layout.preferredHeight: 40
                        color: "#3c2d55"; border.color: "#796294"
                        Canvas {
                            anchors.centerIn: parent; width: 24; height: 24
                            onPaint: {
                                var c = getContext("2d")
                                c.fillStyle = "#d5c1ff"
                                c.fillRect(13, 3, 8, 3); c.fillRect(18, 3, 3, 18); c.fillRect(13, 18, 8, 3)
                                c.fillRect(3, 10, 11, 3); c.fillRect(9, 7, 3, 3); c.fillRect(9, 13, 3, 3)
                            }
                        }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true; spacing: 4
                        CopyText { Layout.fillWidth: true; text: "和朋友一起进入世界"; color: "#f3edff"; font.pixelSize: 17; font.bold: true }
                        CopyText { Layout.fillWidth: true; text: "粘贴房主分享的邀请码，即可加入房间。"; color: "#ab9aba"; font.pixelSize: 11 }
                    }
                }
                Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: "#463850" }
                ColumnLayout {
                    visible: !vm.needsVersion; Layout.fillWidth: true; spacing: 8
                    CopyText {
                        objectName: "join-room-label"; Layout.fillWidth: true
                        text: vm.joinRoomTitle ? vm.joinRoomTitle + " · 房间邀请码" : "房间邀请码"
                        color: "#e4daef"; font.pixelSize: 12; font.bold: true
                    }
                    InputField {
                        id: invite; objectName: "join-invite"
                        Layout.fillWidth: true; implicitHeight: 42
                        placeholderText: "粘贴邀请码，例如 bugg1-…"
                        echoMode: TextInput.PasswordEchoOnEdit
                        enabled: !vm.busy && !vm.instanceLoading
                        onAccepted: join.submit()
                    }
                    CopyText {
                        Layout.fillWidth: true; font.pixelSize: 11; color: "#a496b3"
                        text: vm.joinRoomId ? "请使用这个房间的专属邀请码。" : "与房主选择同一节点；邀请码仅分享给一起玩的朋友。"
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true; spacing: 7; visible: !vm.needsVersion
                    CopyText { text: "连接方式"; color: "#e4daef"; font.pixelSize: 12; font.bold: true }
                    ChoiceBox {
                        objectName: "join-transport"; Layout.fillWidth: true
                        model: ["自动连接 · 优先 P2P，失败时中转", "仅通过节点中转"]
                        enabled: !vm.busy && !vm.instanceLoading
                        currentIndex: vm.transportPolicy === "relay" ? 1 : 0
                        onActivated: function(index) { lobby.act("transport", {policy:index === 1 ? "relay" : "auto"}) }
                    }
                    CopyText {
                        Layout.fillWidth: true; font.pixelSize: 11; color: "#a496b3"
                        text: vm.transportPolicy === "relay" ? "游戏流量通过节点转发，对方不会通过 P2P 获得你的公网地址。"
                            : "优先直连；网络不支持时自动切换中转。"
                    }
                }
                CopyText {
                    visible: vm.needsVersion; Layout.fillWidth: true
                    text: "邀请码已保留，选择游戏实例后会自动继续。"; color: "#d1bfef"
                }
                CopyText {
                    objectName: "join-node-unavailable"; Layout.fillWidth: true
                    visible: !vm.nodeAvailable; color: "#dfbd92"; font.pixelSize: 11
                    text: "联机节点暂不可用，请返回大厅刷新节点后继续。"
                }
                Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: "#463850" }
                RowLayout {
                    objectName: "join-form-actions"
                    Layout.fillWidth: true; spacing: 10
                    CopyText { Layout.fillWidth: true; font.pixelSize: 10; color: "#a496b3"; text: "加入后可自动准备游戏文件" }
                    ActionButton {
                        objectName: "cancel-join"; text: "取消"; quiet: true
                        onClicked: lobby.act("navigate", {page:"hall"})
                    }
                    ActionButton {
                        objectName: "join-confirm"; implicitWidth: vm.needsVersion ? 142 : 100
                        text: vm.busy || vm.instanceLoading ? "正在连接…" : vm.needsVersion ? "请先选择游戏实例" : "加入房间"
                        primary: true; enabled: join.canJoin
                        onClicked: join.submit()
                    }
                }
            }
        }
        Item { Layout.preferredHeight: 6 }
    }
}
