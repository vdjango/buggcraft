import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

ScrollView {
    id: root
    property var state: recordPage.view
    Connections { target: recordPage; function onChanged() { root.state = recordPage.view } }
    clip: true
    contentWidth: availableWidth
    ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
    ColumnLayout {
        width: root.availableWidth
        spacing: 20
        Item { Layout.preferredHeight: 0 }
        SettingsSection {
            visible: root.state.kind === "java"
            objectName: "java-versions-section"
            Layout.fillWidth: true; Layout.leftMargin: 15; Layout.rightMargin: 15
            title: "Java版本列表"
            summary: "已检测到 " + root.state.records.length + " 个 Java 版本"
            collapsible: false
            headerControl: Component {
                RowLayout {
                    spacing: 6
                    Repeater {
                        model: root.state.actions
                        delegate: ActionButton {
                            required property string modelData
                            text: modelData; implicitWidth: 60; implicitHeight: 30
                            enabled: !root.state.busy
                            onClicked: recordPage.action("", modelData)
                        }
                    }
                    ActionButton {
                        text: "下载 Java"
                        implicitWidth: 90; implicitHeight: 30
                        onClicked: recordPage.action("", "下载")
                    }
                }
            }
            Label { Layout.fillWidth: true; visible: !!root.state.status; text: root.state.status; color: "#c6bdda"; wrapMode: Text.Wrap }
            Label {
                Layout.fillWidth: true
                text: "启动时会按 Minecraft 版本与加载器选择兼容的 Java；缺少运行环境时，启动器会自动下载、校验并安装到自身目录。"
                color: "#bcb4ca"; font.pixelSize: 12; wrapMode: Text.Wrap
            }
            Repeater {
                model: root.state.kind === "java" ? root.state.records : []
                delegate: Rectangle {
                    required property var modelData
                    Layout.fillWidth: true; implicitHeight: details.implicitHeight + 20
                    color: "#1affffff"
                    ColumnLayout {
                        id: details
                        anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
                        anchors.leftMargin: 10; anchors.rightMargin: 10; anchors.topMargin: 10
                        spacing: 4
                        RowLayout {
                            Layout.fillWidth: true
                            Label { text: modelData.title; color: "#e6ffffff"; font.pixelSize: 13; font.bold: true; elide: Text.ElideMiddle }
                            Label { Layout.fillWidth: true; text: "版本：" + modelData.version + "    供应商：" + modelData.vendor; color: "#b3ffffff"; font.pixelSize: 11; elide: Text.ElideRight }
                            IconButton { text: "打开目录"; source: "../../images/version/folder.png"; onClicked: recordPage.action(modelData.id, "打开目录") }
                            Rectangle { implicitWidth: 1; implicitHeight: 20; color: "#4dffffff" }
                            IconButton { text: "移除"; source: "../../images/version/delete.png"; onClicked: recordPage.action(modelData.id, "移除") }
                        }
                        Label { Layout.fillWidth: true; text: modelData.description; color: "#bcb4ca"; font.pixelSize: 12; elide: Text.ElideMiddle }
                    }
                }
            }
            Label { visible: root.state.records.length === 0; text: "未检测到 Java，可点击刷新或添加。"; color: "#c9c4d6"; font.pixelSize: 12 }
        }

    ModalDialog {
        parent: Overlay.overlay
        anchors.centerIn: parent
        objectName: "java-download-catalog"
        width: Math.min(root.width - 40, 760)
        height: Math.min(root.height - 40, 520)
        modal: true
        title: "下载 Java"
        visible: root.state.kind === "java" && root.state.javaCatalogOpen
        onClosed: recordPage.close_java_catalog("", "")
        footer: DialogButtonBox {
            ActionButton { text: "关闭"; onClicked: parent.parent.close() }
        }
        contentItem: ColumnLayout {
            spacing: 12
                RowLayout {
                    Layout.fillWidth: true; spacing: 10
                    Label { text: "Java 版本"; color: "#e6ffffff" }
                    ChoiceBox {
                        objectName: "java-catalog-major"
                        implicitWidth: 100
                        enabled: !root.state.busy
                        model: root.state.javaMajors
                        currentIndex: Math.max(0, root.state.javaMajors.indexOf(root.state.javaMajor))
                        onActivated: recordPage.set_java_major(root.state.javaMajors[currentIndex])
                    }
                    Label { text: "下载来源"; color: "#e6ffffff" }
                    ChoiceBox {
                        objectName: "java-catalog-source"
                        enabled: !root.state.busy
                        Layout.fillWidth: true
                        model: root.state.javaSources
                        currentIndex: Math.max(0, root.state.javaSources.indexOf(root.state.javaSource))
                        onActivated: recordPage.set_java_source(root.state.javaSources[currentIndex])
                    }
                    ActionButton {
                        objectName: "java-catalog-search"
                        text: root.state.busy ? "正在获取…" : "获取列表"
                        enabled: !root.state.busy
                        onClicked: recordPage.load_java_catalog()
                    }
                }
                ScrollView {
                    Layout.fillWidth: true; Layout.fillHeight: true; clip: true
                    contentWidth: availableWidth
                    ColumnLayout {
                        width: parent.width; spacing: 8
                        Repeater {
                            model: root.state.javaPackages
                            delegate: Rectangle {
                                required property var modelData
                                Layout.fillWidth: true
                                implicitHeight: row.implicitHeight + 20
                                color: "#1affffff"
                                RowLayout {
                                    id: row
                                    anchors.fill: parent; anchors.margins: 10; spacing: 12
                                    ColumnLayout {
                                        Layout.fillWidth: true; spacing: 4
                                        Label { Layout.fillWidth: true; text: modelData.title; color: "white"; font.pixelSize: 13; font.bold: true; wrapMode: Text.Wrap }
                                        Label { Layout.fillWidth: true; text: modelData.description + " · " + modelData.sizeText; color: "#bcb4ca"; font.pixelSize: 12; wrapMode: Text.Wrap }
                                    }
                                    ActionButton {
                                        text: "下载并安装"; enabled: !root.state.busy
                                        onClicked: recordPage.download_java(modelData.id)
                                    }
                                }
                            }
                        }
                        Label {
                            Layout.fillWidth: true; visible: root.state.javaPackages.length === 0
                            text: root.state.busy ? "正在连接下载源…" : "选择 Java 大版本并获取可用压缩包。"
                            color: "#c9c4d6"; font.pixelSize: 12; wrapMode: Text.Wrap
                        }
                    }
                }
        }
    }

    Repeater {
            model: root.state.kind === "about" ? root.state.sections : []
            delegate: ColumnLayout {
                required property var modelData
                Layout.fillWidth: true; Layout.leftMargin: 15; Layout.rightMargin: 15
                spacing: 8
                Label { text: modelData.title; color: "white"; font.pixelSize: 14; font.bold: true }
                Repeater {
                    model: modelData.records
                    delegate: Rectangle {
                        required property var modelData
                        Layout.fillWidth: true
                        implicitHeight: Math.max(66, row.implicitHeight + 24)
                        color: "#33beb7ff"
                        RowLayout {
                            id: row
                            anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
                            anchors.margins: 12
                            spacing: 14
                            Rectangle {
                                visible: !!modelData.icon
                                Layout.preferredWidth: 40; Layout.preferredHeight: 40
                                color: "#4a4a5a"
                            }
                            ColumnLayout {
                                Layout.fillWidth: true; spacing: 4
                                Label { Layout.fillWidth: true; text: modelData.title; color: "white"; font.pixelSize: 13; font.bold: true }
                                Label { Layout.fillWidth: true; text: modelData.description; color: "#bcb4ca"; font.pixelSize: 12; wrapMode: Text.Wrap }
                            }
                            ActionButton { visible: modelData.actions.length > 0; text: "查看"; implicitHeight: 28; onClicked: recordPage.action(modelData.id, "查看") }
                        }
                    }
                }
            }
        }
        Item { Layout.preferredHeight: 5 }
    }
}
