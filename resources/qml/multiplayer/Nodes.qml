import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

ColumnLayout {
    id: nodesPage
    property var vm: lobby.view
    property bool loggingIn: !!vm.deviceLoginBusy
    spacing: 12
    CopyText {
        Layout.fillWidth: true
        text: "登录节点，和朋友一起玩。浏览器授权完成后，这里会自动关闭。"
        font.pixelSize: 12; color: "#c7bad8"
    }
    ScrollView {
        id: formScroll; objectName: "node-login-scroll"
        Layout.fillWidth: true; Layout.fillHeight: true
        contentWidth: availableWidth; clip: true
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ColumnLayout {
            width: formScroll.availableWidth; spacing: 12
            ColumnLayout {
                Layout.fillWidth: true; spacing: 7
                CopyText { text: "节点地址"; font.pixelSize: 12; color: "#e5dcf3"; font.bold: true }
                InputField {
                    id: nodeAddress
                    objectName: "node-web-address"; Layout.fillWidth: true; Layout.preferredHeight: 40
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
                CopyText { text: nodesPage.loggingIn ? "正在连接你的节点" : "浏览器授权后自动连接"; font.pixelSize: 12; font.bold: true; color: "#ddd0ef" }
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
