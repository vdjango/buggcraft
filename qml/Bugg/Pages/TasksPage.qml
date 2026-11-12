pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import Bugg.DesignSystem

PageLayout {
    id: root
    property var tasks: []
    property real viewportHeight: 440
    signal cancelRequested(string id)
    signal retryRequested(string id)
    signal dependencyChoiceRequested(string id, string choice)
    signal clearRequested
    maximumWidth: 860
    verticalPadding: 8
    spacing: 6
    ListViewport {
        Layout.fillWidth: true
        Layout.preferredHeight: Math.max(120, root.viewportHeight - root.verticalPadding * 2 - summary.implicitHeight - root.spacing)
        model: root.tasks
        delegate: TaskCard {
            required property var modelData
            width: ListView.view.width
            viewportLimit: ListView.view.height
            task: modelData
            onCancelRequested: id => root.cancelRequested(id)
            onRetryRequested: id => root.retryRequested(id)
            onDependencyChoiceRequested: (id, choice) => root.dependencyChoiceRequested(id, choice)
        }
        UiText {
            anchors.centerIn: parent
            visible: root.tasks.length === 0
            text: qsTr("暂无任务")
            color: DesignTokens.muted
        }
    }
    RowLayout {
        id: summary
        Layout.fillWidth: true
        UiText {
            Layout.fillWidth: true
            text: qsTr("进行中 %1 · 排队 %2").arg(root.tasks.filter(t => ["running", "cancelling"].includes(t.state)).length).arg(root.tasks.filter(t => t.state === "queued").length)
            color: DesignTokens.muted
            font.pixelSize: 11
        }
        ActionButton {
            objectName: "clearTaskHistoryButton"
            text: qsTr("清空记录")
            compact: true
            variant: "ghost"
            enabled: root.tasks.some(t => ["done", "failed", "cancelled", "interrupted"].includes(t.state))
            onClicked: root.clearRequested()
        }
    }
}
