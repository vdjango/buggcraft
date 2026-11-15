pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Bugg.DesignSystem

ModalSurface {
    id: root
    objectName: "diagnosticFeedbackDialog"
    property var runtime: null
    property var service: null
    property bool submitted: false
    property string previousId: ""
    readonly property var result: service ? service.feedback : ({})
    readonly property var collection: runtime ? runtime.diagnostics_status : ({})
    readonly property bool busy: !!result.busy || !!collection.busy
    width: Math.min(540, parent.width - 24)
    height: Math.min(610, maximumDialogHeight)
    contentItem: ScrollView {
        id: scroll
        clip: true
        contentWidth: availableWidth
        ColumnLayout {
            width: scroll.availableWidth
            spacing: 10
            UiText {
                Layout.fillWidth: true
                text: qsTr("提交问题与诊断")
                font.pixelSize: 17
                font.bold: true
            }
            UiText {
                Layout.fillWidth: true
                text: qsTr("请说明遇到的问题，以及你期望的结果。")
                wrapMode: Text.Wrap
            }
            TextAreaField {
                id: problem
                objectName: "feedbackProblem"
                Layout.fillWidth: true
                Layout.preferredHeight: 78
                placeholderText: qsTr("遇到了什么问题？如何出现的？")
                surfaceColor: DesignTokens.background
                readOnly: root.busy
            }
            TextAreaField {
                id: expected
                objectName: "feedbackExpected"
                Layout.fillWidth: true
                Layout.preferredHeight: 62
                placeholderText: qsTr("你期望怎样？")
                surfaceColor: DesignTokens.background
                readOnly: root.busy
            }
            FormField {
                id: contact
                Layout.fillWidth: true
                label: qsTr("联系方式（选填）")
                placeholderText: qsTr("方便进一步了解问题")
                enabled: !root.busy
            }
            UiText {
                Layout.fillWidth: true
                text: qsTr("诊断包含近期启动器、游戏、安装与网络日志，当前及所选游戏的版本、加载器、模组文件清单、崩溃报告和网络接口。会清除常见凭据；不上传存档、模组文件或账号存储。仅向官方 Bugg 服务提交，诊断保留最长 90 天。公开分享前请自行检查导出文件。")
                font.pixelSize: 11
                color: DesignTokens.muted
                wrapMode: Text.Wrap
                elide: Text.ElideNone
            }
            CheckOption {
                id: consent
                objectName: "feedbackConsent"
                text: qsTr("我同意本次提交上述诊断信息")
                checked: false
                enabled: !root.busy
            }
            NoticeBanner {
                Layout.fillWidth: true
                visible: !root.service || !root.service.status.feedbackAvailable
                text: qsTr("在线提交需要登录官方 Bugg 账号。也可返回导出日志，手动提交。")
            }
            NoticeBanner {
                Layout.fillWidth: true
                visible: root.submitted && !root.busy && (!!root.result.error || !!root.collection.error || (!!root.result.id && root.result.id !== root.previousId))
                text: root.result.error || root.collection.error || qsTr("反馈已收到，编号：%1").arg(root.result.id || "")
            }
            ActionButton {
                objectName: "submitDiagnosticFeedback"
                Layout.fillWidth: true
                Layout.maximumWidth: Number.POSITIVE_INFINITY
                text: root.busy ? qsTr("正在整理并提交…") : qsTr("提交问题与日志")
                enabled: !!root.runtime && !!root.service && !!root.service.status.feedbackAvailable && !root.busy && consent.checked && problem.text.trim().length > 0 && expected.text.trim().length > 0
                onClicked: {
                    root.previousId = root.result.id || "";
                    root.submitted = true;
                    root.runtime.prepare_feedback(problem.text, expected.text, contact.text);
                }
            }
            ActionButton {
                text: qsTr("通过项目 Issue 手动提交")
                variant: "ghost"
                compact: true
                enabled: !root.busy
                onClicked: Qt.openUrlExternally("https://github.com/vdjango/buggcraft/issues")
            }
            ActionButton {
                Layout.fillWidth: true
                Layout.maximumWidth: Number.POSITIVE_INFINITY
                text: qsTr("返回日志")
                variant: "ghost"
                enabled: !root.busy
                onClicked: root.close()
            }
        }
    }
}
