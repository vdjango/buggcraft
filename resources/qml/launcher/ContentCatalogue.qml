import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Item {
    id: root
    objectName: "content-catalogue"
    property var state: contentController.viewState
    ColumnLayout {
        anchors.fill: parent; spacing: 3
        visible: root.state.view === "browse"
        CatalogueList {
            listObjectName: "content-project-list"
            Layout.fillWidth: true; Layout.fillHeight: true
            rows: root.state.results; query: root.state.query
            statusText: root.state.status; busy: root.state.busy; hasMore: root.state.has_more
            filterLabel: "来源："; filterOptions: ["自动", "Modrinth", "CurseForge"]
            filterIndex: filterOptions.indexOf(root.state.source); filterObjectName: "content-source"
            descriptionForRow: function(row) { return (row.source || "Modrinth") + " | " + (row.display_summary || "暂无简介") }
            emptyText: "暂无结果，可以更换关键词或内容来源。"
            onQueryEdited: query => contentController.setQuery(query)
            onSearchRequested: query => contentController.search(query)
            onFilterSelected: value => contentController.setSource(value)
            onRetryRequested: contentController.search(root.state.query)
            onMoreRequested: contentController.loadMore()
            onRowClicked: (index, record) => contentController.chooseProject(index)
        }
        Label {
            objectName: "content-target"
            Layout.fillWidth: true; Layout.leftMargin: 15; Layout.rightMargin: 15; Layout.bottomMargin: 5
            text: root.state.kind === "modpack" ? "整合包安装目录：" + root.state.target : "安装到「" + root.state.instance + "」：" + root.state.target
            color: "#aaa4b6"; font.pixelSize: 12; elide: Text.ElideMiddle
            HoverHandler { id: targetHover }
            ToolTip.visible: targetHover.hovered; ToolTip.text: text
        }
    }
    Loader { id: details; anchors.fill: parent; active: root.state.view === "detail"; source: "ContentDetails.qml" }
    ColumnLayout {
        objectName: "content-detail-loading"
        anchors.centerIn: parent; visible: details.active && details.status === Loader.Loading
        BusyIndicator { Layout.alignment: Qt.AlignHCenter; running: parent.visible }
        Label { text: "正在加载详情…"; color: "#c7bfd5"; font.pixelSize: 13 }
    }
}
