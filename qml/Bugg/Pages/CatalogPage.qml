pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import Bugg.DesignSystem

// The selected installation target owns game-version and loader filtering.
PageLayout {
    id: root
    objectName: "contentBrowserPage"
    property var session: null
    property var status: session ? session.status : ({})
    property var instances: []
    property real viewportHeight: 450
    property string targetId: ""
    property bool filtersExpanded: true
    signal targetChosen(string id)
    signal projectRequested(string id)
    signal openRequested(string route)
    signal filterExpansionRequested(bool expanded)
    readonly property var kinds: ["mod", "resourcepack", "shader", "modpack"]
    maximumWidth: 1040
    verticalPadding: 8
    spacing: 8
    Component.onCompleted: {
        if (session)
            Qt.callLater(() => root.session.ensure_context(root.instances.find(item => item.id === root.targetId) || {}));
    }
    onTargetIdChanged: {
        if (session && (status.target || {}).id !== targetId)
            Qt.callLater(() => root.session.ensure_context(root.instances.find(item => item.id === root.targetId) || {}));
    }
    ColumnLayout {
        id: filters
        Layout.fillWidth: true
        spacing: 8
        RowLayout {
            Layout.fillWidth: true
            spacing: 6
            NavigationBar {
                objectName: "contentCategories"
                items: [qsTr("模组"), qsTr("资源包"), qsTr("光影包"), qsTr("整合包")]
                selectedIndex: root.kinds.indexOf(root.status.kind || "mod")
                itemWidth: DesignTokens.comfortable ? 78 : 52
                itemHeight: 32
                underline: true
                onSelected: index => {
                    if (root.session)
                        root.session.browse(root.kinds[index], root.status.query || "", root.instances.find(item => item.id === root.targetId) || {});
                }
            }
            Item {
                Layout.fillWidth: true
            }
            SelectField {
                objectName: "contentPublisher"
                Layout.preferredWidth: DesignTokens.comfortable ? 82 : 68
                Layout.maximumWidth: Layout.preferredWidth
                compact: true
                popupWidth: 160
                options: [
                    {
                        id: "CurseForge",
                        name: "CurseForge",
                        shortName: "CF"
                    },
                    {
                        id: "Modrinth",
                        name: "Modrinth",
                        shortName: "MR"
                    }
                ]
                selection: root.status.publisher || "CurseForge"
                onChosen: id => {
                    if (root.session)
                        root.session.edit("publisher", id);
                }
            }
            IconButton {
                objectName: "contentFilterDisclosure"
                Layout.preferredWidth: 28
                Layout.preferredHeight: 30
                iconName: "down"
                rotation: root.filtersExpanded ? 180 : 0
                accessibleName: root.filtersExpanded ? qsTr("收起筛选") : qsTr("展开筛选")
                onClicked: {
                    root.filtersExpanded = !root.filtersExpanded;
                    root.filterExpansionRequested(root.filtersExpanded);
                }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            visible: root.filtersExpanded
            spacing: 8
            InputField {
                objectName: "searchInput"
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                leadingIcon: "compass"
                placeholderText: qsTr("搜索名称、作者或关键词")
                text: root.status.query || ""
                onTextEdited: {
                    if (root.session)
                        root.session.edit("query", text);
                }
                onAccepted: {
                    if (root.session)
                        root.session.search();
                }
            }
            SelectField {
                objectName: "contentCategoryFilter"
                Layout.preferredWidth: DesignTokens.comfortable ? 180 : 118
                Layout.maximumWidth: Layout.preferredWidth
                popupWidth: 260
                busy: !!root.status.categoriesLoading
                options: [
                    {
                        id: "",
                        name: qsTr("全部分类")
                    }
                ].concat((root.status.categories || []))
                selection: root.status.category || ""
                onChosen: id => {
                    if (root.session)
                        root.session.edit("category", id);
                }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            visible: !!root.status.error || !!root.status.categoryError
            NoticeBanner {
                Layout.fillWidth: true
                text: root.status.error || qsTr("分类暂未获取，可继续搜索")
                color: root.status.error ? DesignTokens.danger : DesignTokens.warning
            }
            ActionButton {
                text: qsTr("重试")
                compact: true
                variant: "ghost"
                onClicked: {
                    if (root.session) {
                        root.session.load_categories();
                        root.session.search(root.status.page || 0);
                    }
                }
            }
        }
    }
    ListViewport {
        objectName: "contentResults"
        Layout.fillWidth: true
        Layout.preferredHeight: Math.max(120, root.viewportHeight - filters.implicitHeight - footer.implicitHeight - (pagination.visible ? pagination.implicitHeight + root.spacing : 0) - root.verticalPadding * 2 - root.spacing * 2)
        model: root.session ? root.session.results_model : root.status.items || []
        opacity: root.status.loading ? 0.5 : 1
        delegate: ListRow {
            id: result
            required property var modelData
            enabled: !root.status.loading
            width: ListView.view.width
            text: modelData.title || ""
            caption: modelData.description || modelData.author || ""
            leadingSize: DesignTokens.comfortable ? 44 : 36
            leadingComponent: ContentImage {
                source: result.modelData.icon || ""
            }
            onClicked: root.projectRequested(modelData.id)
        }
        LoadingIndicator {
            anchors.centerIn: parent
            visible: !!root.status.loading
            text: qsTr("搜索中…")
        }
        EmptyState {
            anchors.centerIn: parent
            width: Math.max(0, parent.width - 24)
            visible: parent.count === 0 && !root.status.loading
            title: root.status.error ? qsTr("暂时无法获取内容") : qsTr("没有匹配的内容")
            caption: root.status.error ? qsTr("检查网络后重试") : qsTr("试试其他关键词、内容分类或安装目标")
        }
    }
    Pagination {
        id: pagination
        objectName: "contentPagination"
        Layout.alignment: Qt.AlignHCenter
        visible: (root.status.total || 0) > 20
        hasMore: !!root.status.hasMore
        pageSize: 20
        itemCount: root.status.total || 0
        pageIndex: root.status.page || 0
        onChosen: index => {
            if (root.session)
                root.session.search(index);
        }
    }
    RowLayout {
        id: footer
        Layout.fillWidth: true
        spacing: 8
        UiText {
            text: qsTr("安装到")
            color: DesignTokens.muted
            font.pixelSize: 11
        }
        SelectField {
            objectName: "contentGameFilter"
            Layout.preferredWidth: DesignTokens.comfortable ? 200 : 134
            Layout.maximumWidth: Layout.preferredWidth
            compact: true
            popupWidth: 300
            options: [
                {
                    id: "",
                    name: qsTr("选择目标游戏")
                }
            ].concat(root.instances.map(item => ({
                        id: item.id,
                        name: item.name,
                        caption: [item.version, item.loader].filter(Boolean).join(" · ")
                    })))
            selection: root.targetId
            showSelectedCaption: false
            onChosen: id => {
                root.targetChosen(id);
                if (root.session)
                    root.session.browse(root.status.kind, root.status.query || "", root.instances.find(item => item.id === id) || {});
            }
        }
        Item {
            Layout.fillWidth: true
            Layout.minimumWidth: 0
        }
        UiText {
            objectName: "contentFilterSummary"
            readonly property string targetSummary: [root.status.gameVersion || qsTr("全部版本"), ["mod", "modpack"].includes(root.status.kind) ? root.status.loader || "" : ""].filter(Boolean).join(" · ")
            readonly property string categorySummary: ((root.status.categories || []).find(item => item.id === root.status.category) || {}).name || qsTr("全部分类")
            readonly property string resultSummary: qsTr("%1 个结果").arg(root.status.total || 0)
            Layout.maximumWidth: DesignTokens.comfortable ? 430 : 150
            text: root.status.loading ? qsTr("搜索中…") : targetSummary + (DesignTokens.comfortable ? " · " : "\n") + categorySummary + " · " + resultSummary
            horizontalAlignment: Text.AlignRight
            wrapMode: Text.Wrap
            color: DesignTokens.muted
            font.pixelSize: 11
        }
    }
}
