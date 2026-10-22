import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Item {
    id: connections
    property var vm: lobby.view
    property var labels: ({connecting:"连接中", online:"已连接", reconnecting:"正在重连", stopping:"正在离开", stopped:"已离开", error:"连接失败"})
    ListView {
        id: list; objectName: "connections-list"
        anchors.fill: parent; clip: true; spacing: 5
        model: vm.connections
        ScrollBar.vertical: ScrollBar {}
        delegate: Surface {
            required property var modelData
            width: list.width; height: 64
            RowLayout {
                anchors.fill: parent; anchors.margins: 9; spacing: 8
                ColumnLayout {
                    Layout.fillWidth: true; spacing: 3
                    CopyText { Layout.fillWidth: true; text: modelData.title; font.pixelSize: 13; font.bold: true; color: "#f0eaff"; wrapMode: Text.NoWrap; elide: Text.ElideRight }
                    CopyText { Layout.fillWidth: true; text: (modelData.role === "host" ? "我创建" : "我加入") + "   ·   " + (connections.labels[modelData.state] || modelData.state); color: modelData.state === "online" ? "#a7d4bf" : "#a8a0b8"; font.pixelSize: 11 }
                }
                ActionButton { objectName: "view-connection-" + modelData.id; text: modelData.state === "online" ? "继续一起玩 →" : "查看详情"; onClicked: lobby.act("selectConnection", {id:modelData.id}) }
            }
        }
    }
    ColumnLayout {
        anchors.centerIn: parent; width: Math.min(340, parent.width - 24); spacing: 8
        visible: vm.connections.length === 0
        CopyText { Layout.fillWidth: true; text: "还没有加入房间"; color: "#e3dbf0"; font.pixelSize: 15; horizontalAlignment: Text.AlignHCenter }
        CopyText { Layout.fillWidth: true; text: "从大厅加入朋友的世界，或创建自己的房间。"; horizontalAlignment: Text.AlignHCenter }
        ActionButton { Layout.alignment: Qt.AlignHCenter; text: "去联机大厅"; primary: true; implicitHeight:30; onClicked: lobby.act("navigate", {page:"hall"}) }
    }
}
