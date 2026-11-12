pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import Bugg.DesignSystem

// 只组合组件并发选择意图；版本、互斥和异步状态归 InstallCatalogSession。
PageLayout {
    id: root
    property var catalog: ({})
    property bool editingName: false
    property string contentTitle: ""
    property var existingTarget: ({})
    signal catalogRequested
    signal refreshRequested
    signal gameSelected(string version)
    signal loaderSelected(string kind)
    signal loaderVersionSelected(string version)
    signal loaderRetryRequested
    signal nameEdited(string name)
    signal noticeRequested(string message)
    signal installRequested(string instanceName)
    signal contentRequested
    Component.onCompleted: catalogRequested()
    spacing: 16
    RowLayout {
        Layout.fillWidth: true
        UiText {
            Layout.fillWidth: true
            text: root.existingTarget.id ? qsTr("为 %1 补装光影支持，保留存档、设置与现有游戏文件").arg(root.existingTarget.name || root.existingTarget.id) : root.contentTitle ? qsTr("创建兼容游戏后安装 %1").arg(root.contentTitle) : qsTr("选好版本，即可安装")
            wrapMode: Text.Wrap
            color: DesignTokens.muted
            font.pixelSize: 11
        }
        ActionButton {
            text: qsTr("查找整合包")
            visible: !root.contentTitle
            iconName: "library"
            compact: true
            variant: "ghost"
            onClicked: root.contentRequested()
        }
        IconButton {
            objectName: "catalogRefreshButton"
            iconName: "refresh"
            accessibleName: qsTr("刷新版本")
            visible: !root.contentTitle
            enabled: !root.catalog.refreshing
            onClicked: root.refreshRequested()
        }
    }
    NoticeBanner {
        Layout.fillWidth: true
        text: root.catalog.error || ""
    }
    SelectField {
        objectName: "minecraftVersionField"
        Layout.fillWidth: true
        label: qsTr("游戏版本")
        enabled: !root.contentTitle
        options: root.catalog.games || []
        selection: root.catalog.game || ""
        busy: root.catalog.loadingGames || false
        onChosen: id => root.gameSelected(id)
    }
    UiText {
        text: qsTr("加载器")
        color: DesignTokens.muted
        font.pixelSize: DesignTokens.comfortable ? 13 : 11
    }
    RowLayout {
        Layout.fillWidth: true
        spacing: 2
        Repeater {
            model: [
                {
                    id: "vanilla",
                    name: qsTr("原版")
                },
                {
                    id: "neoforge",
                    name: "NeoForge"
                },
                {
                    id: "forge",
                    name: "Forge"
                },
                {
                    id: "fabric",
                    name: "Fabric"
                },
                {
                    id: "quilt",
                    name: "Quilt"
                }
            ]
            NavItem {
                required property var modelData
                objectName: "loaderChoice_" + modelData.id
                Layout.fillWidth: true
                text: modelData.name
                selected: root.catalog.loader === modelData.id
                enabled: !!root.catalog.game && !root.contentTitle
                onClicked: root.loaderSelected(modelData.id)
            }
        }
    }
    SelectField {
        objectName: "loaderVersionField"
        Layout.fillWidth: true
        visible: (root.catalog.loader || "vanilla") !== "vanilla"
        label: qsTr("加载器版本")
        options: root.catalog.loaders || []
        selection: root.catalog.loaderVersion || ""
        busy: root.catalog.loadingLoaders || false
        placeholderText: root.catalog.loaderError ? qsTr("获取失败，可重试") : qsTr("没有兼容版本")
        onChosen: id => root.loaderVersionSelected(id)
    }
    RowLayout {
        Layout.fillWidth: true
        visible: !!root.catalog.loaderError
        NoticeBanner {
            Layout.fillWidth: true
            text: root.catalog.loaderError || ""
        }
        ActionButton {
            text: qsTr("重试")
            compact: true
            variant: "ghost"
            onClicked: root.loaderRetryRequested()
        }
    }
    FormField {
        id: instanceName
        objectName: "installInstanceName"
        Layout.fillWidth: true
        visible: root.editingName && !root.existingTarget.id
        label: qsTr("游戏名称")
        text: root.catalog.instanceName || ""
        onTextEdited: value => root.nameEdited(value)
    }
    RowLayout {
        Layout.fillWidth: true
        ActionButton {
            objectName: "installGameButton"
            text: root.existingTarget.id ? qsTr("补装支持并安装光影") : root.contentTitle ? qsTr("创建并安装内容") : qsTr("安装游戏")
            iconName: "download"
            compact: true
            enabled: !!root.catalog.ready && (!!root.existingTarget.id || (!!root.catalog.instanceName && root.catalog.instanceName.trim().length > 0))
            onClicked: root.installRequested(root.catalog.instanceName.trim())
        }
        Item {
            Layout.fillWidth: true
        }
        ActionButton {
            objectName: "editInstallNameButton"
            visible: !root.existingTarget.id
            text: root.editingName ? qsTr("收起名称") : qsTr("修改名称")
            variant: "ghost"
            compact: true
            onClicked: root.editingName = !root.editingName
        }
    }
}
