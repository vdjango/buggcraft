pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import Bugg.DesignSystem
import Bugg.Pages
import Bugg.Shell
import Bugg.Presentation

ApplicationWindow {
    id: window
    objectName: "buggPreviewWindow"
    required property var desktopEnvironment
    property var catalogService: null
    property var contentService: null
    property var updateService: null
    property var sourceSettings: null
    property var accountService: null
    property var gameRuntime: null
    property var multiplayerService: null
    property var applicationLifecycle: null
    property var languageService: null
    readonly property var sourcePreferences: sourceSettings || localSourceSettings
    readonly property alias launchSession: launch
    readonly property alias identitySession: identity
    readonly property alias pageStateStore: uiState
    readonly property alias installCatalogSession: installCatalog
    readonly property alias contentCatalogSession: contentCatalog
    property int activeTool: 0
    property int lastTool: 0
    property int pendingTool: -1
    property int selectedInstance: 0
    property bool restoredPreferences: false
    property string previousLaunchState: "idle"
    readonly property bool initializing: applicationLifecycle ? applicationLifecycle.phase !== "ready" : false
    readonly property bool consentPending: !!applicationLifecycle && applicationLifecycle.phase === "awaiting_consent"
    property real contentReveal: 1
    property string noticeText: ""
    readonly property bool floating: presentation.theme === "panel"
    property var instances: gameRuntime ? gameRuntime.instances : []
    readonly property string viewKey: presentation.theme + ":" + lastTool + ":" + deck.route
    readonly property bool presented: visible && visibility !== Window.Minimized && !presentation.collapsed && !edgeDock.compact
    onViewKeyChanged: {
        if (applicationLifecycle)
            applicationLifecycle.update_view(viewKey);
    }
    onPresentedChanged: {
        if (applicationLifecycle)
            applicationLifecycle.set_presented(presented);
    }
    onInstancesChanged: {
        const saved = gameRuntime ? gameRuntime.preferences.selectedInstance : "";
        const restored = instances.findIndex(item => item.id === saved);
        selectedInstance = restored >= 0 ? restored : Math.max(0, Math.min(selectedInstance, instances.length - 1));
        if (languageService && !initializing)
            languageService.set_game_codes((instances[selectedInstance] || {}).languages || []);
    }
    onSelectedInstanceChanged: {
        if (gameRuntime && restoredPreferences && instances[selectedInstance])
            gameRuntime.set_preference("selectedInstance", instances[selectedInstance].id);
        if (languageService && !initializing)
            languageService.set_game_codes((instances[selectedInstance] || {}).languages || []);
    }
    onInitializingChanged: {
        if (!initializing && languageService)
            languageService.set_game_codes((instances[selectedInstance] || {}).languages || []);
    }

    function navigate(tool) {
        if (tool === 3 && (!multiplayerService || multiplayerService.status.state !== "ready")) {
            if (activeTool === 2)
                return;
            tool = 2;
        }
        edgeDock.setFolded(false);
        noticeTimer.stop();
        if (tool >= 0)
            presentation.collapsed = false;
        const current = toolSwitch.running ? pendingTool : activeTool;
        if (presentation.theme !== "panel" && !presentation.collapsed && (tool < 0 || tool === current))
            return;
        pendingTool = tool === current || tool < 0 ? -1 : tool;
        toolSwitch.restart();
    }

    function notify(message) {
        noticeText = message;
        noticeTimer.restart();
    }

    ChoiceDialog {
        id: agreementDialog
        objectName: "firstRunAgreement"
        visible: !!window.applicationLifecycle && window.applicationLifecycle.phase === "awaiting_consent"
        title: qsTr("使用前请阅读")
        requireReading: true
        message: qsTr("Bugg 使用约定 · 2026-11-16\n\nBugg 是开源、免费、由志愿者维护的游戏启动器。请尊重项目许可证，也请善待维护者。\n\n请使用合法取得的游戏与资源，并遵守游戏、模组及服务器各自的协议。第三方服务器的充值、交易、内容和运营由相应提供者负责；Bugg 无法控制，也不参与这些交易。请自行核实并谨慎消费。\n\n游戏、模组、加载器和光影由不同作者维护。兼容信息和其他玩家的反馈仅供参考，不能保证每种组合正常运行。请备份重要存档。我们会在能力范围内修复问题，不作不切实际的可用性保证；本约定不排除法律规定不得免除的责任。\n\n本版本仅面向已满 18 周岁的用户。未满 18 周岁请选择拒绝，并与监护人沟通后选择适合的产品。请合理安排游戏时间。\n\n联网功能会向所使用的资源服务发送必要的下载请求；登录与联机会向相应服务发送必要的账号和连接信息。长期凭据保存在本机受保护的存储中。使用统计记录随机安装标识、启动次数与时间，登录官方联机服务时关联联机用户名，仅管理员后台可查看；可在常规设置关闭，不发送角色名或游戏内容。问题反馈必须由您主动提交，提交前会说明诊断范围；不会自动上传存档、模组文件或账号凭据。\n\n您可以随时退出并停止使用。拒绝会关闭启动器，不启动登录和联网服务。继续表示您已阅读上述约定，并确认已满 18 周岁。")
        options: [
            {
                id: "reject",
                name: qsTr("拒绝并退出")
            },
            {
                id: "accept",
                name: agreementDialog.readComplete ? qsTr("我已满 18 周岁，阅读并同意") : qsTr("请先阅读至底部"),
                variant: "primary",
                enabled: agreementDialog.readComplete
            }
        ]
        onChosen: value => {
            if (value === "accept")
                window.applicationLifecycle.accept_agreement();
            else
                window.applicationLifecycle.shutdown();
        }
    }

    ChoiceDialog {
        objectName: "shaderFeedbackDialog"
        readonly property var feedback: window.gameRuntime ? window.gameRuntime.shader_feedback : ({})
        visible: !!feedback.token && window.presented
        busy: !!feedback.busy
        title: qsTr("刚安装的光影能正常使用吗？")
        message: (feedback.name || "") + "\n" + qsTr("光影默认未启用。请在游戏内启用后再判断；游戏进程退出不代表光影正常。您的选择会帮助其他用户判断这个组合。反馈仅包含匿名安装标识和版本文件组合。")
        errorText: feedback.error || ""
        options: [
            {
                id: "working",
                name: qsTr("已启用，光影正常"),
                variant: "primary"
            },
            {
                id: "startup_failed",
                name: qsTr("游戏启动失败")
            },
            {
                id: "shader_failed",
                name: qsTr("能启动，光影异常 / 贴图错误")
            },
            {
                id: "",
                name: qsTr("尚未测试 / 稍后反馈")
            }
        ]
        onChosen: value => window.gameRuntime.answer_shader_feedback(feedback.token, value)
    }

    DropArea {
        anchors.fill: parent
        onDropped: drop => {
            if (!window.gameRuntime || window.initializing || !drop.hasUrls)
                return;
            const files = drop.urls.filter(url => /^file:\/\//i.test(url.toString()) && /\.(zip|mrpack|buggpack)$/i.test(url.toString()));
            if (drop.urls.length !== 1 || files.length !== 1) {
                window.notify(qsTr("请拖入一个整合包"));
                return;
            }
            window.gameRuntime.inspect_pack(files[0].toString());
            deck.openToolPage(0, "importPack");
            drop.acceptProposedAction();
        }
    }
    width: edgeDock.displayWidth
    height: edgeDock.displayHeight
    visible: true
    title: "Bugg"
    color: "transparent"
    flags: ((floating || edgeDock.folded || presentation.collapsed) && presentation.trayAvailable ? Qt.Tool : Qt.Window) | Qt.FramelessWindowHint | ((floating || edgeDock.folded || presentation.collapsed) ? Qt.WindowStaysOnTopHint : 0)
    font.family: DesignTokens.fontFamily
    palette.highlight: DesignTokens.accent
    palette.windowText: DesignTokens.text
    palette.text: DesignTokens.text
    palette.buttonText: DesignTokens.text
    palette.placeholderText: DesignTokens.muted
    palette.button: DesignTokens.surface
    palette.midlight: DesignTokens.surfaceHover
    palette.light: DesignTokens.accentWash
    palette.mid: DesignTokens.quiet
    // 唯一窗口关闭钩子；切页、主题切换和折叠不取消会话。真实服务按生命周期文档接入。
    onClosing: close => {
        presentation.closing = true;
        identity.cancel_microsoft();
        installCatalog.cancel();
        contentCatalog.cancel();
        if (applicationLifecycle && applicationLifecycle.phase !== "stopped") {
            close.accepted = false;
            window.hide();
            applicationLifecycle.shutdown();
        } else if (!applicationLifecycle)
            launch.finish();
    }

    IdentitySession {
        id: identity
        objectName: "identitySession"
        service: window.accountService
        onCommitted: deck.finishIdentity()
        onStatus_changed: {
            if (window.gameRuntime && window.restoredPreferences)
                window.gameRuntime.set_preference("identity", identity.saved_state);
        }
    }
    PageStateStore {
        id: uiState
        objectName: "pageStateStore"
    }
    SourceSettings {
        id: localSourceSettings
        objectName: "localSourceSettings"
    }
    InstallCatalogSession {
        id: installCatalog
        objectName: "installCatalogSession"
        service: window.catalogService
    }
    ContentCatalogSession {
        id: contentCatalog
        objectName: "contentCatalogSession"
        service: window.contentService
        active: window.presented && (deck.route === "catalog" || deck.route === "content" || (!deck.route.length && deck.toolIndex === 1))
        detail_view: deck.route === "content"
        auto_dependencies: !window.gameRuntime || window.gameRuntime.preferences.autoDependencies !== false
        translation_enabled: !window.gameRuntime || window.gameRuntime.preferences.contentTranslation !== false
    }
    LaunchSession {
        id: launch
        objectName: "launchSession"
        instances: window.instances
        identity_status: identity.status
        service: window.gameRuntime
        onIdentity_required: {
            if (deck.route !== "identity")
                deck.openPage("identity");
        }
    }
    Connections {
        target: window.updateService
        function onUpdate_available(version) {
            window.notify(qsTr("发现新版本 %1，可在设置「关于与更新」中安装。").arg(version));
        }
    }
    Connections {
        target: window.gameRuntime
        function onNotice(message) {
            window.notify(message);
        }
        function onInitialized(error) {
            const prefs = window.gameRuntime.preferences;
            identity.restore_state(prefs.identity || {});
            presentation.selectTheme(prefs.theme || "small");
            window.restoredPreferences = true;
        }
        function onLaunch_changed(status) {
            const state = window.gameRuntime.launch_status.state;
            const wasRunning = window.previousLaunchState === "running";
            window.previousLaunchState = state;
            if (state === "running" && !wasRunning)
                presentation.applyAfterLaunch(window.gameRuntime.preferences.afterLaunch, !!(window.multiplayerService && ((window.multiplayerService.status.room || {}).id || (window.multiplayerService.status.room || {}).session)));
            else if (wasRunning && state !== "stopping")
                presentation.restoreAfterGame();
            else if (window.previousLaunchState !== "running" && presentation.gameRunning && ["idle", "failed", "exited"].includes(state))
                presentation.restoreAfterGame();
        }
    }

    Behavior on height {
        enabled: window.restoredPreferences && !window.consentPending && !presentation.switching && !edgeDock.compact
        NumberAnimation {
            duration: 360
            easing.type: Easing.OutQuint
        }
    }

    Binding {
        target: DesignTokens
        property: "comfortable"
        value: presentation.layoutProgress > 0.5
    }
    Binding {
        target: DesignTokens
        property: "sizeClass"
        value: presentation.theme
    }
    Binding {
        target: DesignTokens
        property: "scenic"
        value: floatingShell.immersiveHome && !window.consentPending
    }
    Binding {
        target: DesignTokens
        property: "sceneSurfaceOpacity"
        value: window.gameRuntime && window.gameRuntime.preferences.surfaceOpacity !== undefined ? window.gameRuntime.preferences.surfaceOpacity : 0.18
    }
    Binding {
        target: DesignTokens
        property: "pageBackdrop"
        value: floatingShell.pageBackdrop
    }
    Binding {
        target: DesignTokens
        property: "pageSurfaceOpacity"
        value: window.gameRuntime && window.gameRuntime.preferences.pageOverlayOpacity !== undefined ? window.gameRuntime.preferences.pageOverlayOpacity : 0.10
    }
    Binding {
        target: DesignTokens
        property: "pageTextColor"
        value: window.gameRuntime && window.gameRuntime.preferences.pageTextColor !== undefined ? window.gameRuntime.preferences.pageTextColor : "light"
    }
    WindowController {
        // Both layouts use the same controls; only the page density changes.
        id: presentation
        animationsEnabled: window.restoredPreferences || !window.gameRuntime
        objectName: "windowController"
        desktopEnvironment: window.desktopEnvironment
        showOverlayInFullscreen: window.gameRuntime ? !!window.gameRuntime.preferences.showOverlayInFullscreen : false
        targetWindow: window
        dock: edgeDock
        onThemeChanged: {
            if (window.gameRuntime && window.restoredPreferences)
                window.gameRuntime.set_preference("theme", theme);
            if (presentation.theme !== "panel" && window.activeTool < 0) {
                toolSwitch.stop();
                window.activeTool = window.lastTool;
                window.pendingTool = window.lastTool;
                window.contentReveal = 1;
            }
        }
    }
    EdgeDock {
        id: edgeDock
        objectName: "edgeDock"
        targetWindow: window
        desktopEnvironment: window.desktopEnvironment
        expandedWidth: 410 + (Math.min(presentation.pageWidth, workArea.width > 0 ? workArea.width - 16 : presentation.pageWidth) - 410) * presentation.layoutProgress
        expandedHeight: window.consentPending ? Math.min(floatingShell.pageExtent, workArea.height > 0 ? workArea.height - 16 : floatingShell.pageExtent) : DesignTokens.modalCount > 0 ? Math.max(floatingShell.requestedHeight, Math.min(520, workArea.height > 0 ? workArea.height - 16 : 520)) : floatingShell.requestedHeight
    }
    FloatingShell {
        id: floatingShell
        anchors.fill: parent
        dock: edgeDock
        pageMode: presentation.layoutProgress
        preferredPageHeight: presentation.pageHeight
        activeTool: presentation.collapsed ? -1 : window.activeTool
        contentHeight: deck.implicitHeight
        contentMaximumWidth: deck.contentMaximumWidth
        fixedViewport: deck.fixedViewport
        contentReveal: presentation.collapsed ? 0 : window.contentReveal
        notice: noticeTimer.running ? window.noticeText : launch.status.memoryNotice || ""
        title: deck.pageTitle
        caption: deck.pageCaption
        captionColor: deck.route === "room" ? (deck.roomStatus.availability === "ready" ? DesignTokens.success : DesignTokens.warning) : DesignTokens.muted
        canGoBack: deck.canGoBack
        roomHeader: deck.route === "room"
        roomManager: !!deck.roomStatus.isManager || deck.roomStatus.role === "host"
        friendsVisible: !!window.multiplayerService && window.multiplayerService.status.state === "ready"
        onHeaderActionRequested: deck.openPage("roomSettings")
        showPageHeader: deck.showPageHeader
        backdropAllowed: !presentation.collapsed
        mediaAllowed: !window.floating
        backgrounds: window.gameRuntime ? window.gameRuntime.preferences.backgrounds || [] : uiState.values["appearance.backgrounds"] || []
        backgroundActive: window.visible && window.visibility !== Window.Minimized && launch.status.state !== "running"
        backgroundEffects: window.gameRuntime ? window.gameRuntime.preferences : ({})
        backgroundOnPages: window.gameRuntime ? window.gameRuntime.preferences.backgroundOnPages === true : false
        backgroundPageOverlayOpacity: window.gameRuntime && window.gameRuntime.preferences.pageOverlayOpacity !== undefined ? window.gameRuntime.preferences.pageOverlayOpacity : 0.10
        backgroundSoundEnabled: window.gameRuntime ? window.gameRuntime.preferences.backgroundSoundEnabled === true : false
        activity: window.gameRuntime ? window.gameRuntime.activity : ({
                active: launch.status.state === "preparing",
                progress: launch.status.progress || -1
            })
        immersiveHome: presentation.theme !== "panel" && !presentation.collapsed && !edgeDock.compact && window.lastTool === 0 && deck.route.length === 0
        onNavigateRequested: index => window.navigate(index)
        onTasksRequested: {
            // 工具条入口不切换菜单索引；复用当前页面栈和窗口展开状态。
            edgeDock.setFolded(false);
            presentation.collapsed = false;
            toolSwitch.stop();
            window.activeTool = window.lastTool;
            window.pendingTool = window.lastTool;
            window.contentReveal = 1;
            deck.openPage("tasks");
        }
        onBackRequested: deck.goBack()
        onHomeRequested: deck.goHome()
        onExpandRequested: {
            presentation.selectTheme(presentation.theme);
            window.raise();
            window.requestActivate();
        }
        onCollapseRequested: {
            presentation.collapseToEdge(Qt.TopEdge);
        }
        onCloseRequested: {
            if (deck.route === "room" && window.multiplayerService)
                deck.requestLeaveRoom();
            else
                window.close();
        }
        onBackgroundSoundToggled: enabled => {
            if (window.gameRuntime)
                window.gameRuntime.set_preference("backgroundSoundEnabled", enabled);
        }
    }
    ToolDeck {
        id: deck
        onEnlargeLogsRequested: {
            logsWindow.show();
            logsWindow.raise();
            logsWindow.requestActivate();
        }
        objectName: "toolContent"
        parent: floatingShell.contentHost
        width: parent.width
        height: implicitHeight
        toolIndex: window.lastTool
        instances: window.instances
        selectedIndex: window.selectedInstance
        launchStatus: window.initializing ? ({
                state: "initializing",
                title: qsTr("正在初始化"),
                progress: -1,
                detail: window.gameRuntime && !window.gameRuntime.loading_instances ? qsTr("恢复游戏身份") : qsTr("读取配置与游戏环境")
            }) : (window.launchSession ? window.launchSession.status : {
                state: "idle"
            })
        identityStatus: window.identitySession ? window.identitySession.status : ({})
        canStart: launch.can_start
        viewActive: window.activeTool >= 0 && !presentation.collapsed && !edgeDock.compact
        pageState: uiState.values
        installCatalog: installCatalog.status
        contentCatalog: contentCatalog
        updateService: window.updateService
        sourceSettings: window.sourcePreferences.status
        runtime: window.gameRuntime
        multiplayer: window.multiplayerService
        backdropTint: floatingShell.backdropColor
        languageService: window.languageService
        loadingInstances: window.initializing || (window.gameRuntime ? window.gameRuntime.loading_instances : false)
        tasks: window.gameRuntime ? window.gameRuntime.tasks : []
        environment: window.gameRuntime ? window.gameRuntime.environment : ({})
        onSourceMoveRequested: (index, delta) => window.sourcePreferences.move_source(index, delta)
        onSourceBaseUrlRequested: value => window.sourcePreferences.set_bugg_base_url(value)
        onCatalogRequested: installCatalog.ensure_loaded()
        onCatalogRefreshRequested: installCatalog.refresh()
        onGameVersionSelected: version => installCatalog.select_game(version)
        onLoaderSelected: kind => installCatalog.select_loader(kind)
        onContentSetupRequested: (game, loader) => installCatalog.prepare_selection(game, loader)
        onLoaderVersionSelected: version => installCatalog.select_loader_version(version)
        onLoaderRetryRequested: installCatalog.retry_loaders()
        onInstanceNameEdited: name => installCatalog.set_instance_name(name)
        authPreviewEnabled: identity.preview_enabled
        previewEnabled: identity.preview_enabled
        theme: presentation.theme
        viewportHeight: floatingShell.viewportHeight
        onRouteChanged: {
            floatingShell.resetScroll();
            // Device authorization survives navigation, folding and restoring.
        }
        onToolIndexChanged: floatingShell.resetScroll()
        onSelected: index => {
            if (!window.launchSession || ["idle", "failed"].includes(window.launchSession.status.state))
                window.selectedInstance = index;
        }
        onLaunchRequested: (index, contributions) => {
            if (window.launchSession)
                window.launchSession.start(index, contributions || {});
            else
                window.notify(qsTr("游戏启动服务尚未接入"));
        }
        onCancelLaunchRequested: {
            if (window.launchSession)
                window.launchSession.cancel();
        }
        onStopGameRequested: {
            if (window.launchSession)
                window.launchSession.stop();
        }
        onOfflineIdentityRequested: name => {
            if (window.identitySession && !deck.identityLocked)
                window.identitySession.use_offline(name);
        }
        onIdentitySelected: id => {
            if (!deck.identityLocked)
                identity.activate_profile(id);
        }
        onDraftEdited: (key, value) => {
            uiState.set_value(key, value);
            if (key === "appearance.backgrounds" && window.gameRuntime) {
                window.gameRuntime.set_preference("backgroundDirectory", "");
                window.gameRuntime.set_preference("backgrounds", value);
            }
        }
        onMicrosoftAuthRequested: {
            if (window.identitySession && !deck.identityLocked)
                window.identitySession.begin_microsoft();
        }
        onMicrosoftCompletionRequested: {
            if (window.identitySession && !deck.identityLocked)
                window.identitySession.complete_microsoft();
        }
        onMicrosoftCancelRequested: {
            if (window.identitySession)
                window.identitySession.cancel_microsoft();
            deck.goBack();
        }
        onMicrosoftLogoutRequested: {
            if (!deck.identityLocked)
                identity.logout_microsoft();
        }
        onNavigateRequested: index => window.navigate(index)
        onThemeRequested: theme => presentation.selectTheme(theme)
        onNoticeRequested: message => window.notify(message)
    }
    Window {
        id: logsWindow
        objectName: "diagnosticLogWindow"
        title: qsTr("Bugg · 问题反馈与调试")
        width: 960
        height: 720
        minimumWidth: 410
        minimumHeight: 430
        transientParent: window
        color: DesignTokens.surface
        LogsPage {
            anchors.fill: parent
            viewportHeight: parent.height
            enlarged: true
            runtime: window.gameRuntime
            service: window.multiplayerService
        }
    }
    SequentialAnimation {
        id: toolSwitch
        NumberAnimation {
            target: window
            property: "contentReveal"
            to: 0
            duration: 65
            easing.type: Easing.OutCubic
        }
        ScriptAction {
            script: {
                if (window.pendingTool >= 0)
                    window.lastTool = window.pendingTool;
                window.activeTool = window.pendingTool;
            }
        }
        PauseAnimation {
            duration: 70
        }
        NumberAnimation {
            target: window
            property: "contentReveal"
            to: window.pendingTool >= 0 ? 1 : 0
            duration: 230
            easing.type: Easing.OutCubic
        }
    }
    Timer {
        id: noticeTimer
        interval: 3200
    }
    Shortcut {
        sequence: "Escape"
        onActivated: {
            if (!edgeDock.folded) {
                if (deck.canGoBack)
                    deck.goBack();
                else if (window.activeTool >= 0)
                    window.navigate(-1);
                else if (edgeDock.attachment)
                    edgeDock.setFolded(true);
            }
        }
    }
}
