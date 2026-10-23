import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// One catalogue layout for Minecraft and all downloadable content.
Item {
    id: root
    property var rows: []
    property string query: ""
    property string statusText: ""
    property bool busy: false
    property bool hasMore: false
    property Component rowDelegate: null
    property string listObjectName: "catalogue-list"
    property string filterLabel: "版本："
    property var filterOptions: []
    property int filterIndex: 0
    property string filterObjectName: "catalogue-filter"
    property string emptyText: "没有符合筛选条件的内容。"
    property var titleForRow: function(row) { return row.display_title || row.title || "未命名项目" }
    property var descriptionForRow: function(row) { return row.display_summary || "" }
    property var nameForRow: function(row, index) { return "content-project-" + index }
    property var iconForRow: function(row) { return row.icon_url || "../../images/user/offline_login.png" }
    signal queryEdited(string query)
    signal searchRequested(string query)
    signal filterSelected(string value)
    signal retryRequested()
    signal moreRequested()
    signal rowClicked(int index, var record)

    ColumnLayout {
        anchors.fill: parent
        anchors.leftMargin: 15; anchors.rightMargin: 15
        spacing: 2
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 60; color: "#4dbeb7ff"
            RowLayout {
                anchors.fill: parent; anchors.leftMargin: 10; anchors.rightMargin: 10; spacing: 8
                Rectangle {
                    Layout.fillWidth: true; implicitHeight: 35; color: "#4d000000"
                    RowLayout {
                        anchors.fill: parent; spacing: 0
                        Item { implicitWidth: 30; Layout.fillHeight: true; Image { anchors.centerIn: parent; width: 12; height: 12; source: "../../images/search.png" } }
                        InputField {
                            id: queryField
                            objectName: "catalogue-query"
                            Layout.fillWidth: true; implicitHeight: 35
                            text: root.query; placeholderText: "请输入名称或关键词"; background: Item {}
                            onTextEdited: root.queryEdited(text)
                            onAccepted: root.searchRequested(text)
                        }
                        ActionButton {
                            objectName: "catalogue-search"
                            text: "搜索"; implicitWidth: 78; implicitHeight: 35
                            background: Image { source: "../../images/Install/Search.png" }
                            onClicked: root.searchRequested(queryField.text)
                        }
                    }
                }
                Label { text: root.filterLabel; color: "#ccffffff"; font.pixelSize: 13; font.bold: true }
                ChoiceBox {
                    objectName: root.filterObjectName
                    model: root.filterOptions; currentIndex: root.filterIndex
                    Layout.preferredWidth: 150; implicitHeight: 35
                    onActivated: root.filterSelected(currentText)
                }
            }
        }
        RowLayout {
            visible: !!root.statusText || root.busy
            Layout.fillWidth: true
            Label {
                Layout.fillWidth: true; text: root.statusText || "正在获取内容…"
                color: "#bfb4d8"; wrapMode: Text.Wrap
            }
            ActionButton { text: "重试"; visible: !root.busy; onClicked: root.retryRequested() }
        }
        PagedListView {
            id: list
            objectName: root.listObjectName
            Layout.fillWidth: true; Layout.fillHeight: true
            clip: true; spacing: 10; model: root.rows
            hasMore: root.hasMore; loading: root.busy
            loadFailed: root.statusText.startsWith("获取失败")
            onMoreRequested: root.moreRequested()
            delegate: root.rowDelegate || standardRow
        Component {
            id: standardRow
            ListRow {
                required property int index
                required property var modelData
                objectName: root.nameForRow(modelData, index)
                width: list.width; height: 70
                title: root.titleForRow(modelData)
                description: root.descriptionForRow(modelData)
                icon: root.iconForRow(modelData)
                onClicked: root.rowClicked(index, modelData)
            }
        }
            Label {
                anchors.centerIn: parent; width: parent.width - 30
                visible: list.count === 0
                text: root.busy ? "正在获取内容，结果会陆续显示…" : root.emptyText
                color: "#b9afca"; wrapMode: Text.Wrap; horizontalAlignment: Text.AlignHCenter
            }
        }
    }
}
