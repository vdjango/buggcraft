pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls

AbstractButton {
    id: root

    required property int edge
    readonly property bool vertical: edge !== Qt.TopEdge
    signal moveRequested

    objectName: "dockHandle"
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    Accessible.role: Accessible.Button
    Accessible.name: qsTr("展开 Bugg 工具面板")
    background: InteractiveSurface {
        control: root
        radius: 12
    }
    contentItem: Item {
        scale: root.down ? 0.96 : root.hovered ? 1.02 : 1
        Behavior on scale {
            NumberAnimation {
                duration: 110
                easing.type: Easing.OutQuad
            }
        }
        Repeater {
            model: 3
            Rectangle {
                required property int index
                width: 2.5
                height: 2.5
                radius: 1.25
                x: root.vertical ? (parent.width - width) / 2 : parent.width / 2 - 16 + index * 5
                y: root.vertical ? parent.height / 2 - 16 + index * 5 : (parent.height - height) / 2
                color: DesignTokens.quiet
            }
        }
        AppIcon {
            width: 14
            height: 14
            x: root.vertical ? (parent.width - width) / 2 : parent.width / 2 + 5
            y: root.vertical ? parent.height / 2 + 5 : (parent.height - height) / 2
            name: "chevron"
            color: DesignTokens.muted
            rotation: root.edge === Qt.TopEdge ? 90 : root.edge === Qt.RightEdge ? 180 : 0
        }
    }
    DragHandler {
        target: null
        onActiveChanged: if (active)
            root.moveRequested()
    }
}
