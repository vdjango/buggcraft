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
    property var setupCatalog: ({})
    readonly property bool inlineSetup: (status.kind || "") === "shader" && !!(status.missingLoader || false)
    readonly property string setupContext: inlineSetup ? JSON.stringify([targetId, status.gameVersion, status.suggestedLoader]) : ""
    readonly property string setupIdentity: inlineSetup ? JSON.stringify([setupCatalog.game, setupCatalog.loader, setupCatalog.loaderVersion, setupCatalog.ready]) : ""
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
    signal setupLoaderChosen(string loader)
    signal setupVersionChosen(string version)
    signal setupRetryRequested
    spacing: root.status.kind === "shader" ? 8 : 12
    onSelectionIdentityChanged: replace.checked = false
    onSetupContextChanged: prepareSetup()
    Component.onCompleted: prepareSetup()
    function prepareSetup() {
        if (!root.inlineSetup || !root.session)
            return;
        const game = root.status.suggestedGame || root.status.gameVersion || "";
        const loader = root.status.suggestedLoader || "";
        if (!game || !loader)
            return;
        Qt.callLater(() => {
            if (root.inlineSetup && (root.setupCatalog.game !== game || !root.setupCatalog.loader || root.setupCatalog.loader === "vanilla"))
                root.setupRequested(game, loader);
        });
    }
    onSetupIdentityChanged: {
        const identity = root.setupIdentity;
        Qt.callLater(() => {
            if (identity === root.setupIdentity && root.inlineSetup && root.session && root.setupCatalog.ready && root.setupCatalog.loaderVersion && root.setupCatalog.game === root.status.gameVersion)
                root.session.select_setup_loader(root.setupCatalog.loader || "", root.setupCatalog.loaderVersion || "");
        });
    }
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
        visible: !root.status.missingLoader && (!!root.status.planning || (!root.pack && root.ready && (!root.currentInspection.instance || !!root.currentInspection.loading)))
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
        text: root.pack ? qsTr("整合包将创建独立游戏") : root.plan.query && root.plan.query.autoDependencies === false ? qsTr("自动依赖已关闭，仅安装所选文件") : qsTr("自动安装 %1 项必要依赖").arg((root.plan.files || []).filter(item => item.dependency).length)
        font.pixelSize: 11
        color: DesignTokens.muted
        wrapMode: Text.Wrap
    }
    NoticeBanner {
        Layout.fillWidth: true
        visible: root.status.kind === "shader" && !!root.shaderSupport.automaticDisabled
        text: qsTr("自动依赖已关闭，请自行准备光影核心及其依赖。安装光影包不会启用光影。")
        color: DesignTokens.muted
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
        popupWidth: 420
        showSelectedCaption: false
        options: (root.shaderSupport.choices || []).map(item => ({
                    id: item.id,
                    name: item.name,
                    caption: item.publisher + " · " + (item.feedback ? qsTr("正常 %1 · 失败 %2").arg(item.feedback.counts.working).arg(item.feedback.counts.startup_failed + item.feedback.counts.shader_failed) : item.feedbackUnavailable ? qsTr("反馈暂不可用") : qsTr("反馈待核验"))
                }))
        selection: root.shaderSupport.choice || ""
        onChosen: id => {
            if (root.session && id !== root.shaderSupport.choice)
                root.session.select_shader_runtime(id);
        }
    }
    UiText {
        objectName: "optifineDownloadNotice"
        Layout.fillWidth: true
        visible: root.shaderSupport.id === "optifine"
        text: (root.shaderSupport.optifine || {}).cachePolicy === "cache" ? qsTr("源站缓存 · Forge %1").arg((root.shaderSupport.optifine || {}).forge || "") : qsTr("上游转发 · Forge %1").arg((root.shaderSupport.optifine || {}).forge || "")
        color: DesignTokens.muted
        font.pixelSize: 11
        wrapMode: Text.Wrap
    }
    UiText {
        objectName: "shaderCommunityFeedback"
        Layout.fillWidth: true
        visible: !!root.shaderSupport.name
        readonly property var counts: (root.shaderSupport.feedback || {}).counts
        text: counts ? qsTr("当前核心：正常 %1 · 启动失败 %2 · 光影异常 %3").arg(counts.working).arg(counts.startup_failed).arg(counts.shader_failed) : root.shaderSupport.feedbackUnavailable ? qsTr("反馈暂不可用") : qsTr("此核心暂无反馈")
        color: DesignTokens.muted
        font.pixelSize: 11
        wrapMode: Text.Wrap
        elide: Text.ElideNone
    }
    UiText {
        objectName: "shaderEnvironmentFeedback"
        Layout.fillWidth: true
        readonly property var counts: (root.shaderSupport.environmentFeedback || {}).counts
        visible: !!counts
        text: counts ? qsTr("此游戏 / 加载器：正常 %1 · 启动失败 %2 · 光影异常 %3（含其他核心）").arg(counts.working).arg(counts.startup_failed).arg(counts.shader_failed) : ""
        color: DesignTokens.muted
        font.pixelSize: 11
        wrapMode: Text.Wrap
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
        text: root.status.missingLoader ? (root.status.kind === "shader" ? qsTr("为当前游戏补装光影支持") : qsTr("创建兼容游戏并安装")) : qsTr("先安装兼容游戏")
        compact: true
        enabled: root.ready && !!root.status.suggestedLoader
        visible: !root.pack && ["missingLoader", "noTarget"].includes(root.status.compatibility) && !root.inlineSetup
        onClicked: {
            root.setupRequested(root.status.suggestedGame || "", root.status.suggestedLoader || "");
        }
    }
    SelectField {
        objectName: "inlineShaderLoaderSelector"
        Layout.fillWidth: true
        visible: root.inlineSetup
        label: qsTr("加载器")
        options: [
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
        selection: root.setupCatalog.loader || ""
        onChosen: id => root.setupLoaderChosen(id)
    }
    SelectField {
        objectName: "inlineShaderLoaderVersionSelector"
        Layout.fillWidth: true
        visible: root.inlineSetup
        label: qsTr("加载器版本")
        options: root.setupCatalog.loaders || []
        selection: root.setupCatalog.loaderVersion || ""
        busy: !!root.setupCatalog.loadingLoaders
        placeholderText: root.setupCatalog.loaderError ? qsTr("获取失败，可重试") : qsTr("此游戏版本暂无对应加载器")
        onChosen: id => root.setupVersionChosen(id)
    }
    UiText {
        Layout.fillWidth: true
        visible: root.inlineSetup && (root.setupCatalog.loadingLoaders || !!root.setupCatalog.loaderSource)
        text: root.setupCatalog.loadingLoaders ? qsTr("加载器目录：BUGG 源站优先，失败自动回退") : qsTr("加载器目录来源：%1").arg(root.setupCatalog.loaderSource)
        color: DesignTokens.muted
        font.pixelSize: 10
        wrapMode: Text.Wrap
    }
    NoticeBanner {
        Layout.fillWidth: true
        visible: root.inlineSetup && !!root.setupCatalog.loaderError
        text: root.setupCatalog.loaderError || ""
        color: DesignTokens.warning
    }
    ActionButton {
        visible: root.inlineSetup && !!root.setupCatalog.loaderError
        text: qsTr("重试加载器目录")
        variant: "ghost"
        compact: true
        onClicked: root.setupRetryRequested()
    }
    ActionButton {
        objectName: "installInlineShaderSupportButton"
        Layout.fillWidth: true
        visible: root.inlineSetup
        text: qsTr("补装加载器并安装光影")
        compact: true
        enabled: root.ready && !!root.setupCatalog.ready && root.setupCatalog.game === root.status.gameVersion && !!root.shaderSupport.name && !root.shaderSupport.unavailable && (root.plan.query || {}).loader === root.setupCatalog.loader && (root.plan.query || {}).loaderVersion === root.setupCatalog.loaderVersion
        onClicked: root.installRequested({
            kind: "installWithContent",
            id: root.targetId,
            name: (root.status.target || {}).name || root.targetId,
            game: root.setupCatalog.game,
            loader: root.setupCatalog.loader,
            loaderVersion: root.setupCatalog.loaderVersion,
            plan: root.plan,
            autoDependencies: true,
            updateExisting: true
        })
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
