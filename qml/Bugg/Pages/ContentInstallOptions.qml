pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import Bugg.DesignSystem

// The same installation form is a sidebar or the panel's installation tab.
ColumnLayout {
    id: root
    property var session: null
    property var status: session ? session.status : ({})
    property var instances: []
    property string targetId: ""
    property var inspection: ({})
    readonly property var project: status.project || ({})
    readonly property var plan: status.plan || ({})
    readonly property var currentInspection: inspection.instance === targetId && JSON.stringify(inspection.requestedPlan) === JSON.stringify(plan) ? inspection : ({})
    readonly property var shaderSupport: !currentInspection.loading && !currentInspection.error ? currentInspection.shaderSupport || plan.shaderSupport || ({}) : plan.shaderSupport || ({})
    readonly property string selectionIdentity: JSON.stringify([targetId, plan])
    readonly property bool pack: status.kind === "modpack"
    readonly property bool ready: !!plan.files && plan.files.length > 0 && !status.planning && !status.detailLoading && !status.detailError && !status.planError
    readonly property var installed: !currentInspection.loading ? currentInspection.installed || [] : []
    readonly property bool alreadyInstalled: installed.length > 0 && installed.every(item => item.matchesSelected)
    readonly property var replacementFiles: [...new Set((currentInspection.conflicts || []).concat(currentInspection.dependencyConflicts || []))]
    signal targetChosen(string id)
    signal installRequested(var specification)
    signal setupRequested(string game, string loader)
    spacing: root.status.kind === "shader" ? 8 : 12
    onSelectionIdentityChanged: replace.checked = false
    RowLayout {
        Layout.fillWidth: true
        spacing: 10
        ContentImage {
            Layout.preferredWidth: 32
            Layout.preferredHeight: 32
            source: root.project.icon || ""
        }
        UiText {
            Layout.fillWidth: true
            text: [root.project.author, root.project.publisher].filter(Boolean).join(" · ")
            color: DesignTokens.muted
            font.pixelSize: 11
            wrapMode: Text.Wrap
        }
        IconButton {
            visible: !!root.project.website
            iconName: "compass"
            accessibleName: qsTr("查看项目原站")
            onClicked: Qt.openUrlExternally(root.project.website)
        }
    }
    UiText {
        Layout.fillWidth: true
        visible: root.status.kind !== "shader"
        text: root.project.description || ""
        wrapMode: Text.Wrap
        maximumLineCount: 3
        font.pixelSize: 12
    }
    GridLayout {
        Layout.fillWidth: true
        columns: root.status.kind === "shader" ? 2 : 1
        columnSpacing: 2
        rowSpacing: 2
        UiText {
            Layout.fillWidth: true
            font.pixelSize: 11
            wrapMode: Text.Wrap
            color: DesignTokens.muted
            text: root.status.translationEnabled === false ? qsTr("资源翻译已关闭") : !root.status.translated ? qsTr("正在显示原文") : root.status.translationError ? qsTr("译文暂不可用，显示原文") : root.project.translatedBody ? qsTr("中文译文") : root.status.translationLoading ? qsTr("正在获取译文…") : root.status.translationPending ? root.project.translatedSummary ? qsTr("简介已翻译，正文准备中") : qsTr("译文准备中，可继续安装") : root.project.translatedSummary ? qsTr("简介已翻译，正文显示原文") : qsTr("暂无匹配译文，显示原文")
        }
        ActionButton {
            objectName: "contentTranslationToggle"
            visible: root.status.translationEnabled !== false
            text: root.status.translated ? qsTr("查看原文") : qsTr("显示中文")
            compact: true
            variant: "ghost"
            onClicked: {
                if (root.session)
                    root.session.set_original_text(!!root.status.translated);
            }
        }
    }
    Divider {
        Layout.fillWidth: true
    }
    UiText {
        text: qsTr("安装选项")
        font.weight: Font.DemiBold
        font.pixelSize: DesignTokens.controlTextSize
    }
    SelectField {
        objectName: "contentTargetSelector"
        Layout.fillWidth: true
        visible: !root.pack
        label: qsTr("目标游戏")
        options: root.instances.map(item => ({
                    id: item.id,
                    name: item.name,
                    caption: [item.version, [item.loader, item.loaderVersion].filter(Boolean).join(" ")].filter(Boolean).join(" · ")
                }))
        selection: root.targetId
        showSelectedCaption: false
        onChosen: id => root.targetChosen(id)
    }
    UiText {
        Layout.fillWidth: true
        visible: !root.pack && !!root.status.gameVersion
        text: [qsTr("Minecraft %1").arg(root.status.gameVersion || ""), [(root.status.target || {}).loader, (root.status.target || {}).loaderVersion].filter(Boolean).join(" ")].filter(Boolean).join(" · ")
        wrapMode: Text.Wrap
        font.pixelSize: 11
        color: DesignTokens.muted
    }
    SelectField {
        objectName: "contentVersionSelector"
        Layout.fillWidth: true
        label: qsTr("内容版本")
        placeholderText: root.status.detailLoading ? qsTr("获取版本…") : qsTr("暂无兼容版本")
        busy: !!root.status.detailLoading
        options: (root.status.versions || []).map(item => ({
                    id: item.id,
                    name: item.name,
                    caption: ((item.gameVersions || []).includes(root.status.gameVersion) ? qsTr("适配 %1").arg(root.status.gameVersion) + ((item.gameVersions || []).length > 1 ? qsTr(" · 另支持 %1 个版本").arg(item.gameVersions.length - 1) : "") : (item.gameVersions || []).slice(0, 3).join(" / ")) + (item.channel === "beta" ? qsTr(" · 测试版") : item.channel === "alpha" ? qsTr(" · 预览版") : "")
                }))
        selection: (root.status.version || {}).id || ""
        showSelectedCaption: true
        onChosen: id => {
            if (root.session)
                root.session.select_version(id);
        }
    }
    Pagination {
        Layout.alignment: Qt.AlignHCenter
        visible: (root.status.versionTotal || 0) > 20
        pageSize: 20
        itemCount: root.status.versionTotal || 0
        pageIndex: root.status.versionPage || 0
        onChosen: index => {
            if (root.session)
                root.session.version_page(index);
        }
    }
    FormField {
        id: packName
        objectName: "contentPackName"
        Layout.fillWidth: true
        visible: root.pack
        label: qsTr("新游戏名称")
        text: root.project.title || ""
    }
    LoadingIndicator {
        Layout.fillWidth: true
        visible: !!root.status.planning || (!root.pack && root.ready && (!root.currentInspection.instance || !!root.currentInspection.loading))
        text: root.status.planning ? qsTr("检查必要依赖…") : qsTr("检查目标游戏…")
    }
    NoticeBanner {
        objectName: "installedContentNotice"
        Layout.fillWidth: true
        visible: !root.pack && root.installed.length > 0
        text: qsTr("已安装 · %1").arg(root.installed.map(item => item.versionName || item.versionId || item.path).join(" / "))
        color: DesignTokens.success
    }
    NoticeBanner {
        Layout.fillWidth: true
        visible: !root.pack && !!root.status.compatibilityAdvice && !(root.status.kind === "shader" && root.status.compatibility === "compatible")
        text: root.status.compatibilityAdvice || ""
        color: root.status.compatibility === "compatible" ? DesignTokens.success : DesignTokens.warning
    }
    NoticeBanner {
        Layout.fillWidth: true
        visible: !!root.status.detailError || !!root.status.planError || (!root.pack && !!root.currentInspection.error && root.status.compatibility === "compatible") || (!root.status.detailLoading && !(root.status.versions || []).length)
        text: root.status.detailError || root.status.planError || (root.status.compatibility === "compatible" ? root.currentInspection.error : "") || qsTr("没有适合当前筛选的文件。可调整版本筛选，或切换目标游戏。")
        color: DesignTokens.warning
    }
    ActionButton {
        objectName: "matchContentTargetButton"
        visible: !root.pack && (root.status.compatibility === "incompatible" || (!root.status.detailLoading && !(root.status.versions || []).length && !!root.targetId))
        text: qsTr("匹配目标游戏")
        compact: true
        variant: "soft"
        onClicked: {
            if (root.session)
                root.session.match_target();
        }
    }
    UiText {
        Layout.fillWidth: true
        visible: root.ready && root.status.kind !== "shader"
        text: root.pack ? qsTr("整合包将创建独立游戏") : qsTr("自动安装 %1 项必要依赖").arg((root.plan.files || []).filter(item => item.dependency).length)
        font.pixelSize: 11
        color: DesignTokens.muted
        wrapMode: Text.Wrap
    }
    NoticeBanner {
        objectName: "shaderSupportNotice"
        Layout.fillWidth: true
        visible: root.status.kind === "shader" && !!root.shaderSupport.name && !root.currentInspection.error && !root.status.planError && !root.status.detailError
        text: root.shaderSupport.installed ? qsTr("已安装 %1 · %2，将复用现有核心").arg(root.shaderSupport.name).arg(root.shaderSupport.version || "") : qsTr("需要 %1，将自动安装核心及依赖").arg(root.shaderSupport.name)
        color: root.shaderSupport.installed ? DesignTokens.success : DesignTokens.muted
    }
    SelectField {
        objectName: "shaderCoreSelector"
        Layout.fillWidth: true
        visible: root.status.kind === "shader" && !root.shaderSupport.installed && (root.shaderSupport.choices || []).length > 0
        label: qsTr("光影核心版本")
        options: (root.shaderSupport.choices || []).map(item => ({
                    id: item.id,
                    name: item.name,
                    caption: item.publisher + " · " + (item.status === "reviewed_available" ? qsTr("此文件组合经人工标记可用") : item.status === "dependency_unknown" ? qsTr("平台依赖未列出，待核验") : qsTr("平台声明，运行待验证"))
                }))
        selection: root.shaderSupport.choice || ""
        onChosen: id => {
            if (root.session && id !== root.shaderSupport.choice)
                root.session.select_shader_runtime(id);
        }
    }
    UiText {
        Layout.fillWidth: true
        visible: root.status.kind === "shader" && !!root.shaderSupport.choicesIncomplete
        text: qsTr("仅显示已查询的部分核心版本")
        font.pixelSize: 11
        color: DesignTokens.muted
        wrapMode: Text.Wrap
    }
    NoticeBanner {
        Layout.fillWidth: true
        visible: root.status.kind !== "shader" && (root.plan.missingDependencies || []).length > 0
        text: qsTr("部分依赖暂未解析，安装时会再次尝试。所选内容会保留；缺失项将在任务中列出。")
        color: DesignTokens.warning
    }
    CheckOption {
        id: replace
        objectName: "replaceContentOption"
        Layout.fillWidth: true
        visible: !root.pack && root.replacementFiles.length > 0
        text: qsTr("替换已有文件（%1）").arg(root.replacementFiles.length)
    }
    NoticeBanner {
        Layout.fillWidth: true
        visible: replace.visible
        text: root.replacementFiles.slice(0, 3).join("\n")
    }
    ActionButton {
        objectName: "setupContentLoaderButton"
        Layout.fillWidth: true
        visible: !root.pack && ["missingLoader", "noTarget"].includes(root.status.compatibility)
        text: root.status.missingLoader ? (root.status.kind === "shader" ? qsTr("为当前游戏补装光影支持") : qsTr("创建兼容游戏并安装")) : qsTr("先安装兼容游戏")
        compact: true
        enabled: root.ready && !!root.status.suggestedLoader
        onClicked: root.setupRequested(root.status.suggestedGame || "", root.status.suggestedLoader || "")
    }
    ActionButton {
        objectName: "installContentButton"
        Layout.fillWidth: true
        visible: root.pack || !["missingLoader", "noTarget"].includes(root.status.compatibility)
        text: root.pack || !root.installed.length ? qsTr("下载并安装") : root.alreadyInstalled ? qsTr("已安装") : qsTr("替换并安装")
        iconName: root.alreadyInstalled ? "check" : "download"
        compact: true
        enabled: root.ready && (root.pack ? packName.text.trim().length > 0 && !root.instances.some(item => item.name.toLowerCase() === packName.text.trim().toLowerCase()) : root.status.compatibility === "compatible" && (root.status.target || {}).id === root.targetId && root.currentInspection.instance === root.targetId && !root.currentInspection.loading && !root.currentInspection.error && (!(root.status.kind === "shader" ? root.replacementFiles : root.currentInspection.conflicts || []).length || replace.checked))
        onClicked: root.installRequested({
            kind: root.pack ? "onlinePack" : "content",
            id: root.targetId,
            name: qsTr("安装内容 · ") + (root.project.title || ""),
            instanceName: packName.text.trim(),
            plan: root.plan,
            replace: replace.checked
        })
    }
    NoticeBanner {
        Layout.fillWidth: true
        visible: root.pack && root.instances.some(item => item.name.toLowerCase() === packName.text.trim().toLowerCase())
        text: qsTr("已有同名游戏，请修改名称")
    }
    ActionButton {
        visible: !!root.status.detailError || !!root.status.planError
        text: qsTr("重试")
        compact: true
        variant: "ghost"
        onClicked: {
            if (!root.session)
                return;
            if (root.status.detailError)
                root.session.version_page(root.status.versionPage || 0);
            else
                root.session.select_version((root.status.version || {}).id || "");
        }
    }
}
