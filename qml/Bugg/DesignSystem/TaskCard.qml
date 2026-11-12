import QtQuick
import QtQuick.Layouts

// 任务呈现共用组件；任务状态与重试规则由 GameRuntime 所有。
Surface {
    id: root
    required property var task
    property bool detailsExpanded: true
    property real viewportLimit: 0
    readonly property int failedItems: (task.contentItems || []).filter(item => item.state === "failed").length
    readonly property bool cancellable: ["queued", "running"].includes(task.state)
    readonly property bool missingDependencies: task.state === "done" && (task.missingDependencies || []).length > 0
    readonly property bool retryable: task.kind !== "launch" && (["failed", "cancelled", "interrupted"].includes(task.state) || missingDependencies)
    readonly property string operation: ({
            "install": qsTr("安装游戏"),
            "room": qsTr("同步游戏"),
            "import": qsTr("导入整合包"),
            "export": qsTr("导出整合包"),
            "remove": qsTr("删除"),
            "launch": qsTr("启动游戏")
        })[task.kind] || ""
    signal cancelRequested(string id)
    signal retryRequested(string id)
    signal dependencyChoiceRequested(string id, string choice)
    implicitHeight: body.implicitHeight + 32
    color: DesignTokens.canvas
    ColumnLayout {
        id: body
        anchors.fill: parent
        spacing: 12
        RowLayout {
            id: taskHeader
            Layout.fillWidth: true
            ProgressItem {
                Layout.fillWidth: true
                title: (root.operation.length ? root.operation + " · " : "") + (root.task.name || "")
                state: ({
                        queued: qsTr("排队中"),
                        cancelling: qsTr("正在取消"),
                        cancelled: qsTr("已取消"),
                        failed: qsTr("失败"),
                        done: root.missingDependencies ? qsTr("待补齐依赖") : qsTr("完成"),
                        interrupted: qsTr("上次未完成，可重试"),
                        needs_dependency_decision: qsTr("等待依赖处理选择")
                    })[root.task.state] || ""
                progress: root.task.progress === undefined ? -1 : root.task.progress
                caption: [root.task.detail || "", root.task.state === "running" && root.task.downloadSpeed && root.task.activeTransfers > 0 ? qsTr("%1 · %2 个连接").arg(root.task.downloadSpeed).arg(root.task.activeTransfers) : ""].filter(Boolean).join("\n")
                showBar: ["running", "cancelling"].includes(root.task.state)
                titleSize: 14
            }
            ActionButton {
                visible: root.cancellable || root.retryable
                text: root.cancellable ? qsTr("取消") : root.missingDependencies ? qsTr("重试依赖") : qsTr("重试")
                compact: true
                variant: "ghost"
                onClicked: root.cancellable ? root.cancelRequested(root.task.id) : root.retryRequested(root.task.id)
            }
        }
        ColumnLayout {
            Layout.fillWidth: true
            visible: root.task.state === "needs_dependency_decision"
            spacing: 8
            NoticeBanner {
                Layout.fillWidth: true
                text: (root.task.dependencyDecision || {}).summary || ""
            }
            UiText {
                Layout.fillWidth: true
                text: (root.task.dependencyDecision || {}).repairError || qsTr("整合包可能包含作者验证过的特殊组合。保留原版本不会替换文件；自动处理会在暂存区重新选择并核验依赖，也可能使用测试版。")
                color: DesignTokens.muted
                font.pixelSize: 12
            }
            ActionButton {
                Layout.fillWidth: true
                text: qsTr("保留原版本继续")
                onClicked: root.dependencyChoiceRequested(root.task.id, "keep")
            }
            ActionButton {
                Layout.fillWidth: true
                visible: !!(root.task.dependencyDecision || {}).canRepair
                variant: "secondary"
                text: qsTr("自动处理依赖（允许测试版）")
                onClicked: root.dependencyChoiceRequested(root.task.id, "repair")
            }
            ActionButton {
                Layout.fillWidth: true
                variant: "ghost"
                text: qsTr("取消安装")
                onClicked: root.dependencyChoiceRequested(root.task.id, "cancel")
            }
        }
        NoticeBanner {
            id: dependencyNotice
            Layout.fillWidth: true
            visible: root.missingDependencies
            text: (root.task.contentItems || []).length ? qsTr("必要依赖未补齐，游戏可能无法正常运行。请查看明细并重试。") : qsTr("请补装以下必要依赖：") + "\n" + (root.task.missingDependencies || []).map(item => (item.title || item.projectId || item.versionId) + " · " + item.reason).join("\n")
            color: DesignTokens.warning
        }
        SummaryButton {
            id: disclosure
            objectName: "contentTaskDisclosure"
            Layout.fillWidth: true
            visible: (root.task.contentItems || []).length > 0
            text: qsTr("安装明细 · %1 项").arg((root.task.contentItems || []).length) + (root.failedItems ? qsTr(" · %1 项失败").arg(root.failedItems) : "")
            titleSize: 12
            implicitHeight: 28
            expanded: root.detailsExpanded
            onClicked: root.detailsExpanded = !root.detailsExpanded
        }
        ListViewport {
            objectName: "contentTaskItems"
            Layout.fillWidth: true
            Layout.preferredHeight: Math.max(64, Math.min(contentHeight, DesignTokens.comfortable ? 250 : 210, root.viewportLimit > 0 ? root.viewportLimit - root.padding * 2 - taskHeader.implicitHeight - disclosure.implicitHeight - body.spacing * 2 - (dependencyNotice.visible ? dependencyNotice.implicitHeight + body.spacing : 0) : 250))
            visible: root.detailsExpanded && count > 0
            spacing: 8
            model: root.task.contentItems || []
            delegate: ProgressItem {
                required property var modelData
                width: ListView.view.width - 8
                title: (modelData.title || modelData.filename || modelData.projectId || modelData.versionId) + (modelData.dependency ? qsTr(" · 依赖") : "")
                state: ({
                        queued: qsTr("等待中"),
                        checking: qsTr("校验中"),
                        downloading: qsTr("下载中"),
                        installing: qsTr("安装中"),
                        installed: qsTr("已安装"),
                        done: qsTr("安装完成"),
                        failed: qsTr("失败"),
                        cancelled: qsTr("已取消"),
                        interrupted: qsTr("未完成")
                    })[modelData.state] || ""
                titleSize: 12
                titleWeight: Font.Medium
                captionSize: 11
                caption: [modelData.versionName && modelData.versionName !== modelData.title && modelData.versionName !== modelData.filename ? modelData.versionName : "", modelData.state === "downloading" ? [modelData.transferText || "", modelData.speedText || ""].filter(Boolean).join(" · ") : "", ["failed", "interrupted"].includes(modelData.state) ? modelData.detail || "" : ""].filter(Boolean).join("\n")
                progress: modelData.progress === undefined ? -1 : modelData.progress
                showBar: modelData.state === "downloading"
            }
        }
    }
}
