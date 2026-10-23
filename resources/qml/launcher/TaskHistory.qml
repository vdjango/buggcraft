import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Item {
    id: root
    property bool logOpen: false
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
        width: Math.min(root.width - 40, 640)
        height: Math.min(root.height - 50, 400)
        modal: true
        title: taskHistory.logTitle
        onOpened: root.logOpen = true
        onClosed: {
            root.logOpen = false
            taskHistory.closeLog()
        }
        background: Rectangle { color: "#211e2d"; border.color: "#625277"; radius: 7 }
        contentItem: ScrollView {
            clip: true
            TextArea {
                readOnly: true
                selectByMouse: true
                text: taskHistory.logLines.join("\n")
                color: "#e8e1ef"
                font.family: "Consolas"
                font.pixelSize: 11
                wrapMode: TextEdit.Wrap
                background: Rectangle { color: "#2c273b"; radius: 5 }
            }
        }
        footer: DialogButtonBox {
            alignment: Qt.AlignRight
            Button { text: "关闭"; DialogButtonBox.buttonRole: DialogButtonBox.AcceptRole }
        }
    }

    onLogOpenChanged: if (logOpen && !logDialog.opened) logDialog.open()
}
