import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Item {
    id: root
    property var state: gameCatalogue.view
    Connections { target: gameCatalogue; function onChanged() { root.state = gameCatalogue.view } }
    ColumnLayout {
        anchors.fill: parent
        spacing: 0
        RowLayout {
            objectName: "download-categories"
            visible: root.state.category === "game" ? root.state.installView === "catalogue" : contentController.viewState.view !== "detail"
            Layout.fillWidth: true
            Layout.leftMargin: 15; Layout.rightMargin: 15; Layout.topMargin: 10; Layout.bottomMargin: 3
            spacing: 0
            Repeater {
                model: ["游戏", "模组", "资源包", "光影包", "整合包"]
                delegate: ActionButton {
                    required property int index
                    required property string modelData
                    property string kind: ["game", "mod", "resourcepack", "shader", "modpack"][index]
                    objectName: "content-kind-" + index
                    text: modelData; primary: root.state.category === kind
                    implicitWidth: 60; implicitHeight: 40
                    background: Item {
                        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 2; visible: parent.parent.primary; color: "#7859ff" }
                    }
                    onClicked: gameCatalogue.openContent(kind)
                }
            }
            Item { Layout.fillWidth: true }
            ActionButton { objectName: "download-import-pack"; text: "导入整合包"; implicitHeight: 30; onClicked: gameCatalogue.importPack() }
        }
        Item {
            Layout.fillWidth: true; Layout.fillHeight: true
            Loader {
                anchors.fill: parent
                visible: root.state.category === "game"
                source: "GameCatalogue.qml"
            }
            Loader {
                anchors.fill: parent
                active: root.state.category !== "game"
                sourceComponent: Component { DownloadHub { embedded: true } }
            }
        }
    }
}
