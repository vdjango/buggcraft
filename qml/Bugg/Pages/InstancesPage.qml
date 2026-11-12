pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import Bugg.DesignSystem

PageLayout {
    id: root
    required property var instances
    required property int selectedIndex
    property bool selectionOnly: false
    property real viewportHeight: 440
    property bool swipeHintSeen: true
    property string queryText: ""
    signal queryEdited(string value)
    signal selected(int index)
    signal openRequested(string route)
    signal hintShown
    maximumWidth: 860
    spacing: 14
    InputField {
        id: search
        objectName: "instanceSearchField"
        Layout.fillWidth: true
        leadingIcon: "compass"
        placeholderText: qsTr("搜索游戏")
        text: root.queryText
        onTextEdited: root.queryEdited(text)
    }
    ListViewport {
        objectName: "instancesViewport"
        Layout.fillWidth: true
        Layout.preferredHeight: Math.max(96, root.viewportHeight - (DesignTokens.comfortable ? 164 : 136))
        model: root.instances.map((item, index) => ({
                    item: item,
                    originalIndex: index
                })).filter(entry => (entry.item.name + " " + entry.item.version + " " + entry.item.loader).toLowerCase().includes(root.queryText.trim().toLowerCase()))
        delegate: SwipeListRow {
            required property var modelData
            required property int index
            objectName: "manageInstance" + modelData.originalIndex
            width: ListView.view.width
            text: modelData.item.name
            caption: modelData.item.version + " · " + modelData.item.loader
            selected: modelData.originalIndex === root.selectedIndex
            leadingSize: DesignTokens.comfortable ? 42 : 32
            leadingComponent: Component {
                WorldMark {}
            }
            hint: index === 0 && !root.swipeHintSeen
            actions: [
                {
                    id: "exportPack",
                    text: qsTr("导出")
                },
                {
                    id: "deleteInstance",
                    text: qsTr("删除"),
                    danger: true
                }
            ]
            onHintShown: root.hintShown()
            onClicked: {
                root.selected(modelData.originalIndex);
                if (!root.selectionOnly)
                    root.openRequested("instance");
            }
            onActionRequested: action => {
                // 操作目标只切换选择，不走选择完成的自动返回。
                root.operationRequested(modelData.originalIndex, action);
            }
        }
        UiText {
            anchors.centerIn: parent
            visible: parent.count === 0
            text: qsTr("没有匹配的游戏")
            color: DesignTokens.muted
        }
    }
    signal operationRequested(int index, string route)
    RowLayout {
        objectName: "instancesFooter"
        Layout.fillWidth: true
        spacing: 6
        ActionButton {
            text: qsTr("安装游戏")
            iconName: "plus"
            variant: "ghost"
            compact: true
            onClicked: root.openRequested("install")
        }
        IconButton {
            iconName: "folder"
            accessibleName: qsTr("游戏目录")
            onClicked: root.openRequested("storage")
        }
        Item {
            Layout.fillWidth: true
        }
        ActionButton {
            objectName: "manageInstancesButton"
            visible: root.selectionOnly
            text: qsTr("管理")
            variant: "ghost"
            compact: true
            enabled: root.selectedIndex >= 0 && root.selectedIndex < root.instances.length
            onClicked: root.openRequested("instance")
        }
    }
}
