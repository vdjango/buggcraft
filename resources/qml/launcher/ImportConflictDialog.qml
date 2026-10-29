import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Rectangle {
    id: root
    property var state: dialogModel.view
    color: "#181722"
    border.color: "#735fd0"; border.width: 1; radius: 10
    Connections { target: dialogModel; function onChanged() { root.state = dialogModel.view } }
    ColumnLayout {
        anchors.fill: parent; anchors.margins: 24; spacing: 14
        Label { text: root.state.title; color: "#f4f1ff"; font.pixelSize: 18; font.bold: true; Layout.fillWidth: true }
        Label { text: root.state.message; color: "#ded8f1"; font.pixelSize: 14; wrapMode: Text.Wrap; Layout.fillWidth: true }
        Label { text: root.state.detail; color: "#aaa2c8"; font.pixelSize: 12; wrapMode: Text.Wrap; Layout.fillWidth: true }
        InputField {
            objectName: "import-conflict-name"; Layout.fillWidth: true
            text: root.state.data.name || ""; placeholderText: "输入新的实例名称"
            onTextEdited: dialogModel.setDataValue("name", text)
        }
        RowLayout { Layout.fillWidth: true
            Item { Layout.fillWidth: true }
            Repeater {
                model: root.state.actions
                delegate: ActionButton {
                    required property string modelData
                    required property int index
                    objectName: "dialog-action-" + index
                    text: modelData; primary: modelData === root.state.primaryAction
                    onClicked: dialogModel.action(modelData)
                }
            }
        }
    }
}
