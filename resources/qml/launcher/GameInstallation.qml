import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Rectangle {
    id: root
    objectName: "game-installation"
    property var state: gameCatalogue.view
    color: "#272937"
    ColumnLayout {
        anchors.fill: parent; anchors.margins: 18; spacing: 18
        RowLayout {
            Layout.fillWidth: true; spacing: 10
            ActionButton { objectName: "game-install-back"; text: "‹"; implicitWidth: 32; implicitHeight: 30; onClicked: root.state.installView === "versions" ? gameCatalogue.backToComponents() : gameCatalogue.backToGames() }
            Label { Layout.fillWidth: true; text: root.state.installView === "versions" ? "选择 " + root.state.pendingComponent + " 版本" : "安装新游戏"; font.pixelSize: 14; font.bold: true; color: "#dcdcdc" }
        }
        Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: "#8b85da" }
        ScrollView {
            id: componentsScroll
            objectName: "game-component-scroll"
            visible: root.state.installView === "components"
            Layout.fillWidth: true; Layout.fillHeight: true
            clip: true; contentWidth: availableWidth
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
            ColumnLayout {
                width: componentsScroll.availableWidth; spacing: 18
                ListRow {
                    Layout.fillWidth: true; implicitHeight: 68; color: "#40beb7ff"
                    title: "安装实例：" + root.state.game + (root.state.loader ? "-" + root.state.loader : "")
                    description: "Minecraft " + root.state.game
                    icon: "../../images/user/offline_login.png"
                }
                Flow {
                    Layout.fillWidth: true; spacing: 18
                    InstallationComponent { objectName: "component-Minecraft"; name: "Minecraft"; description: root.state.game; selected: true; fixed: true; icon: "../../images/user/offline_login.png" }
                    Repeater {
                        model: root.state.components
                        delegate: InstallationComponent {
                            required property var modelData
                            objectName: "component-" + modelData.name
                            name: modelData.name; description: modelData.description
                            selected: modelData.selected; available: modelData.supported && !modelData.reason
                            symbol: ({Forge:"F", NeoForge:"NF", OptiFine:"OF", Fabric:"F", "Fabric API":"FA", Quilt:"Q", "QSL/QFAPI":"QA"})[modelData.name]
                            onChoose: gameCatalogue.openComponent(modelData.name)
                            onRemove: gameCatalogue.removeComponent(modelData.name)
                        }
                    }
                }
            }
        }
        ListView {
            id: versions
            objectName: "component-version-list"
            visible: root.state.installView === "versions"
            Layout.fillWidth: true; Layout.fillHeight: true; clip: true; spacing: 8
            model: root.state.componentVersions
            ScrollBar.vertical: ScrollBar {}
            delegate: ListRow {
                required property int index
                required property var modelData
                objectName: "component-version-" + index
                width: versions.width; height: 64
                title: root.state.pendingComponent + " " + modelData.name
                description: modelData.date_published ? modelData.date_published.substring(0, 10) : "Minecraft " + root.state.game
                icon: "../../images/user/offline_login.png"
                onClicked: gameCatalogue.chooseComponentVersion(index)
            }
            Label {
                objectName: "component-list-status"
                anchors.centerIn: parent; width: parent.width; wrapMode: Text.Wrap; horizontalAlignment: Text.AlignHCenter
                visible: versions.count === 0; color: "#b3ffffff"
                text: root.state.loaderBusy ? "正在获取版本…" : root.state.loaderStatus || "暂无可用版本"
            }
        }
        RowLayout {
            Layout.fillWidth: true; spacing: 20
            Label { Layout.fillWidth: true; text: root.state.installView === "components" ? root.state.loaderStatus : ""; color: "#e5b59c"; wrapMode: Text.Wrap; font.pixelSize: 12 }
            ActionButton { objectName: "component-reload"; visible: root.state.installView === "versions" && !root.state.loaderBusy; text: "重新加载"; onClicked: gameCatalogue.openComponent(root.state.pendingComponent) }
            ActionButton { objectName: "install-selected-game"; visible: root.state.installView === "components"; text: "安装"; primary: true; implicitWidth: 72; implicitHeight: 35; onClicked: gameCatalogue.install() }
            ActionButton { objectName: "game-install-cancel"; text: root.state.installView === "versions" ? "返回" : "取消"; implicitWidth: 72; implicitHeight: 35; onClicked: root.state.installView === "versions" ? gameCatalogue.backToComponents() : gameCatalogue.backToGames() }
        }
    }
}
