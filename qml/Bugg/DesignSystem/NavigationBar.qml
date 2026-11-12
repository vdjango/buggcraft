pragma ComponentBehavior: Bound
import QtQuick

Item {
    id: root
    property var items: [qsTr("启动"), qsTr("广场"), qsTr("联机"), qsTr("好友")]
    // 可见位置与稳定工具 ID 分离，面板隐藏广场后联机/好友仍为 2/3。
    property var toolIds: [0, 1, 2, 3]
    property var iconNames: []
    readonly property int selectedPosition: toolIds.indexOf(selectedIndex)
    property int selectedIndex: -1
    property bool vertical: false
    property real itemWidth: 58
    property real itemHeight: 34
    property bool underline: false
    signal selected(int index)
    implicitWidth: vertical ? 132 : items.length * itemWidth - 2
    implicitHeight: vertical ? items.length * 46 : itemHeight
    clip: true
    Rectangle {
        objectName: "navigationSelection"
        x: root.vertical ? 0 : Math.max(0, root.selectedPosition) * root.itemWidth + (root.underline ? (root.itemWidth - width) / 2 : 0)
        y: root.vertical ? Math.max(0, root.selectedPosition) * 46 : root.underline ? root.itemHeight - 3 : 0
        width: root.vertical ? root.width : root.underline ? 24 : root.itemWidth - 3
        height: root.vertical ? 40 : root.underline ? 2 : root.itemHeight
        radius: root.underline ? 1 : 9
        color: root.underline ? DesignTokens.accent : DesignTokens.accentWash
        opacity: root.selectedPosition >= 0 ? 1 : 0
        Behavior on x {
            NumberAnimation {
                duration: 180
                easing.type: Easing.OutCubic
            }
        }
        Behavior on y {
            // 横向的下划线/选中块形态切换不可带着旧 y 伸出工具条。
            enabled: root.vertical
            NumberAnimation {
                duration: 180
                easing.type: Easing.OutCubic
            }
        }
        Behavior on opacity {
            NumberAnimation {
                duration: 120
            }
        }
    }
    Repeater {
        model: root.items
        NavItem {
            required property int index
            required property string modelData
            objectName: "nav" + root.toolIds[index]
            x: root.vertical ? 0 : index * root.itemWidth
            y: root.vertical ? index * 46 : 0
            width: root.vertical ? root.width : root.itemWidth - 3
            height: root.vertical ? 40 : root.itemHeight
            text: modelData
            iconName: root.iconNames[index] || ""
            selected: root.selectedIndex === root.toolIds[index]
            drawSelection: false
            onClicked: root.selected(root.toolIds[index])
        }
    }
}
