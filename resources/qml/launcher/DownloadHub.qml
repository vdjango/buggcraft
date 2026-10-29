import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Item {
    id: root
    property bool embedded: false
    property var state: contentController.viewState
    Loader { anchors.fill: parent; active: root.embedded || root.state.view !== "import"; visible: root.state.view !== "import"; source: "ContentCatalogue.qml" }
    ColumnLayout {
        anchors.fill: parent; anchors.margins: 15; spacing: 15
        visible: root.state.view === "import"
        RowLayout {
            Layout.fillWidth: true; spacing: 10
            ActionButton { objectName: "pack-import-back"; text: "‹ 返回"; implicitWidth: 70; onClicked: contentController.returnFromImport() }
            Label { text: "导入整合包"; color: "#f2f2f2"; font.pixelSize: 14; font.bold: true }
            Item { Layout.fillWidth: true }
        }
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: form.implicitHeight + 40
            color: "#33beb7ff"
            ColumnLayout {
                id: form
                anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
                anchors.margins: 20; spacing: 15
                RowLayout {
                    Layout.fillWidth: true; spacing: 10
                    InputField {
                        Layout.fillWidth: true; readOnly: true
                        text: root.state.pack_path ? root.state.pack_path.replace(/\\/g, "/").split("/").pop() : ""
                        placeholderText: "选择 BUGGPACK / ZIP / MRPACK 整合包"
                    }
                    ActionButton { objectName: "choose-pack-file"; text: "选择文件"; onClicked: contentController.choosePack() }
                }
                Label {
                    Layout.fillWidth: true; visible: !!root.state.pack_path
                    text: root.state.pack_summary.split("\n").slice(0, 2).join("\n")
                    color: "#d3cbe2"; font.pixelSize: 12; wrapMode: Text.Wrap
                }
                RowLayout {
                    Layout.fillWidth: true; spacing: 15
                    Label { text: "实例名称"; color: "#eee8f7"; font.pixelSize: 13 }
                    InputField {
                        id: packName
                        objectName: "pack-instance-name"; Layout.fillWidth: true
                        text: root.state.pack_name; placeholderText: "选择文件后自动填写"
                        onTextEdited: contentController.setPackName(text)
                    }
                }
                Label { objectName: "pack-import-error"; text: root.state.pack_error; color: "#ff9b91"; Layout.fillWidth: true; wrapMode: Text.Wrap; visible: !!text }
                RowLayout {
                    Layout.fillWidth: true
                    Item { Layout.fillWidth: true }
                    ActionButton {
                        objectName: "start-pack-import"; text: "开始导入"; primary: true
                        enabled: !root.state.pack_inspecting && !!root.state.pack_path && !!packName.text.trim()
                        onClicked: contentController.importPack()
                    }
                }
            }
        }
        Item { Layout.fillHeight: true }
    }
}
