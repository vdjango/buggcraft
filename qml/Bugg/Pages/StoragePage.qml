import QtQuick
import QtQuick.Layouts
import Bugg.DesignSystem

PageLayout {
    id: root
    property string gameRoot: ""
    property string cacheRoot: ""
    signal cacheSelected(string path)
    signal noticeRequested(string message)
    signal directorySelected(string path)
    signal openRequested
    maximumWidth: 700
    spacing: 16
    Surface {
        Layout.fillWidth: true
        implicitHeight: gameGroup.implicitHeight + 32
        ColumnLayout {
            id: gameGroup
            anchors.fill: parent
            spacing: 14
            ListRow {
                Layout.fillWidth: true
                text: qsTr("游戏目录")
                caption: root.gameRoot
                iconName: "folder"
                showChevron: false
                hoverFeedbackEnabled: false
                onClicked: root.openRequested()
            }
            RowLayout {
                Layout.fillWidth: true
                ActionButton {
                    text: qsTr("选择已有 Minecraft 目录")
                    variant: "secondary"
                    compact: true
                    onClicked: directory.open()
                }
                Item {
                    Layout.fillWidth: true
                }
                IconButton {
                    iconName: "folder"
                    accessibleName: qsTr("打开当前目录")
                    onClicked: root.openRequested()
                }
            }
        }
    }
    Surface {
        Layout.fillWidth: true
        implicitHeight: cacheRow.implicitHeight + 16
        padding: 8
        ListRow {
            id: cacheRow
            anchors.fill: parent
            text: qsTr("配置与缓存")
            caption: root.cacheRoot
            iconName: "folder"
            onClicked: cache.open()
        }
    }
    DirectoryPicker {
        id: cache
        title: qsTr("选择空目录存放配置与缓存")
        onDirectoryChosen: path => root.cacheSelected(path)
    }
    DirectoryPicker {
        id: directory
        title: qsTr("选择 .minecraft 目录")
        onDirectoryChosen: path => root.directorySelected(path)
    }
}
