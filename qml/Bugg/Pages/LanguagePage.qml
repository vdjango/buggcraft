import QtQuick
import QtQuick.Layouts
import Bugg.DesignSystem

PageLayout {
    id: root
    property var service: null
    property string selection: "zh_cn"
    property bool contentTranslation: true
    readonly property var downloadStatus: service ? service.status : ({})
    signal chosen(string value)
    signal contentTranslationEdited(bool enabled)
    minimumHeight: DesignTokens.comfortable ? 0 : 400
    SelectField {
        objectName: "languageSelector"
        Layout.fillWidth: true
        label: qsTr("语言")
        searchPlaceholder: qsTr("搜索语言")
        options: root.service ? root.service.options : []
        selection: root.downloadStatus.requestedCode || root.selection
        onChosen: value => root.chosen(value)
    }
    UiText {
        Layout.fillWidth: true
        text: qsTr("其他语言首次使用时下载，之后可离线使用。下载失败会保留当前语言。")
        font.pixelSize: 12
        color: DesignTokens.muted
        wrapMode: Text.Wrap
    }
    LoadingIndicator {
        Layout.fillWidth: true
        visible: root.downloadStatus.state === "loading"
        text: qsTr("正在获取语言包…")
    }
    UiText {
        Layout.fillWidth: true
        visible: root.downloadStatus.state === "error"
        text: root.downloadStatus.error || ""
        color: DesignTokens.muted
        wrapMode: Text.Wrap
    }
    ActionButton {
        objectName: "languageDownloadRetry"
        visible: root.downloadStatus.state === "error"
        text: qsTr("重试")
        onClicked: root.service.retry()
    }
    ActionButton {
        objectName: "languageDownloadCancel"
        visible: root.downloadStatus.state === "loading"
        text: qsTr("取消")
        onClicked: root.service.cancel()
    }
    Divider {
        Layout.fillWidth: true
    }
    ColumnLayout {
        Layout.fillWidth: true
        spacing: 6
        CheckOption {
            objectName: "contentTranslationOption"
            text: qsTr("资源中文翻译")
            checked: root.contentTranslation
            onToggled: root.contentTranslationEdited(checked)
        }
        UiText {
            Layout.fillWidth: true
            text: qsTr("自动翻译资源列表简介和图文详情，暂缺译文时显示原文。")
            font.pixelSize: 12
            color: DesignTokens.muted
            wrapMode: Text.Wrap
        }
    }
}
