import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root
    property var state: gameCatalogue.view
    Connections { target: gameCatalogue; function onChanged() { root.state = gameCatalogue.view } }
    CatalogueList {
        visible: root.state.installView === "catalogue"
        anchors.fill: parent
        rows: root.state.versions
        statusText: root.state.status; busy: root.state.busy
        filterOptions: ["正式版", "快照", "旧版", "全部"]
        filterIndex: filterOptions.indexOf(root.state.filter)
        query: root.state.query || ""
        titleForRow: function(row) { return "版本号：" + row.id }
        descriptionForRow: function(row) { return (({release:"正式版",snapshot:"快照",old_alpha:"旧版 Alpha",old_beta:"旧版 Beta"})[row.type] || row.type) + " | 发布时间：" + (row.releaseTime || "").substring(0, 10) }
        nameForRow: function(row, index) { return "install-" + row.id }
        iconForRow: function(row) { return "../../images/user/offline_login.png" }
        emptyText: "没有符合筛选条件的版本。"
        onQueryEdited: function(query) { gameCatalogue.setQuery(query) }
        onSearchRequested: function(query) { gameCatalogue.setQuery(query) }
        onFilterSelected: function(value) { gameCatalogue.setFilter(value) }
        onRetryRequested: gameCatalogue.refresh()
        onRowClicked: function(index, record) { gameCatalogue.selectGame(record.id) }
    }
    Loader { anchors.fill: parent; active: root.state.installView !== "catalogue"; source: "GameInstallation.qml" }
}
