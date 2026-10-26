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
        spacing: 14
        Item { Layout.preferredHeight: 0 }
        Rectangle {
            visible: root.state.kind === "about"
            Layout.fillWidth: true; Layout.leftMargin: 15; Layout.rightMargin: 15
            implicitHeight: aboutIntro.implicitHeight + 30
            color: "#211d2b"; border.color: "#514568"; radius: 5
            RowLayout {
                id: aboutIntro
                anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
                anchors.margins: 18; spacing: 14
                Rectangle {
                    Layout.preferredWidth: 54; Layout.preferredHeight: 54; radius: 8
                    color: "#382b52"; border.color: "#7f68b2"
                    Image { anchors.fill: parent; anchors.margins: 5; source: "../../icons/1024x1024/app.png"; fillMode: Image.PreserveAspectFit }
                }
                ColumnLayout {
                    Layout.fillWidth: true; spacing: 5
                    Label { text: "Buggcraft"; color: "#f2edfc"; font.pixelSize: 18; font.bold: true }
                    Label { Layout.fillWidth: true; text: "版本 " + root.state.launcherVersion + "  ·  实例管理 · 资源下载 · 好友联机"; color: "#b8afc9"; font.pixelSize: 12; wrapMode: Text.Wrap }
                    Label { Layout.fillWidth: true; text: "让安装、管理和一起游玩都在一个地方完成。"; color: "#897f9a"; font.pixelSize: 11; wrapMode: Text.Wrap }
                }
            }
        }
        RowLayout {
            visible: root.state.kind === "about"
            Layout.fillWidth: true; Layout.leftMargin: 15; Layout.rightMargin: 15; spacing: 10
            Repeater {
                model: [
                    {title:"官方网站", url:"https://bugg.icu/"},
                    {title:"使用帮助", url:"https://github.com/vdjango/buggcraft#通过节点联机"},
                    {title:"问题反馈", url:"https://github.com/vdjango/buggcraft/issues"}
                ]
                ActionButton {
                    required property var modelData
                    Layout.fillWidth: true; text: modelData.title
                    onClicked: recordPage.action(modelData.url, "查看")
                }
            }
        }
        SettingsSection {
            visible: root.state.kind === "java"
            objectName: "java-versions-section"
            Layout.fillWidth: true; Layout.leftMargin: 15; Layout.rightMargin: 15
            title: root.state.javaCatalogOpen ? "下载 Java" : "Java 版本列表"
            summary: root.state.javaCatalogOpen ? "选择适合当前游戏的运行环境" : "已检测到 " + root.state.records.length + " 个 Java 版本"
            collapsible: false
            headerControl: Component {
                RowLayout {
                    spacing: 6
                    Repeater {
                        model: root.state.javaCatalogOpen ? [] : root.state.actions
                        delegate: ActionButton {
                            required property string modelData
                            text: modelData; implicitWidth: 60; implicitHeight: 30
                            enabled: !root.state.busy
                            onClicked: recordPage.action("", modelData)
                        }
                    }
                    ActionButton {
                        objectName: "java-catalog-back"
                        text: root.state.javaCatalogOpen ? "返回列表" : "下载 Java"
                        implicitWidth: 90; implicitHeight: 30
                        onClicked: root.state.javaCatalogOpen ? recordPage.close_java_catalog("", "") : recordPage.action("", "下载")
                    }
                }
            }
            Label { Layout.fillWidth: true; visible: !root.state.javaCatalogOpen && !!root.state.status; text: root.state.status; color: "#c6bdda"; wrapMode: Text.Wrap }
            Label {
                Layout.fillWidth: true
                visible: !root.state.javaCatalogOpen
                text: "启动游戏时自动选择兼容的 Java，缺少时自动安装。"
                color: "#bcb4ca"; font.pixelSize: 12; wrapMode: Text.Wrap
            }
            Repeater {
                model: root.state.kind === "java" ? root.state.records : []
                delegate: Rectangle {
                    required property var modelData
                    visible: !root.state.javaCatalogOpen
                    Layout.fillWidth: true; implicitHeight: details.implicitHeight + 16
                    color: "transparent"
                    Rectangle { anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom; height: 1; color: "#393445" }
                    ColumnLayout {
                        id: details
                        anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
                        anchors.leftMargin: 2; anchors.rightMargin: 2; anchors.topMargin: 7
                        spacing: 6
                        RowLayout {
                            Layout.fillWidth: true
                            Label { Layout.preferredWidth: 170; text: modelData.title; color: "#eee9f7"; font.pixelSize: 13; font.bold: true; elide: Text.ElideMiddle }
                            Label { Layout.fillWidth: true; Layout.minimumWidth: 0; text: "版本 " + modelData.version + "   ·   " + modelData.vendor; color: "#aaa2bb"; font.pixelSize: 11; elide: Text.ElideRight }
                            IconButton { text: "打开目录"; source: "../../images/version/folder.png"; onClicked: recordPage.action(modelData.id, "打开目录") }
                            IconButton { text: "移除"; source: "../../images/version/delete.png"; onClicked: recordPage.action(modelData.id, "移除") }
                        }
                        Label { Layout.fillWidth: true; text: modelData.description; color: "#8f879e"; font.pixelSize: 11; elide: Text.ElideMiddle }
                    }
                }
            }
            Label { visible: root.state.records.length === 0 && !root.state.javaCatalogOpen; text: "未检测到 Java，可点击刷新或添加。"; color: "#c9c4d6"; font.pixelSize: 12 }
            ColumnLayout {
                objectName: "java-download-catalog"
                visible: root.state.kind === "java" && root.state.javaCatalogOpen
                Layout.fillWidth: true
                ColumnLayout {
                    Layout.fillWidth: true; spacing: 12
                    RowLayout {
                        Layout.fillWidth: true; spacing: 10
                        ColumnLayout {
                            Layout.preferredWidth: 130; spacing: 7
                            Label { text: "Java 版本"; color: "#d8d1e5"; font.pixelSize: 12 }
                            ChoiceBox {
                                objectName: "java-catalog-major"; Layout.fillWidth: true
                                enabled: !root.state.busy; model: root.state.javaMajors
                                currentIndex: Math.max(0, root.state.javaMajors.indexOf(root.state.javaMajor))
                                onActivated: recordPage.set_java_major(root.state.javaMajors[currentIndex])
                            }
                        }
                        ColumnLayout {
                            Layout.fillWidth: true; Layout.minimumWidth: 0; spacing: 7
                            Label { text: "下载来源"; color: "#d8d1e5"; font.pixelSize: 12 }
                            ChoiceBox {
                                objectName: "java-catalog-source"; enabled: !root.state.busy; Layout.fillWidth: true; Layout.minimumWidth: 0
                                model: root.state.javaSources
                                currentIndex: Math.max(0, root.state.javaSources.indexOf(root.state.javaSource))
                                onActivated: recordPage.set_java_source(root.state.javaSources[currentIndex])
                            }
                        }
                        ActionButton {
                            Layout.alignment: Qt.AlignBottom; implicitHeight: 36; implicitWidth: 102
                            objectName: "java-catalog-search"; text: root.state.busy ? "正在获取…" : "获取列表"
                            enabled: !root.state.busy; onClicked: recordPage.load_java_catalog()
                        }
                    }
                    ProgressBar {
                        objectName: "java-catalog-loading"
                        Layout.fillWidth: true; implicitHeight: 4
                        visible: root.state.busy; indeterminate: true
                        palette.highlight: "#bba3ff"; palette.dark: "#514568"
                    }
                    Label { Layout.fillWidth: true; visible: !!root.state.status; text: root.state.status; color: "#c6bdda"; font.pixelSize: 11; wrapMode: Text.Wrap }
                    Repeater {
                        model: root.state.javaPackages
                        delegate: ColumnLayout {
                            required property var modelData
                            Layout.fillWidth: true; spacing: 7
                            Rectangle { Layout.fillWidth: true; height: 1; color: "#393445" }
                            RowLayout {
                                Layout.fillWidth: true; spacing: 12
                                ColumnLayout {
                                    Layout.fillWidth: true; Layout.minimumWidth: 0; spacing: 4
                                    Label { Layout.fillWidth: true; Layout.minimumWidth: 0; text: modelData.title; color: "#eee9f7"; font.pixelSize: 13; font.bold: true; wrapMode: Text.Wrap }
                                    Label { Layout.fillWidth: true; Layout.minimumWidth: 0; text: modelData.description + " · " + modelData.sizeText; color: "#aaa2bb"; font.pixelSize: 11; wrapMode: Text.Wrap }
                                }
                                ActionButton { text: "下载并安装"; enabled: !root.state.busy; onClicked: recordPage.download_java(modelData.id) }
                            }
                        }
                    }
                    Label {
                        Layout.fillWidth: true; visible: root.state.javaPackages.length === 0 && !root.state.status
                        text: root.state.busy ? "正在连接下载源…" : "选择 Java 大版本并获取可用版本。"
                        color: "#c9c4d6"; font.pixelSize: 12; wrapMode: Text.Wrap
                    }
                }
            }
        }

        Repeater {
            model: root.state.kind === "about" ? root.state.sections : []
            delegate: SettingsSection {
                required property var modelData
                Layout.fillWidth: true; Layout.leftMargin: 15; Layout.rightMargin: 15
                flat: true
                title: modelData.title
                summary: ""
                expanded: modelData.title === "关于" || modelData.title === "鸣谢"
                Repeater {
                    model: modelData.records
                    delegate: Rectangle {
                        required property var modelData
                        Layout.fillWidth: true
                        implicitHeight: Math.max(66, row.implicitHeight + 24)
                        color: "transparent"
                        Rectangle { anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom; height: 1; color: "#393445" }
                        RowLayout {
                            id: row
                            anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
                            anchors.topMargin: 12
                            spacing: 14
                            Rectangle {
                                visible: !!modelData.icon
                                Layout.preferredWidth: 40; Layout.preferredHeight: 40
                                color: "#302b3b"
                                radius: 4
                                clip: true
                                Image {
                                    anchors.fill: parent
                                    source: "../../settings/" + modelData.icon
                                    fillMode: Image.PreserveAspectCrop
                                    smooth: false
                                }
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
