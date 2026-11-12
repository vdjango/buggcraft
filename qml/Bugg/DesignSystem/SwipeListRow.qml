pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts

// 复用 ListRow；左右手势仅改变内容偏移，后方操作仍用同一个 ActionButton。
Item {
    id: root
    property alias text: row.text
    property alias caption: row.caption
    property alias value: row.value
    property alias selected: row.selected
    property alias leadingComponent: row.leadingComponent
    property alias leadingSize: row.leadingSize
    property var actions: []
    property bool hint: false
    property real offset: 0
    property real startOffset: 0
    readonly property real revealWidth: actions.length * 76
    signal clicked
    signal actionRequested(string action)
    signal hintShown
    implicitHeight: row.implicitHeight
    clip: true
    RowLayout {
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        spacing: 0
        Repeater {
            model: root.actions
            ActionButton {
                required property var modelData
                Layout.preferredWidth: 76
                text: modelData.text
                variant: modelData.danger ? "danger" : "ghost"
                compact: true
                onClicked: {
                    root.offset = 0;
                    root.actionRequested(modelData.id);
                }
            }
        }
    }
    ListRow {
        id: row
        objectName: root.objectName + "Row"
        x: root.offset
        width: root.width
        showChevron: false
        background: InteractiveSurface {
            control: row
            selected: row.selected
            restingColor: DesignTokens.elevated
            hoverColor: DesignTokens.surface
            selectedColor: DesignTokens.accentWash
        }
        onClicked: {
            if (root.offset < 0)
                root.offset = 0;
            else
                root.clicked();
        }
    }
    DragHandler {
        id: drag
        target: null
        xAxis.enabled: true
        yAxis.enabled: false
        onActiveChanged: {
            if (active) {
                hintClose.stop();
                root.startOffset = root.offset;
            } else root.offset = root.offset < -root.revealWidth / 3 ? -root.revealWidth : 0;
        }
        onTranslationChanged: {
            if (active)
                root.offset = Math.max(-root.revealWidth, Math.min(0, root.startOffset + translation.x));
        }
    }
    Behavior on offset {
        enabled: !drag.active
        NumberAnimation { duration: 180; easing.type: Easing.OutCubic }
    }
    Timer { id: hintClose; interval: 1400; onTriggered: root.offset = 0 }
    Component.onCompleted: {
        if (hint) Qt.callLater(function() {
            root.offset = -root.revealWidth;
            hintClose.start();
            root.hintShown();
        });
    }
}
