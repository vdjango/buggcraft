pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import Bugg.DesignSystem

PageLayout {
    id: root
    objectName: "contentDetailsPage"
    property var session: null
    property var status: session ? session.status : ({})
    property var instances: []
    property real viewportHeight: 500
    property string targetId: ""
    property var inspection: ({})
    property int selectedTab: 0
    readonly property var project: status.project || ({})
    readonly property var plan: status.plan || ({})
    readonly property string inspectionKey: JSON.stringify([targetId, status.compatibility, plan])
    signal inspectRequested(string id, var plan)
    signal targetChosen(string id)
    signal installRequested(var specification)
    signal setupRequested(string game, string loader)
    maximumWidth: 1040
    verticalPadding: 12
    spacing: 12
    Component.onCompleted: {
        if (session && targetId && (status.target || {}).id !== targetId)
            Qt.callLater(() => root.session.select_target(root.instances.find(item => item.id === root.targetId) || {}));
    }
    onInspectionKeyChanged: {
        if (status.kind !== "modpack" && plan.files && plan.files.length && targetId && (status.target || {}).id === targetId && status.compatibility === "compatible")
            inspectRequested(targetId, plan);
    }
    NavigationBar {
        id: tabs
        Layout.fillWidth: true
        visible: !DesignTokens.comfortable
        items: [qsTr("介绍"), qsTr("安装")]
        toolIds: [0, 1]
        selectedIndex: root.selectedTab
        underline: true
        itemWidth: 74
        onSelected: index => root.selectedTab = index
    }
    GridLayout {
        Layout.fillWidth: true
        columns: DesignTokens.comfortable ? 3 : 1
        columnSpacing: 24
        RichDocument {
            id: document
            objectName: "contentDescription"
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            Layout.preferredWidth: 610
            Layout.preferredHeight: Math.max(180, root.viewportHeight - root.verticalPadding * 2 - (DesignTokens.comfortable ? 0 : tabs.implicitHeight + 56))
            visible: DesignTokens.comfortable || root.selectedTab === 0
            model: root.session ? root.session.document_model : blocks
            blocks: (root.project.body || []).concat(root.project.gallery || [])
            introduction: !(root.project.body || []).length && !root.status.detailLoading ? root.project.description || "" : ""
            LoadingIndicator {
                anchors.centerIn: parent
                visible: !!root.status.detailLoading && !document.count
                text: qsTr("获取图文介绍…")
            }
        }
        Divider {
            Layout.preferredWidth: 1
            Layout.fillHeight: true
            visible: DesignTokens.comfortable
        }
        ListViewport {
            objectName: "contentInstallViewport"
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            Layout.preferredWidth: 260
            Layout.maximumWidth: DesignTokens.comfortable ? 300 : 10000
            Layout.preferredHeight: document.Layout.preferredHeight
            visible: DesignTokens.comfortable || root.selectedTab === 1
            model: 1
            delegate: ContentInstallOptions {
                width: ListView.view.width - 10
                session: root.session
                instances: root.instances
                targetId: root.targetId
                inspection: root.inspection
                onTargetChosen: id => root.targetChosen(id)
                onInstallRequested: specification => root.installRequested(specification)
                onSetupRequested: (game, loader) => root.setupRequested(game, loader)
            }
        }
    }
    ActionButton {
        Layout.fillWidth: true
        visible: !DesignTokens.comfortable && root.selectedTab === 0
        text: qsTr("选择版本并安装")
        iconName: "download"
        compact: true
        onClicked: root.selectedTab = 1
    }
    NoticeBanner {
        Layout.fillWidth: true
        visible: !!root.project.bodyError
        text: qsTr("图文介绍暂未获取，可重试或查看原站")
    }
    ActionButton {
        visible: !!root.project.bodyError
        text: qsTr("重试图文介绍")
        compact: true
        variant: "ghost"
        onClicked: {
            if (root.session)
                root.session.version_page(root.status.versionPage || 0);
        }
    }
}
