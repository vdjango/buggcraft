import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Item {
    id: root
    property bool logOpen: false
    property bool textLog: false
    property var filters: ["全部记录", "进行中", "已完成", "失败", "已取消", "已中断"]
    function showTaskLog(taskId) {
        // Keep the modal's lifecycle in the persistent page's context.
        taskHistory.showLog(taskId)
        root.logOpen = true
    }
    ColumnLayout {
        anchors.fill: parent; anchors.topMargin: 10; spacing: 8
        RowLayout {
            Layout.fillWidth: true; Layout.leftMargin: 15; Layout.rightMargin: 15
            Label { text: "下载记录"; color: "#f2f2f2"; font.pixelSize: 14; font.bold: true }
            Item { Layout.fillWidth: true }
            ActionButton { objectName: "task-clear-ended"; text: "清除已结束记录"; enabled: taskHistory.canClear; onClicked: taskHistory.clearCompleted() }
        }
        CatalogueList {
            listObjectName: "download-history-list"
            Layout.fillWidth: true; Layout.fillHeight: true
            rows: taskHistory.taskModel; query: taskHistory.query
            filterLabel: "状态："; filterOptions: root.filters
            filterIndex: Math.max(0, root.filters.indexOf(taskHistory.filterValue))
            emptyText: "暂无下载记录"
            onQueryEdited: query => taskHistory.setQuery(query)
            onSearchRequested: query => taskHistory.setQuery(query)
            onFilterSelected: value => taskHistory.setFilter(value)
            rowDelegate: Component {
                TaskRecord { onViewLog: taskId => root.showTaskLog(taskId) }
            }
        }
    }

    ModalDialog {
        id: logDialog
        parent: Overlay.overlay
        anchors.centerIn: parent
        objectName: "task-log-dialog"
        width: Math.min(root.width - 24, 740)
        height: Math.min(root.height - 20, 530)
        modal: true
        title: taskHistory.logTitle
        onOpened: {
            root.logOpen = true
            root.textLog = false
            // Embedded QQuickWidget hosts can keep the previous page's focus
            // on macOS. Explicitly focus the modal after its enter transition
            // so Escape and keyboard navigation work consistently.
            logDialog.forceActiveFocus()
        }
        onClosed: {
            root.logOpen = false
            taskHistory.closeLog()
        }
        background: Rectangle { color: "#211e2d"; border.color: "#625277"; radius: 7 }
        contentItem: ColumnLayout {
            spacing: 10
            RowLayout {
                Layout.fillWidth: true
                ActionButton { objectName: "log-files-tab"; text: "文件进度"; primary: !root.textLog; onClicked: root.textLog = false }
                ActionButton { objectName: "log-text-tab"; text: "文字日志"; primary: root.textLog; onClicked: root.textLog = true }
                Item { Layout.fillWidth: true }
                Label { text: taskHistory.fileCount + " 个文件"; color: "#b6a8c6"; font.pixelSize: 11 }
            }
            ListView {
                id: fileList; objectName: "task-log-files"
                Layout.fillWidth: true; Layout.fillHeight: true
                visible: !root.textLog; clip: true; spacing: 7
                model: taskHistory.fileModel
                delegate: DownloadFileRow {
                    required property var modelData
                    width: fileList.width - 12
                    file: modelData
                }
                ScrollBar.vertical: ScrollBar {}
                Label {
                    anchors.centerIn: parent; width: parent.width - 20
                    visible: fileList.count === 0
                    text: "尚无文件下载记录\n开始下载后会在这里显示每个文件的进度。"
                    horizontalAlignment: Text.AlignHCenter; wrapMode: Text.Wrap
                    color: "#a89abb"; font.pixelSize: 12
                }
            }
            ScrollView {
                Layout.fillWidth: true; Layout.fillHeight: true
                visible: root.textLog; clip: true
                contentWidth: availableWidth
                TextArea {
                    objectName: "task-log-text"
                    readOnly: true; selectByMouse: true
                    text: taskHistory.logLines.join("\n")
                    color: "#e8e1ef"; font.family: "Consolas"; font.pixelSize: 11
                    wrapMode: TextEdit.Wrap
                    background: Rectangle { color: "#2c273b"; radius: 5 }
                }
            }
        }
        footer: Item {
            implicitHeight: 46
            ActionButton { objectName: "task-log-close"; anchors.right: parent.right; anchors.rightMargin: 12; text: "关闭"; onClicked: logDialog.close() }
        }
    }

    onLogOpenChanged: if (logOpen && !logDialog.opened) logDialog.open()
}
