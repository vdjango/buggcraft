pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import Bugg.DesignSystem

PageLayout {
    id: root
    property var javaEntries: []
    property string selection: ""
    property real viewportHeight: 440
    readonly property var displayedEntries: root.javaEntries.concat(root.selection && !root.javaEntries.some(item => item.id === root.selection) ? [
        {
            id: root.selection,
            name: qsTr("指定 Java"),
            caption: root.selection
        }
    ] : [])
    signal selected(string path)
    signal refreshRequested
    maximumWidth: 860
    ListRow {
        Layout.fillWidth: true
        objectName: "automaticJavaRow"
        iconName: ""
        text: qsTr("自动匹配")
        caption: ""
        selected: root.selection.length === 0
        showChevron: false
        onClicked: root.selected("")
    }
    ListViewport {
        Layout.fillWidth: true
        Layout.preferredHeight: Math.min(root.displayedEntries.length * 80, Math.max(0, Math.min(290, root.viewportHeight - 190)))
        model: root.displayedEntries
        delegate: ListRow {
            required property var modelData
            width: ListView.view.width
            iconName: "folder"
            text: modelData.name
            caption: modelData.caption || modelData.id
            selected: root.selection === modelData.id
            showChevron: false
            onClicked: root.selected(modelData.id)
        }
    }
    RowLayout {
        Layout.fillWidth: true
        ActionButton {
            text: qsTr("添加 Java")
            variant: "secondary"
            onClicked: executable.open()
        }
        Item {
            Layout.fillWidth: true
        }
        IconButton {
            iconName: "refresh"
            accessibleName: qsTr("重新检测")
            onClicked: root.refreshRequested()
        }
    }
    FilePicker {
        id: executable
        title: qsTr("选择 Java 可执行文件")
        nameFilters: ["Java (java.exe)"]
        onFilesChosen: urls => {
            if (urls.length)
                root.selected(urls[0]);
        }
    }
}
