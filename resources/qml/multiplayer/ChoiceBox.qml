import QtQuick
import QtQuick.Controls.Basic

ComboBox {
    id: control
    implicitHeight: 34
    leftPadding: 14
    rightPadding: 32
    contentItem: CopyText { text: control.displayText; color: "#f4f0ff"; verticalAlignment: Text.AlignVCenter; wrapMode: Text.NoWrap; elide: Text.ElideRight }
    indicator: Item {
        x: control.width - 24; y: (control.height - height) / 2
        width: 10; height: 6
        Rectangle { x: 1; y: 1; width: 6; height: 2; rotation: 45; color: "#c5b7df" }
        Rectangle { x: 4; y: 1; width: 6; height: 2; rotation: -45; color: "#c5b7df" }
    }
    opacity: enabled ? 1 : 0.55
    background: Rectangle { color: control.hovered ? "#33263f" : "#211a2c"; border.color: control.activeFocus ? "#a99bf8" : control.hovered ? "#8b85da" : "#625482" }
    delegate: ItemDelegate {
        width: control.width
        implicitHeight: 32
        objectName: "choice-option-" + index
        property bool selectedOption: control.currentIndex === index
        leftPadding: 14; rightPadding: 34
        contentItem: CopyText { text: modelData; color: "#f1eaff"; wrapMode: Text.NoWrap; elide: Text.ElideRight }
        background: Rectangle {
            color: selectedOption ? (highlighted ? "#473668" : "#392b58") : (highlighted ? "#292735" : "#1d1c28")
            Rectangle { width: 3; height: parent.height - 12; y: 6; color: "#a99bf8"; visible: selectedOption }
        }
        CopyText { anchors.right: parent.right; anchors.rightMargin: 12; anchors.verticalCenter: parent.verticalCenter; text: "✓"; color: "#d7cbff"; visible: parent.selectedOption }
        highlighted: control.highlightedIndex === index
    }
    popup: Popup {
        y: control.height + 4; width: control.width; padding: 4
        implicitHeight: Math.min(180, contentItem.implicitHeight + 8)
        contentItem: ListView { clip: true; implicitHeight: contentHeight; model: control.popup.visible ? control.delegateModel : null; currentIndex: control.highlightedIndex; ScrollIndicator.vertical: ScrollIndicator {} }
        background: Rectangle { color: "#211a2c"; border.color: "#8b85da" }
    }
}
