import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

ColumnLayout {
    id: join
    property var vm: lobby.view
    spacing: 12
    ScrollView {
        Layout.fillWidth: true; Layout.fillHeight: true
        clip: true; contentWidth: availableWidth
        ColumnLayout {
            width: parent.width; spacing: 10
            Surface {
                Layout.fillWidth: true; Layout.alignment: Qt.AlignHCenter
                implicitHeight: form.implicitHeight + 24
                ColumnLayout {
                    id: form
                    anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 12
                    spacing: 10
                    ColumnLayout {
                        visible: !vm.needsVersion; Layout.fillWidth: true; spacing: 10
                        CopyText { objectName: "join-room-label"; Layout.fillWidth: true; text: vm.joinRoomTitle ? vm.joinRoomTitle + " · 需要邀请码" : "房间邀请码" }
                        InputField { id: invite; objectName: "join-invite"; Layout.fillWidth: true; placeholderText: "bugg1-…"; echoMode: TextInput.PasswordEchoOnEdit; onAccepted: if (vm.nodeAvailable && !vm.busy && text.trim()) lobby.act("join", {invite:text}) }
                        CopyText { Layout.fillWidth: true; text: vm.joinRoomId ? "请向该房主获取邀请码，填写后加入这个房间。" : "请和朋友选择相同节点。邀请码只发给你想一起玩的朋友。"; font.pixelSize: 12 }
                        CopyText { Layout.fillWidth: true; text: "连接方式"; color: "#d5cfe3" }
                        ChoiceBox {
                            objectName: "join-transport"
                            Layout.fillWidth: true
                            model: ["优先 P2P，失败时自动中转", "仅通过节点中转"]
                            currentIndex: vm.transportPolicy === "relay" ? 1 : 0
                            onActivated: function(index) { lobby.act("transport", {policy:index === 1 ? "relay" : "auto"}) }
                        }
                        CopyText {
                            Layout.fillWidth: true; font.pixelSize: 11
                            text: vm.transportPolicy === "relay" ? "游戏流量经节点转发；对端不会通过 P2P 获得你的公网地址。" : "默认尝试 P2P。网络不支持直连时，游戏流量自动经节点转发。"
                        }
                    }
                    CopyText { visible: vm.needsVersion; Layout.fillWidth: true; text: "邀请码已保留，选择上方实例后会自动继续。" }
                    CopyText { Layout.fillWidth: true; text: "加入后可查看版本与模组，快速启动游戏；缺少文件时可自动准备。"; font.pixelSize: 12 }
                }
            }
        }
    }
    CopyText {
        objectName: "join-node-unavailable"; Layout.fillWidth: true
        visible: !vm.nodeAvailable; color: "#dfbd92"; font.pixelSize: 12
        text: "联机节点暂不可用，请返回大厅刷新节点后继续。"
    }
    RowLayout {
        Layout.fillWidth: true
        Item { Layout.fillWidth: true }
        ActionButton {
            objectName: "cancel-join"; text: "取消"; quiet: true
            onClicked: lobby.act("navigate", {page:"hall"})
        }
        ActionButton {
            objectName: "join-confirm"
            text: vm.busy || vm.instanceLoading ? "正在准备连接…" : vm.needsVersion ? "请先选择游戏实例" : "加入房间"
            primary: true; enabled: !!vm.nodeAvailable && !vm.busy && !vm.instanceLoading && !vm.needsVersion && invite.text.trim().length > 0
            onClicked: lobby.act("join", {invite:invite.text, transport:vm.transportPolicy})
        }
    }
}
