import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Rectangle {
    id: root
    objectName: "content-details"
    color: "#dd15131f"; radius: 4; border.color: "#403f3859"
    property var state: contentController.viewState
    property var project: state.selected_project || ({})
    property int tab: 0
    property bool expandedGames: false
    property string supportedGames: (project.game_versions || project.versions || []).join(" / ")
    property color adviceColor: state.selected_file.compatibility_state === "warning" ? "#eac389" : state.selected_file.compatibility_state === "compatible" ? "#add3b6" : "#bcb5d0"

    ColumnLayout {
        anchors.fill: parent; anchors.margins: 14; spacing: 8
        RowLayout {
            Layout.fillWidth: true; spacing: 10
            ActionButton {
                objectName: "content-back"; text: "‹"; implicitWidth: 24; implicitHeight: 32
                font.pixelSize: 27; padding: 0; background: Item {}
                onClicked: contentController.backToResults()
                ToolTip.visible: hovered; ToolTip.text: "返回资源列表"
            }
            Rectangle {
                Layout.preferredWidth: 42; Layout.preferredHeight: 42
                color: "#292435"; border.color: "#50465f"; radius: 7
                Label {
                    anchors.centerIn: parent
                    visible: projectIcon.status !== Image.Ready
                    text: (root.project.display_title || root.project.title || "?").substring(0, 1).toUpperCase()
                    color: "#cbbaff"; font.pixelSize: 23; font.bold: true
                }
                Image {
                    id: projectIcon
                    anchors.fill: parent; anchors.margins: 5; asynchronous: true
                    source: root.project.icon_url || ""
                    fillMode: Image.PreserveAspectFit
                }
            }
            ColumnLayout {
                Layout.fillWidth: true; spacing: 5
                Label {
                    Layout.fillWidth: true; text: root.project.display_title || root.project.title || "项目详情"
                    color: "#f4f0ff"; font.pixelSize: 18; font.bold: true; elide: Text.ElideRight; textFormat: Text.PlainText
                    HoverHandler { id: projectTitleHover }
                    ToolTip.visible: projectTitleHover.hovered && truncated; ToolTip.text: text
                }
                Label { Layout.fillWidth: true; text: [root.project.source, root.project.author ? "由 " + root.project.author + " 发布" : ""].filter(Boolean).join("  ·  "); color: "#a69db7"; font.pixelSize: 11; elide: Text.ElideRight }
            }
            ActionButton { text: "项目原站 ↗"; implicitHeight: 32; visible: !!root.project.website_url; onClicked: { if (root.project.website_url.startsWith("https://")) Qt.openUrlExternally(root.project.website_url) } }
            ActionButton { objectName: "content-toggle-original"; text: root.state.show_original ? "显示译文" : "查看原文"; implicitHeight: 32; visible: root.state.translation_enabled; onClicked: contentController.toggleOriginal() }
        }
        RowLayout {
            Layout.fillWidth: true; spacing: 0
            Repeater {
                model: ["项目介绍", "版本文件"]
                delegate: ActionButton {
                    required property int index
                    required property string modelData
                    objectName: "content-detail-tab-" + index
                    text: modelData; implicitWidth: 94; implicitHeight: 33
                    font.pixelSize: 13
                    background: Rectangle {
                        color: "transparent"
                        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 2; color: "#ac98ff"; visible: root.tab === index }
                    }
                    onClicked: root.tab = index
                }
            }
            Item { Layout.fillWidth: true }
            Label { visible: root.tab === 0; text: "版本由你选择"; color: "#91869f"; font.pixelSize: 11 }
            InputField {
                objectName: "content-file-query"
                visible: root.tab === 1; Layout.preferredWidth: 230; implicitHeight: 30
                font.pixelSize: 12; text: root.state.file_query
                placeholderText: "搜索已加载版本、文件名或加载器"
                onTextEdited: contentController.setFileQuery(text)
            }
        }
        ScrollView {
            id: descriptionScroll
            objectName: "content-description"
            visible: root.tab === 0 && !root.state.details_busy; Layout.fillWidth: true; Layout.fillHeight: true
            contentWidth: availableWidth; clip: true
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
            ColumnLayout {
                width: descriptionScroll.availableWidth; spacing: 12
                Label {
                    Layout.fillWidth: true
                    text: !root.state.show_original && root.project.translated_summary ? root.project.translated_summary : root.project.description || root.project.display_summary || "作者暂未提供简介。"
                    color: "#ddd6eb"; font.pixelSize: 13; wrapMode: Text.Wrap; lineHeight: 1.25
                    textFormat: Text.PlainText; maximumLineCount: 3; elide: Text.ElideRight
                    HoverHandler { id: summaryHover }
                    ToolTip.visible: summaryHover.hovered && truncated; ToolTip.text: text
                }
                Surface {
                    Layout.fillWidth: true; implicitHeight: information.implicitHeight + 20
                    color: "#221e30"; border.color: "#42394f"; radius: 4
                    ColumnLayout {
                        id: information
                        anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 10; spacing: 8
                        RowLayout {
                            Layout.fillWidth: true
                            Label { text: "支持的游戏版本"; color: "#f0e9ff"; font.pixelSize: 12; font.bold: true }
                            Item { Layout.fillWidth: true }
                            ActionButton { text: root.expandedGames ? "收起" : "展开"; visible: root.supportedGames.length > 120; implicitHeight: 22; padding: 2; font.pixelSize: 11; background: Item {} onClicked: root.expandedGames = !root.expandedGames }
                        }
                        Label {
                            Layout.fillWidth: true; text: root.supportedGames || "请在版本文件中查看作者声明"
                            color: "#bdb1d4"; font.pixelSize: 12; wrapMode: Text.Wrap; elide: Text.ElideRight
                            maximumLineCount: root.expandedGames ? 1000 : 2; lineHeight: 1.2
                        }
                        Label {
                            objectName: "content-project-compatibility"
                            Layout.fillWidth: true; visible: !!root.state.project_compatibility
                            text: root.state.project_compatibility; color: "#add3b6"; wrapMode: Text.Wrap; font.pixelSize: 11
                        }
                        Rectangle { Layout.fillWidth: true; height: 1; color: "#3b3348" }
                        RowLayout {
                            Layout.fillWidth: true; spacing: 14
                            Repeater {
                                model: [
                                    {title:"下载次数", value:root.project.downloads ? Number(root.project.downloads).toLocaleString(Qt.locale(), "f", 0) : "—"},
                                    {title:"最近更新", value:(root.project.updated || root.project.date_modified || "").substring(0,10) || "—"},
                                    {title:"许可证", value:root.project.license_name || "见项目原站"}
                                ]
                                delegate: ColumnLayout {
                                    required property var modelData
                                    Layout.fillWidth: true; Layout.preferredWidth: 1; Layout.minimumWidth: 0; spacing: 4
                                    Label { text: modelData.title; color: "#9488a5"; font.pixelSize: 11 }
                                    Label { Layout.fillWidth: true; text: modelData.value; color: "#d9d0e8"; elide: Text.ElideRight; font.pixelSize: 12
                                        HoverHandler { id: metaHover }
                                        ToolTip.visible: metaHover.hovered; ToolTip.text: text
                                    }
                                }
                            }
                        }
                    }
                }
                Label {
                    Layout.fillWidth: true; text: (root.project.categories || []).join("  ·  ")
                    visible: !!text; color: "#b49cdf"; font.pixelSize: 11; wrapMode: Text.Wrap
                }
                Label { text: "项目说明"; color: "#eee6fb"; font.pixelSize: 13; font.bold: true }
                Label {
                    objectName: "content-translation-status"
                    Layout.fillWidth: true; visible: root.state.translation_enabled
                    text: root.state.translation_status || (root.project.translated_body ? "AI 自动翻译 · 可切换查看原文" : "正在查找译文…")
                    textFormat: Text.PlainText; color: "#a69db7"; font.pixelSize: 11; wrapMode: Text.Wrap
                }
                Label {
                    Layout.fillWidth: true
                    objectName: "content-body-text"
                    text: root.state.details_busy ? "正在加载项目介绍…" : (!root.state.show_original && root.project.translated_body ? root.project.translated_body : root.project.body_text) || root.project.detail_error || "可在版本文件中查看每个文件支持的游戏版本、加载器和发布日期。"
                    textFormat: Text.MarkdownText; wrapMode: Text.Wrap; color: "#c7bfd5"; font.pixelSize: 13; lineHeight: 1.2
                    onLinkActivated: link => { if (link.startsWith("https://")) Qt.openUrlExternally(link) }
                }
                Item { Layout.preferredHeight: 4 }
            }
        }
        Item {
            Layout.fillWidth: true; Layout.fillHeight: true
            visible: root.tab === 0 && root.state.details_busy
            ColumnLayout {
                objectName: "content-project-loading"
                anchors.centerIn: parent
                BusyIndicator { Layout.alignment: Qt.AlignHCenter; running: root.state.details_busy && root.tab === 0 }
                Label { text: "正在加载项目详情…"; color: "#c7bfd5"; font.pixelSize: 13 }
            }
        }
        PagedListView {
            id: versions
            objectName: "content-version-list"
            visible: root.tab === 1; Layout.fillWidth: true; Layout.fillHeight: true
            model: root.state.versions; spacing: 8; clip: true
            hasMore: root.state.has_more_versions; loading: root.state.busy
            loadFailed: root.state.status.startsWith("获取失败")
            onMoreRequested: contentController.loadMoreVersions()
            delegate: ListRow {
                required property int index
                required property var modelData
                objectName: "content-version-" + index
                width: versions.width; height: 70
                title: modelData.display_name
                description: [modelData.display_date, modelData.channel_label, modelData.game_versions_label, modelData.loaders_label].filter(Boolean).join(" · ")
                selected: root.state.selected_version === index
                icon: selected ? "../../images/version/selected.png" : "../../images/version/not-selected.png"
                onClicked: contentController.selectVersion(index)
                HoverHandler { id: versionHover }
                ToolTip.visible: versionHover.hovered
                ToolTip.text: [modelData.filename, "Minecraft " + modelData.game_versions_label, modelData.loaders_label, modelData.file_size_label].filter(Boolean).join("\n")
            }
            Label { anchors.centerIn: parent; width: parent.width - 24; visible: versions.count === 0; text: root.state.busy ? "正在读取版本文件…" : root.state.file_query ? "已加载文件中没有匹配项，可更换关键词或继续加载版本。" : root.state.status || "作者暂未提供可下载文件。"; wrapMode: Text.Wrap; color: "#b9afca"; horizontalAlignment: Text.AlignHCenter }
        }
        Surface {
            Layout.fillWidth: true; implicitHeight: installArea.implicitHeight + 20
            color: "#221d30"; border.color: "#514364"; radius: 4
            ColumnLayout {
                id: installArea
                anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 10; spacing: 7
                Label {
                    objectName: "content-compatibility"
                    Layout.fillWidth: true; wrapMode: Text.Wrap; font.pixelSize: 12
                    text: root.state.busy && root.state.selected_version < 0 ? "正在加载版本文件与兼容信息…" : root.state.selected_file.compatibility || "兼容信息供参考，可在版本文件中自行选择。"
                    color: root.state.selected_file.compatibility_state === "incompatible" ? "#f09a9a" : root.adviceColor
                }
                RowLayout {
                    Layout.fillWidth: true; spacing: 12
                    ColumnLayout {
                        Layout.fillWidth: true; Layout.minimumWidth: 0; spacing: 4
                        Label { Layout.fillWidth: true; text: (root.state.selected_file.filename || root.state.selected_file.display_name || "请在版本文件中选择文件") + (root.state.selected_file.file_size_label ? " · " + root.state.selected_file.file_size_label : ""); color: "#e5ddee"; elide: Text.ElideMiddle; font.pixelSize: 12 }
                        Label { Layout.fillWidth: true; text: root.state.kind === "modpack" ? "下载后自动安装为独立实例 · " + root.state.target : "安装到「" + root.state.instance + "」 · " + root.state.target; color: "#9e90b0"; elide: Text.ElideMiddle; font.pixelSize: 11
                            HoverHandler { id: destinationHover }
                            ToolTip.visible: destinationHover.hovered; ToolTip.text: text
                        }
                    }
                    ActionButton { objectName: "download-content-version"; text: root.state.kind === "modpack" ? "下载并安装" : "安装所选版本"; implicitWidth: 118; primary: true; enabled: !root.state.busy && root.state.selected_version >= 0 && (root.state.kind === "modpack" || root.state.installable); onClicked: contentController.downloadSelected() }
                }
                Label { Layout.fillWidth: true; visible: !!root.state.status && !root.state.busy; text: root.state.status; color: "#dfb9bc"; wrapMode: Text.Wrap; font.pixelSize: 11 }
                ActionButton { visible: versions.loadFailed && root.tab === 1; text: "重试加载"; implicitHeight: 28; onClicked: contentController.loadMoreVersions() }
            }
        }
    }
}
