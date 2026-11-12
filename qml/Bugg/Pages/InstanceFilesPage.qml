pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import Bugg.DesignSystem

PageLayout {
    id: root
    property var snapshot: ({})
    property real viewportHeight: 440
    property string category: "mods"
    signal refreshRequested(string category)
    signal changeRequested(string name, string action)
    signal filesChosen(var urls)
    signal browseRequested(string kind)
    maximumWidth: 860
    verticalPadding: 12
    spacing: 12
    Component.onCompleted: root.refreshRequested(category)
    SelectField {
        Layout.fillWidth: true
        label: qsTr("类型")
        selection: root.category
        options: [
            {
                id: "mods",
                name: qsTr("模组")
            },
            {
                id: "resourcepacks",
                name: qsTr("资源包")
            },
            {
                id: "shaderpacks",
                name: qsTr("光影")
            }
        ]
        onChosen: id => {
            root.category = id;
            root.refreshRequested(id);
        }
    }
    InputField {
        id: search
        Layout.fillWidth: true
        placeholderText: qsTr("搜索")
        leadingIcon: "compass"
    }
    ListViewport {
        Layout.fillWidth: true
        Layout.preferredHeight: Math.max(80, root.viewportHeight - 290)
        enabled: !root.snapshot.loading
        model: (root.snapshot.entries || []).filter(item => item.name.toLowerCase().includes(search.text.toLowerCase()))
        delegate: SwipeListRow {
            required property var modelData
            width: ListView.view.width
            text: modelData.name.replace(/\.disabled$/, "")
            value: modelData.enabled ? qsTr("已启用") : qsTr("已停用")
            actions: [
                {
                    id: "toggle",
                    text: modelData.enabled ? qsTr("停用") : qsTr("启用")
                },
                {
                    id: "delete",
                    text: qsTr("移至回收站"),
                    danger: true
                }
            ]
            onClicked: root.changeRequested(modelData.name, "toggle")
            onActionRequested: action => root.changeRequested(modelData.name, action)
        }
    }
    NoticeBanner {
        Layout.fillWidth: true
        visible: !!root.snapshot.error || (!root.snapshot.loading && !(root.snapshot.entries || []).length)
        text: root.snapshot.error || qsTr("暂无文件")
    }
    RowLayout {
        Layout.fillWidth: true
        ActionButton {
            text: qsTr("添加文件")
            iconName: "plus"
            enabled: !root.snapshot.loading
            onClicked: files.open()
        }
        ActionButton {
            text: qsTr("在线添加")
            iconName: "compass"
            variant: "soft"
            onClicked: root.browseRequested(root.category === "mods" ? "mod" : root.category === "resourcepacks" ? "resourcepack" : "shader")
        }
        Item {
            Layout.fillWidth: true
        }
        IconButton {
            iconName: "refresh"
            accessibleName: qsTr("刷新")
            enabled: !root.snapshot.loading
            onClicked: root.refreshRequested(root.category)
        }
    }
    FilePicker {
        id: files
        multiple: true
        nameFilters: root.category === "mods" ? ["Java (*.jar)"] : ["ZIP (*.zip)"]
        onFilesChosen: urls => root.filesChosen(urls)
    }
}
