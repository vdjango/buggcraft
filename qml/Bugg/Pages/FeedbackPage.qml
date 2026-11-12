import QtQuick
import QtQuick.Layouts
import Bugg.DesignSystem

PageLayout {
    id: root
    property var service: null
    readonly property var result: service ? service.feedback : ({})
    signal noticeRequested(string message)
    TextAreaField {
        id: message
        Layout.fillWidth: true
        placeholderText: qsTr("发生了什么？你原本希望怎样？")
    }
    FormField {
        id: contact
        Layout.fillWidth: true
        label: qsTr("联系方式（选填）")
        placeholderText: qsTr("方便我们进一步了解问题")
    }
    CheckOption {
        id: diagnostics
        text: qsTr("附加版本、系统和 CPU 架构")
        checked: true
    }
    ActionButton {
        Layout.fillWidth: true
        text: root.result.busy ? qsTr("正在提交…") : qsTr("提交问题")
        enabled: !!root.service && !root.result.busy && message.text.trim().length > 0
        compact: true
        onClicked: root.service.submit_feedback(message.text, contact.text, diagnostics.checked)
    }
    NoticeBanner {
        Layout.fillWidth: true
        visible: !!root.result.error || !!root.result.id
        text: root.result.error || qsTr("已收到反馈，编号：%1").arg(root.result.id || "")
    }
}
