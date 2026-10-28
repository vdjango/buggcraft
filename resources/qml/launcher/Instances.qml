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
            color: "#e61d1a25"
            border.color: "#49415c"
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
                    spacing: 2
                    model: root.state.directories
                    ScrollBar.vertical: ScrollBar {}
                    delegate: Rectangle {
                        required property var modelData
                        objectName: "instance-directory-" + modelData.path
                        width: directories.width - 6
                        height: 64
                        color: root.state.directory === modelData.path ? "#292536" : "transparent"
                        border.color: "transparent"
                        Rectangle { visible: root.state.directory === modelData.path; x: 0; y: 8; width: 3; height: parent.height - 16; color: "#a88df1"; radius: 1 }
                        Rectangle { anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom; height: 1; color: "#393445" }
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 12; anchors.rightMargin: 26
                            spacing: 10
                            Image { Layout.preferredWidth: 30; Layout.preferredHeight: 30; source: "../../images/version/" + (root.state.directory === modelData.path ? "selected.png" : "not-selected.png") }
                            ColumnLayout {
                                Layout.fillWidth: true; spacing: 5
                                Text { Layout.fillWidth: true; text: modelData.title; elide: Text.ElideRight; color: "#f2f2f2"; font.pixelSize: 13; font.bold: true }
                                Text { Layout.fillWidth: true; text: modelData.path; elide: Text.ElideMiddle; color: "#aaa2bb"; font.pixelSize: 11 }
                            }
                        }
                        MouseArea { anchors.fill: parent; onClicked: instancesPage.selectDirectory(modelData.path) }
                        IconButton { objectName: "instance-remove-directory-" + modelData.path; anchors.right: parent.right; anchors.top: parent.top; width: 24; height: 24; text: "移除目录"; source: "../../images/version/close.png"; onClicked: instancesPage.action(modelData.path, "deleteDirectory") }
                    }
                }
                ActionButton { objectName: "instance-add-directory"; Layout.fillWidth: true; text: "添加游戏文件夹"; onClicked: instancesPage.addDirectory() }
                ActionButton { objectName: "instance-install-game"; Layout.fillWidth: true; text: "安装新游戏"; primary: true; onClicked: instancesPage.action("", "download") }
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
            Label {
                objectName: "instance-status"
                Layout.fillWidth: true
                visible: !!root.state.status
                text: root.state.status
                color: root.state.status.indexOf("失败") >= 0 || root.state.status.indexOf("无法") >= 0 ? "#ff9b91" : "#b9a8e8"
                elide: Text.ElideMiddle
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
                    objectName: "instance-row-" + modelData.version
                    width: versions.width; height: 68
                    title: "版本号：" + modelData.version
                    description: modelData.description
                    icon: "../../images/version/" + (root.state.selected === modelData.version ? "selected.png" : "not-selected.png")
                    onClicked: instancesPage.selectVersion(modelData.version)
                    actions: Component {
                        RowLayout {
                            spacing: 8
                            ActionButton { objectName: "instance-export-" + instanceRow.modelData.version; text: "导出"; implicitWidth: 52; implicitHeight: 30; onClicked: instancesPage.action(instanceRow.modelData.version, "export") }
                            IconButton { objectName: "instance-settings-" + instanceRow.modelData.version; text: "设置"; source: "../../images/version/setting.png"; onClicked: instancesPage.action(instanceRow.modelData.version, "settings") }
                            IconButton { objectName: "instance-folder-" + instanceRow.modelData.version; text: "目录"; source: "../../images/version/folder.png"; onClicked: instancesPage.action(instanceRow.modelData.version, "folder") }
                            IconButton { objectName: "instance-delete-" + instanceRow.modelData.version; text: "删除"; source: "../../images/version/delete.png"; onClicked: instancesPage.action(instanceRow.modelData.version, "deleteVersion") }
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
