import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Item {
    id: root
    property var state: headerModel.view
    function openList() {
        choices.popup.open(); choices.forceActiveFocus()
        Qt.callLater(function() {
            if (root.state.picker_index >= 0) {
                choices.popup.contentItem.currentIndex = root.state.picker_index
                choices.popup.contentItem.positionViewAtIndex(root.state.picker_index, ListView.Contain)
            }
        })
    }
    Connections {
        target: headerModel
        function onChanged() { if (root.state.picker_open) root.openList() }
    }
    ChoiceBox {
        id: choices
        width: root.width; height: 0
        model: root.state.versions
        currentIndex: root.state.picker_index
        popup.y: 0; popup.width: root.width; popup.height: root.height
        popup.padding: 5
        popup.closePolicy: Popup.NoAutoClose
        popup.background: Rectangle { color: "#1d1c28"; radius: 5; border.color: "#8b85da"; border.width: 1 }
        delegate: ItemDelegate {
            id: option
            required property int index
            required property var modelData
            property bool selected: modelData === root.state.selected
            property bool keyboardFocused: index === root.state.picker_index
            objectName: "choice-option-" + index
            width: choices.popup.width - 10; height: 59
            padding: 0; hoverEnabled: true
            background: Rectangle {
                radius: 3
                color: option.selected ? (option.hovered ? "#473668" : "#392b58") : option.hovered ? "#292735" : "#1d1c28"
                border.color: option.keyboardFocused ? "#8b85da" : "transparent"
                Rectangle { x: 0; y: 7; width: 3; height: parent.height - 14; visible: option.selected; color: "#a99bf8" }
                Rectangle { anchors.bottom: parent.bottom; anchors.left: parent.left; anchors.right: parent.right; anchors.leftMargin: 12; anchors.rightMargin: 12; height: 1; color: "#393246"; visible: option.index < root.state.versions.length - 1 }
            }
            contentItem: RowLayout {
                spacing: 12
                Item { Layout.preferredWidth: 2 }
                Image { Layout.preferredWidth: 25; Layout.preferredHeight: 25; source: root.state.resources + "images/user/offline_login.png"; fillMode: Image.PreserveAspectFit }
                Text {
                    objectName: "version-option-title-" + option.index
                    Layout.fillWidth: true; Layout.minimumWidth: 0
                    text: option.modelData; elide: Text.ElideMiddle
                    color: "#f4f0ff"; font.pixelSize: 13; font.bold: option.selected
                    verticalAlignment: Text.AlignVCenter
                }
                Text { visible: option.selected; text: "✓ 当前"; color: "#d7cbff"; font.pixelSize: 12 }
                Item { Layout.preferredWidth: 14 }
            }
            onClicked: headerModel.selectVersion(modelData)
            HoverHandler { cursorShape: Qt.PointingHandCursor }
            Accessible.name: modelData
            Accessible.description: selected ? "当前游戏版本" : "选择此游戏版本"
        }
        onActivated: headerModel.selectVersion(currentText)
        Keys.onEscapePressed: headerModel.dismissVersionPicker()
    }
    Component.onCompleted: openList()
}
