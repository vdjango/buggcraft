pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import Bugg.DesignSystem

PageLayout {
    id: root
    // 唯一来源设置快照，命令交由 C++ SourceSettings；页面无能力路由规则。
    property var sourceSettings: ({})
    signal moveRequested(int index, int delta)
    signal baseUrlRequested(string value)
    UiText {
        text: qsTr("下载源优先级")
        color: DesignTokens.muted
    }
    UiText {
        Layout.fillWidth: true
        text: qsTr("从上到下依次尝试。源不提供的接口走官方，相同来源只尝试一次。")
        color: DesignTokens.muted
        font.pixelSize: DesignTokens.comfortable ? 12 : 11
        wrapMode: Text.WordWrap
    }
    Repeater {
        model: root.sourceSettings.options || []
        RowLayout {
            id: sourceRow
            required property var modelData
            required property int index
            objectName: "sourcePriority_" + modelData.id
            Layout.fillWidth: true
            enabled: !root.sourceSettings.loading
            UiText {
                text: (sourceRow.index + 1).toString()
                color: DesignTokens.quiet
                Layout.preferredWidth: 20
            }
            UiText {
                text: qsTr(sourceRow.modelData.name)
                Layout.fillWidth: true
            }
            ActionButton {
                objectName: "sourceUp_" + sourceRow.modelData.id
                text: qsTr("上移")
                variant: "ghost"
                compact: true
                enabled: sourceRow.index > 0
                onClicked: root.moveRequested(sourceRow.index, -1)
            }
            ActionButton {
                objectName: "sourceDown_" + sourceRow.modelData.id
                text: qsTr("下移")
                variant: "ghost"
                compact: true
                enabled: sourceRow.index < (root.sourceSettings.options || []).length - 1
                onClicked: root.moveRequested(sourceRow.index, 1)
            }
        }
    }
    UiText {
        text: qsTr("Bugg 源地址")
        color: DesignTokens.muted
    }
    InputField {
        objectName: "buggSourceBaseUrl"
        Layout.fillWidth: true
        text: root.sourceSettings.buggBaseUrl || ""
        enabled: !root.sourceSettings.loading
        onEditingFinished: root.baseUrlRequested(text)
    }
    UiText {
        Layout.fillWidth: true
        text: qsTr("游戏目录、广场和资源下载共用此地址。")
        color: DesignTokens.muted
        font.pixelSize: DesignTokens.controlTextSize
        wrapMode: Text.WordWrap
    }
    NoticeBanner {
        Layout.fillWidth: true
        text: root.sourceSettings.error || ""
    }
}
