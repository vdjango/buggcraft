import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Item {
    id: root
    property bool logOpen: false
    property bool textLog: false
    property var filters: ["全部记录", "进行中", "已完成", "失败", "已取消", "已中断"]
    ColumnLayout {
        anchors.fill: parent; anchors.topMargin: 10; spacing: 8
        RowLayout {
            Layout.fillWidth: true; Layout.leftMargin: 15; Layout.rightMargin: 15
            Label { text: "下载记录"; color: "#f2f2f2"; font.pixelSize: 14; font.bold: true }
            Item { Layout.fillWidth: true }
            ActionButton { text: "清除已结束记录"; enabled: taskHistory.canClear; onClicked: taskHistory.clearCompleted() }
        }
        CatalogueList {
            listObjectName: "download-history-list"
            Layout.fillWidth: true; Layout.fillHeight: true
            rows: taskHistory.tasks; query: taskHistory.query
            filterLabel: "状态："; filterOptions: root.filters
            filterIndex: Math.max(0, root.filters.indexOf(taskHistory.filterValue))
            emptyText: "暂无下载记录"
            onQueryEdited: query => taskHistory.setQuery(query)
            onSearchRequested: query => taskHistory.setQuery(query)
            onFilterSelected: value => taskHistory.setFilter(value)
            rowDelegate: Component {
                TaskRecord { onViewLog: taskId => { taskHistory.showLog(taskId); root.logOpen = true } }
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
        onOpened: { root.logOpen = true; root.textLog = false }
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
                Label { text: taskHistory.currentFiles.length + " 个文件"; color: "#b6a8c6"; font.pixelSize: 11 }
            }
            ListView {
                id: fileList; objectName: "task-log-files"
                Layout.fillWidth: true; Layout.fillHeight: true
                visible: !root.textLog; clip: true; spacing: 7
                model: taskHistory.currentFiles.length
                delegate: DownloadFileRow {
                    required property int index
                    width: fileList.width - 12
                    file: taskHistory.currentFiles[index] || ({})
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
            ActionButton { anchors.right: parent.right; anchors.rightMargin: 12; text: "关闭"; onClicked: logDialog.close() }
        }
    }

    onLogOpenChanged: if (logOpen && !logDialog.opened) logDialog.open()
}
