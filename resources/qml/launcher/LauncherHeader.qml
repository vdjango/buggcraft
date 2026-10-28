import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root
    property bool versionPopupVisible: root.state.picker_open
    property var state: headerModel.view
    Connections { target: headerModel; function onChanged() { root.state = headerModel.view } }
    MouseArea { anchors.fill: parent; onPressed: headerModel.dragWindow() }
    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: root.state.collapsed ? 10 : 215
        anchors.rightMargin: 11
        spacing: 5
        Button {
            objectName: "toggle-launcher-sidebar"
            Layout.preferredWidth: 40; Layout.preferredHeight: 30
            background: Image { source: root.state.resources + "images/bar/" + (root.state.collapsed ? "toggle-left.png" : "toggle-right.png"); fillMode: Image.PreserveAspectFit }
            onClicked: headerModel.toggleMenu()
        }
        Repeater {
            model: ["开始", "下载", "设置"]
            delegate: Button {
                required property string modelData
                objectName: modelData === "设置" ? "launcher-nav-settings" : modelData === "下载" ? "launcher-nav-download" : "launcher-nav-home"
                Layout.preferredWidth: 100; Layout.preferredHeight: 40
                text: modelData
                background: Image { source: root.state.resources + "images/bar/" + (root.state.active === modelData ? "menu.png" : "no-menu.png") }
                contentItem: Text { text: modelData; color: "#f2f2f2"; font.pixelSize: 14; font.weight: Font.Bold; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                onClicked: {
                    headerModel.navigate(modelData)
                    if (modelData === "设置") tutorial.action("settings")
                }
            }
        }
        Item { Layout.fillWidth: true }
        HeaderAction {
            id: versions
            objectName: "version-picker"
            Layout.preferredWidth: 125; Layout.preferredHeight: 32
            text: "版本"
            artwork: root.state.resources + "images/bar/version_Settings_background.png"
            trailingIcon: root.state.resources + "images/version/expand.png"
            expanded: root.state.picker_open
            function openPicker() {
                var position = versions.mapToItem(root, 0, versions.height + 3)
                headerModel.openVersionPicker(position.x, position.y)
            }
            onClicked: openPicker()
            Keys.onPressed: function(event) {
                if (event.key === Qt.Key_Down || event.key === Qt.Key_Up || event.key === Qt.Key_Space || event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
                    openPicker(); event.accepted = true
                }
            }
            Accessible.name: "选择游戏版本"
        }
        HeaderAction {
            objectName: "instances-button"
            Layout.preferredWidth: 110; Layout.preferredHeight: 32
            text: "实例"
            artwork: root.state.resources + "images/bar/version_Settings_background.png"
            leadingIcon: selected ? root.state.resources + "images/bar/ic.png" : ""
            selected: root.state.active === "实例"
            onClicked: headerModel.navigate("实例")
        }
        Button {
            objectName: "minimize-launcher"
            Layout.preferredWidth: 30; Layout.preferredHeight: 30
            background: Image { source: root.state.resources + "images/bar/min.png" }
            onClicked: headerModel.minimize()
        }
        Button {
            Layout.preferredWidth: 30; Layout.preferredHeight: 30
            background: Image { source: root.state.resources + "images/bar/close.png" }
            objectName: "close-launcher"
            onClicked: headerModel.closeWindow()
        }
    }
}
