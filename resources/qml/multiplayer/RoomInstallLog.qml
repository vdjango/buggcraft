import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

ColumnLayout {
    id: log
    property var record: ({})
    property bool remote: false
    readonly property string prefix: remote ? "remote-" : ""
    property var rows: record.prepareLogs || []
    function filtered() {
        var query = search.text.toLowerCase()
        var categories = [[], ["game", "java", "assets", "libraries", "loader"], ["mods"], ["resources"], ["configuration"], ["verify"]]
        var levels = ["", "info", "warning", "error"]
        return rows.filter(function(row) {
            return (!query || row.text.toLowerCase().indexOf(query) >= 0) &&
                (!category.currentIndex || categories[category.currentIndex].indexOf(row.category) >= 0) &&
                (!level.currentIndex || row.level === levels[level.currentIndex])
        })
    }
    spacing: 8
    RowLayout {
        Layout.fillWidth: true; spacing: 7
        InputField { id: search; objectName: log.prefix + "room-log-search"; Layout.fillWidth: true; placeholderText: "搜索安装日志"; implicitHeight: 30 }
        ChoiceBox { id: category; objectName: log.prefix + "room-log-category"; implicitWidth: 100; implicitHeight: 30; model: ["全部", "游戏", "模组", "资源", "配置", "校验"] }
        ChoiceBox { id: level; objectName: log.prefix + "room-log-level"; implicitWidth: 86; implicitHeight: 30; model: ["全部级别", "信息", "警告", "错误"] }
        ActionButton { objectName: log.prefix + "room-log-copy"; text: "复制"; implicitHeight: 30; onClicked: lobby.act("copyPrepareLog", {remote:log.remote}) }
        ActionButton { objectName: log.prefix + "room-log-export"; text: "保存"; implicitHeight: 30; onClicked: lobby.act("exportPrepareLog", {remote:log.remote}) }
    }
    ListView {
        id: entries; objectName: log.prefix + "room-install-log"
        Layout.fillWidth: true; Layout.fillHeight: true; clip: true; spacing: 6
        model: log.filtered()
        ScrollBar.vertical: ScrollBar {}
        onCountChanged: if (follow.checked) Qt.callLater(function() { entries.positionViewAtEnd() })
        onMovementStarted: follow.checked = false
        delegate: CopyText {
            required property var modelData
            width: entries.width - 14; font.pixelSize: 11; font.family: "Consolas"
            text: modelData.time + "  " + modelData.text; textFormat: Text.PlainText; wrapMode: Text.Wrap
            color: modelData.level === "error" ? "#ffadb9" : modelData.level === "warning" ? "#e8c38f" : modelData.category === "verify" ? "#add4bb" : modelData.category === "mods" ? "#c8b3ec" : "#bcb0cd"
        }
        CopyText { anchors.centerIn: parent; visible: entries.count === 0; text: log.rows.length ? "没有匹配的日志" : "同步安装后，进度和日志会显示在这里"; font.pixelSize: 12; color: "#a89ab6" }
    }
    CheckBox { id: follow; objectName: log.prefix + "room-log-follow"; text: "跟随最新日志"; checked: true; implicitHeight: 25; palette.windowText: "#bcb0cd" }
}
