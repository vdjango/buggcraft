import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

ColumnLayout {
    id: nodesPage
    property var vm: lobby.view
    property bool removing: false
    property bool loggingIn: !!vm.deviceLoginBusy
    spacing: 10
    Connections {
        target: lobby
        ignoreUnknownSignals: true
        function onChanged() { nodesPage.removing = false }
    }
    RowLayout {
        Layout.fillWidth: true; Layout.fillHeight: true; spacing: 12
        Surface {
            Layout.preferredWidth: 212; Layout.fillHeight: true
            ColumnLayout {
                anchors.fill: parent; anchors.margins: 14; spacing: 12
                RowLayout {
                    Layout.fillWidth: true
                    CopyText { text: "我的节点"; font.pixelSize: 14; font.bold: true; color: "#eee8fa" }
                    Item { Layout.fillWidth: true }
                    CopyText { text: vm.nodes.length + " 个"; font.pixelSize: 11; color: "#baaccb" }
                }
                CopyText { Layout.fillWidth: true; text: "选择已保存的入口，或在右侧添加"; font.pixelSize: 11; color: "#aa9bbc" }
                ListView {
                    id: list; objectName: "nodes-list"
                    Layout.fillWidth: true; Layout.fillHeight: true
                    model: vm.nodes; spacing: 8; clip: true
                    ScrollBar.vertical: ScrollBar {}
                    delegate: Button {
                        required property var modelData
                        required property int index
                        objectName: "choose-node-" + index
                        width: list.width; height: 72; padding: 10
                        Accessible.name: "使用节点 " + modelData.title
                        contentItem: ColumnLayout {
                            spacing: 5
                            CopyText { Layout.fillWidth: true; text: modelData.title; color: "#f2ecff"; font.pixelSize: 12; elide: Text.ElideMiddle; wrapMode: Text.NoWrap }
                            CopyText {
                                Layout.fillWidth: true
                                text: modelData.codeExpired ? "登录已失效 · 请重新登录"
                                    : (vm.nodeIndex === index ? "● 当前入口" : "切换至此节点 →")
                                      + (modelData.deviceManaged || modelData.personalCode ? " · 账号登录" : " · 匿名接入")
                                color: modelData.codeExpired ? "#f0c49c" : vm.nodeIndex === index ? "#9dd4b8" : "#b4a6ca"
                                font.pixelSize: 10
                            }
                        }
                        background: Rectangle {
                            color: vm.nodeIndex === index ? "#382c4d" : parent.hovered ? "#2f283b" : "#231f2d"
                            border.color: vm.nodeIndex === index ? "#a18acb" : "#44394f"
                            Rectangle { width: 2; height: parent.height - 16; y: 8; color: "#b79ae6"; visible: vm.nodeIndex === index }
                        }
                        enabled: !vm.connections.length && !nodesPage.loggingIn
                        onClicked: { nodesPage.removing = false; lobby.act("node", {index:index}) }
                    }
                    Column {
                        anchors.centerIn: parent; width: parent.width - 12; spacing: 12
                        visible: vm.nodes.length === 0
                        CopyText { width: parent.width; text: "还没有添加节点"; horizontalAlignment: Text.AlignHCenter; font.pixelSize: 13; color: "#ded3ee" }
                        CopyText { width: parent.width; text: "填写右侧地址并登录\n授权后会自动保存在这里"; horizontalAlignment: Text.AlignHCenter; font.pixelSize: 11; color: "#a79ab6" }
                    }
                }
                ActionButton {
                    objectName: "remove-node"; text: nodesPage.removing ? "确认移除节点" : "移除所选节点"
                    Layout.fillWidth: true; implicitHeight: 30
                    enabled: vm.nodeIndex >= 0 && !vm.connections.length && !nodesPage.loggingIn
                    danger: true; quiet: true
                    onClicked: { if (nodesPage.removing) { nodesPage.removing = false; lobby.act("removeNode", {}) } else nodesPage.removing = true }
                }
            }
        }
        Surface {
            Layout.fillWidth: true; Layout.fillHeight: true
            color: "#ed241d32"; border.color: "#645077"
            ScrollView {
                id: formScroll
                objectName: "node-login-scroll"
                anchors.fill: parent; anchors.margins: 18
                contentWidth: availableWidth; clip: true
                ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                ColumnLayout {
                    width: formScroll.availableWidth; spacing: 12
                    ColumnLayout {
                        Layout.fillWidth: true; spacing: 5
                        CopyText { text: "添加联机节点"; font.pixelSize: 20; font.bold: true; color: "#f0e8ff" }
                        CopyText { Layout.fillWidth: true; text: "填写地址，在浏览器登录一次，即可自动连接。"; font.pixelSize: 12; color: "#c7bad8" }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true; spacing: 7
                        CopyText { text: "1  节点地址"; font.pixelSize: 12; color: "#e5dcf3"; font.bold: true }
                        InputField {
                            id: nodeAddress
                            objectName: "node-web-address"; Layout.fillWidth: true; Layout.preferredHeight: 38
                            placeholderText: "域名或 IP，例如 node.bugg.icu"; maximumLength: 320
                            enabled: !nodesPage.loggingIn && !vm.busy
                            text: vm.deviceOrigin || ""
                            onTextEdited: lobby.act("deviceOrigin", {text:text})
                            onAccepted: if (loginButton.enabled) lobby.act("loginOfficialDevice", {remember: rememberDevice.checked, origin:text})
                        }
                        CopyText { Layout.fillWidth: true; text: "支持 HTTPS 域名或 IP，可带端口。官方：node.bugg.icu"; font.pixelSize: 11; color: "#ad9dbe" }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true; spacing: 3
                        CheckBox {
                            id: rememberDevice; objectName: "remember-device-login"; checked: true
                            Layout.fillWidth: true; implicitHeight: 28
                            enabled: !nodesPage.loggingIn
                            text: "保持登录"; spacing: 9
                            Accessible.name: "保持登录，自动续期节点账号授权"
                            indicator: Rectangle {
                                implicitWidth: 18; implicitHeight: 18
                                x: rememberDevice.leftPadding; y: (rememberDevice.height - height) / 2
                                radius: 3; color: rememberDevice.checked ? "#8060d8" : "#211a2c"
                                border.width: rememberDevice.activeFocus ? 2 : 1
                                border.color: rememberDevice.activeFocus ? "#e0d0ff" : "#aa8ed3"
                                Text { anchors.centerIn: parent; text: "✓"; color: "white"; font.pixelSize: 14; visible: rememberDevice.checked }
                            }
                            contentItem: Text {
                                objectName: "remember-device-label"
                                text: rememberDevice.text; font.family: Qt.application.font.family
                                font.pixelSize: 13; color: rememberDevice.enabled ? "#f0e8ff" : "#c0b4d0"
                                leftPadding: rememberDevice.indicator.width + rememberDevice.spacing
                                verticalAlignment: Text.AlignVCenter
                            }
                        }
                        CopyText { Layout.fillWidth: true; text: "30 天未使用失效，最长 180 天；不勾选时登录保持 8 小时。"; font.pixelSize: 11; color: "#ad9dbe" }
                    }
                    ActionButton {
                        id: loginButton
                        objectName: "login-official-device"; Layout.fillWidth: true; implicitHeight: 38
                        text: !nodesPage.loggingIn ? "打开浏览器，登录并连接"
                            : vm.deviceLoginStage === "preparing" ? "正在准备登录…"
                            : vm.deviceLoginStage === "verifying" ? "正在验证连接…" : "等待浏览器授权…"
                        primary: true; enabled: !nodesPage.loggingIn && !vm.busy && nodeAddress.text.trim().length > 0
                        onClicked: lobby.act("loginOfficialDevice", {remember: rememberDevice.checked, origin: nodeAddress.text})
                    }
                    Rectangle { Layout.fillWidth: true; height: 1; color: "#453650" }
                    ColumnLayout {
                        Layout.fillWidth: true; spacing: 7
                        CopyText { text: "2  浏览器授权 → 3  自动连接"; font.pixelSize: 12; font.bold: true; color: "#ddd0ef" }
                        CopyText {
                            objectName: "node-login-status"; Layout.fillWidth: true
                            text: vm.error || vm.deviceLoginMessage || vm.notice || "默认浏览器会自动打开节点网站。登录账号并确认设备后，启动器会自动保存节点。"
                            font.pixelSize: 12
                            color: vm.error || vm.deviceLoginStage === "error" ? "#ffc2bd" : vm.deviceLoginStage === "complete" ? "#a9e1c2" : "#c7bad8"
                        }
                        RowLayout {
                            Layout.fillWidth: true; spacing: 8
                            visible: nodesPage.loggingIn
                            ActionButton {
                                objectName: "reopen-device-browser"; text: "重新打开浏览器"; Layout.fillWidth: true; implicitHeight: 30; quiet: true
                                visible: !!vm.deviceLoginUrl; enabled: vm.deviceLoginStage === "waiting"
                                onClicked: lobby.act("openDeviceBrowser", {})
                            }
                            ActionButton {
                                objectName: "copy-device-login-url"; text: "复制登录链接"; Layout.fillWidth: true; implicitHeight: 30; quiet: true
                                visible: !!vm.deviceLoginUrl; enabled: vm.deviceLoginStage === "waiting"
                                onClicked: lobby.act("copyDeviceLoginUrl", {})
                            }
                            ActionButton {
                                objectName: "cancel-device-login"; text: "取消"; implicitHeight: 30; quiet: true
                                onClicked: lobby.act("cancelDeviceLogin", {})
                            }
                        }
                    }
                }
            }
        }
    }
    RowLayout {
        Layout.fillWidth: true; spacing: 10
        CopyText { Layout.fillWidth: true; text: "其他节点也可直接填写地址，账号由对应节点管理。"; font.pixelSize: 11; color: "#b0a0c3" }
        ActionButton { objectName: "nodes-done"; text: "返回大厅"; implicitHeight: 30; primary: true; onClicked: lobby.act("navigate", {page:"hall"}) }
    }
}
