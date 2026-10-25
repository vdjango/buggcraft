import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root
    property var state: instancesPage.view
    Connections {
        target: instancesPage
        function onChanged() {
            root.state = instancesPage.view
        }
    }
    RowLayout {
        anchors.fill: parent
        anchors.margins: 15
        spacing: 10
        Rectangle {
            Layout.preferredWidth: 235
            Layout.minimumWidth: 180
            Layout.fillHeight: true
            color: "#405c5a98"
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 10
                spacing: 10
                Label { objectName: "directory-heading"; text: "游戏目录"; font.pixelSize: 14; font.weight: Font.DemiBold; color: "#f2edf8" }
                ListView {
                    id: directories
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    spacing: 8
                    model: root.state.directories
                    ScrollBar.vertical: ScrollBar {}
                    delegate: Rectangle {
                        required property var modelData
                        width: directories.width - 6
                        height: 60
                        color: root.state.directory === modelData.path ? "#7859ff" : "#33ad9df4"
                        border.color: "#7859ff"
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 10; anchors.rightMargin: 23
                            spacing: 10
                            Image { Layout.preferredWidth: 30; Layout.preferredHeight: 30; source: "../../images/version/" + (root.state.directory === modelData.path ? "selected.png" : "not-selected.png") }
                            ColumnLayout {
                                Layout.fillWidth: true; spacing: 5
                                Text { Layout.fillWidth: true; text: modelData.title; elide: Text.ElideRight; color: "#f2f2f2"; font.pixelSize: 13; font.bold: true }
                                Text { Layout.fillWidth: true; text: modelData.path; elide: Text.ElideMiddle; color: "#f2f2f2"; font.pixelSize: 12 }
                            }
                        }
                        MouseArea { anchors.fill: parent; onClicked: instancesPage.selectDirectory(modelData.path) }
                        IconButton { anchors.right: parent.right; anchors.top: parent.top; width: 24; height: 24; text: "移除目录"; source: "../../images/version/close.png"; onClicked: instancesPage.action(modelData.path, "deleteDirectory") }
                    }
                }
                ActionButton { Layout.fillWidth: true; text: "添加游戏文件夹"; onClicked: instancesPage.addDirectory() }
                ActionButton { Layout.fillWidth: true; text: "安装新游戏"; primary: true; onClicked: instancesPage.action("", "download") }
            }
        }
        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 10
            RowLayout {
                Layout.fillWidth: true
                Label { objectName: "instance-heading"; Layout.fillWidth: true; text: "游戏实例"; font.pixelSize: 14; font.weight: Font.DemiBold; color: "#f2edf8" }
            }
            ListView {
                id: versions
                Layout.fillWidth: true
                Layout.fillHeight: true
                model: root.state.versions
                clip: true
                spacing: 10
                ScrollBar.vertical: ScrollBar {}
                delegate: ListRow {
                    id: instanceRow
                    required property var modelData
                    width: versions.width; height: 68
                    color: "#40beb7ff"
                    title: "版本号：" + modelData.version
                    description: modelData.description
                    icon: "../../images/version/" + (root.state.selected === modelData.version ? "selected.png" : "not-selected.png")
                    onClicked: instancesPage.selectVersion(modelData.version)
                    actions: Component {
                        RowLayout {
                            spacing: 8
                            IconButton { text: "设置"; source: "../../images/version/setting.png"; onClicked: instancesPage.action(instanceRow.modelData.version, "settings") }
                            Rectangle { implicitWidth: 2; implicitHeight: 40; color: "#4dffffff" }
                            IconButton { text: "目录"; source: "../../images/version/folder.png"; onClicked: instancesPage.action(instanceRow.modelData.version, "folder") }
                            IconButton { text: "删除"; source: "../../images/version/delete.png"; onClicked: instancesPage.action(instanceRow.modelData.version, "deleteVersion") }
                        }
                    }
                }
                Label {
                    anchors.centerIn: parent; width: parent.width - 20
                    visible: versions.count === 0; text: "当前目录没有游戏实例，请前往下载页安装。"
                    color: "#bcb2cc"; wrapMode: Text.Wrap; horizontalAlignment: Text.AlignHCenter
                }
            }
        }
    }
}
