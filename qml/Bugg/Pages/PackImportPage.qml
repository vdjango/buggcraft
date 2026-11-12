pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import Bugg.DesignSystem
PageLayout {
    id: root
    property var preview: ({})
    signal installRequested(string instanceName)
    maximumWidth: 640
    FormField {
        id: instanceName
        Layout.fillWidth: true
        label: qsTr("游戏名称")
        text: root.preview.name || ""
        enabled: !root.preview.loading && !root.preview.error
    }
    UiText {
        Layout.fillWidth: true
        text: root.preview.loading ? qsTr("正在检查整合包…") : root.preview.error || [root.preview.game, root.preview.loader, root.preview.loaderVersion].filter(Boolean).join(" · ")
        color: root.preview.error ? DesignTokens.danger : DesignTokens.muted
        wrapMode: Text.Wrap
        elide: Text.ElideNone
    }
    ActionButton {
        Layout.alignment: Qt.AlignRight
        text: qsTr("导入整合包")
        enabled: !root.preview.loading && !root.preview.error && !!root.preview.path && instanceName.text.trim().length > 0
        onClicked: root.installRequested(instanceName.text.trim())
    }
}
