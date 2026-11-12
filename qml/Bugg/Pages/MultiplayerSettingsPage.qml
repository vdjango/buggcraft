import QtQuick
import QtQuick.Layouts
import Bugg.DesignSystem

// Non-sensitive origin preference uses GameRuntime; authorization stays in MultiplayerService.
PageLayout {
    id: root
    property string loginOrigin: ""
    property bool customService: false
    signal originEdited(string value)
    signal customServiceEdited(bool enabled)
    spacing: 16
    CheckOption {
        objectName: "customMultiplayerServiceOption"
        text: qsTr("使用自定义统一服务")
        checked: root.customService
        onToggled: root.customServiceEdited(checked)
    }
    FormField {
        objectName: "multiplayerServiceOriginField"
        Layout.fillWidth: true
        visible: root.customService
        label: qsTr("服务地址")
        placeholderText: "https://…"
        text: root.loginOrigin
        onTextEdited: value => root.originEdited(value)
    }
    UiText {
        Layout.fillWidth: true
        text: root.customService ? qsTr("填写统一服务的 HTTPS 地址，下次登录时使用。") : qsTr("使用 Bugg 默认联机服务。")
        font.pixelSize: 12
        color: DesignTokens.muted
        wrapMode: Text.Wrap
    }
}
