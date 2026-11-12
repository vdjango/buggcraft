import QtQuick
import QtQuick.Layouts
import Bugg.DesignSystem

PageLayout {
    id: root
    property real viewportHeight: 500
    property string playerName: ""
    property bool locked: false
    readonly property bool validName: /^[A-Za-z0-9_]{3,16}$/.test(playerNameField.text)
    signal saveRequested(string name)
    signal nameEdited(string value)
    maximumWidth: 400
    minimumHeight: DesignTokens.comfortable ? viewportHeight : 0
    centered: DesignTokens.comfortable
    FormField {
        id: playerNameField
        objectName: "offlineNameField"
        Layout.fillWidth: true
        label: qsTr("玩家名称")
        placeholderText: qsTr("例如 BuggPlayer")
        text: root.playerName
        enabled: !root.locked
        onTextEdited: value => root.nameEdited(value)
    }
    UiText {
        Layout.fillWidth: true
        text: qsTr("3–16 位字母、数字或下划线")
        color: playerNameField.text.length && !root.validName ? DesignTokens.danger : DesignTokens.muted
        font.pixelSize: 12
    }
    ActionButton {
        objectName: "saveOfflineIdentityButton"
        Layout.fillWidth: true
        Layout.maximumWidth: Number.POSITIVE_INFINITY
        text: qsTr("使用这个名字")
        compact: true
        enabled: root.validName && !root.locked
        onClicked: root.saveRequested(playerNameField.text)
    }
}
