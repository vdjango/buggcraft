import QtQuick
import QtQuick.Layouts

ColumnLayout {
    id: root
    property string label: ""
    property alias text: input.text
    property alias placeholderText: input.placeholderText
    property alias echoMode: input.echoMode
    property string actionIcon: ""
    signal actionRequested
    signal textEdited(string value)
    spacing: DesignTokens.comfortable ? 12 : 8
    UiText {
        text: root.label
        font.pixelSize: DesignTokens.comfortable ? 13 : 11
        color: DesignTokens.muted
    }
    InputField {
        id: input
        onTextEdited: root.textEdited(text)
        Layout.fillWidth: true
        IconButton {
            visible: root.actionIcon.length > 0
            iconName: root.actionIcon
            accessibleName: qsTr("选择文件")
            onClicked: root.actionRequested()
        }
    }
}
