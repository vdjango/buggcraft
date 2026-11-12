pragma ComponentBehavior: Bound
import QtQuick
import Bugg.DesignSystem

Item {
    id: root
    LayoutMirroring.enabled: root.languageService ? root.languageService.right_to_left : false
    LayoutMirroring.childrenInherit: true
    required property var instances
    required property int selectedIndex
    required property string theme
    property int toolIndex: 0
    property string route: ""
    property var history: []
    property var pendingNavigation: null
    property string pendingInstanceName: ""
    property bool taskCancelled: false
    property real pageReveal: 1
    property real viewportHeight: 500
    property var launchStatus: ({
            state: "idle"
        })
    property var identityStatus: ({})
    property var friends: []
    property var pageState: ({})
    property var installCatalog: ({})
    property var contentCatalog: null
    property var updateService: null
    readonly property var contentStatus: contentCatalog ? contentCatalog.status : ({})
    property var sourceSettings: ({})
    property var runtime: null
    property var multiplayer: null
    readonly property var roomStatus: multiplayer ? multiplayer.status.room || ({}) : ({})
    readonly property bool joiningRoom: !!multiplayer && !!multiplayer.status.roomBusy && multiplayer.status.roomOperation === "join"
    property color backdropTint: "#243D44"
    property var languageService: null
    property bool loadingInstances: false
    property var preferences: runtime ? runtime.preferences : ({
            language: "zh_cn",
            concurrency: 6,
            afterLaunch: "keep"
        })
    property int settingsRevision: 0
    Connections {
        target: root.runtime
        function onSettings_changed() {
            root.settingsRevision++;
        }
        function onInstallation_finished(task, instance) {
            if (root.route === "tasks")
                root.goHome();
        }
    }
    property var tasks: []
    property var environment: ({})
    readonly property var currentInstance: instances[selectedIndex] || ({
            name: qsTr("未选择游戏"),
            version: "",
            loader: "",
            id: ""
        })
    property bool authPreviewEnabled: false
    // 显式测试夹具开关；正常入口不把未接入服务的示例快照展示为真实数据。
    property bool previewEnabled: false
    readonly property var unconnectedViews: ({
            taskFiles: qsTr("暂无文件进度，下载服务尚未接入")
        })
    property bool canStart: false
    property bool viewActive: true
    readonly property bool identityLocked: !["idle", "failed"].includes(launchStatus.state)
    readonly property bool canGoBack: joiningRoom || history.length > 0
    readonly property bool showPageHeader: false
    readonly property string pageTitle: joiningRoom ? qsTr("加入房间") : route.length ? routeTitle(route) : [qsTr("启动"), qsTr("广场"), qsTr("联机"), qsTr("好友"), qsTr("设置")][Math.max(0, toolIndex)]
    readonly property string pageCaption: !joiningRoom && route.length ? (routes[route].caption || "") : ""
    function routeTitle(value) {
        return routes[value] ? routes[value].title : "";
    }
    function openPage(value) {
        if (!routes[value])
            return false;
        if (value === "install") {
            root.draftEdited("content.setup", {});
            root.draftEdited("content.setupTarget", {});
        }
        history = history.concat([route]);
        route = value;
        return true;
    }
    // 菜单有切换动画：等待实际工具索引变化后再开二级页，避免被导航复位覆盖。
    function openToolPage(tool, value) {
        if (toolIndex === tool) {
            if (route !== value)
                openPage(value);
        } else {
            pendingNavigation = {
                tool: tool,
                route: value
            };
            navigateRequested(tool);
        }
    }
    function beginInstall(name) {
        if (runtime) {
            if (!installCatalog.ready) {
                noticeRequested(qsTr("请先选择完整的游戏和加载器版本"));
                return;
            }
            const content = root.pageState["content.setup"] || {};
            const target = root.pageState["content.setupTarget"] || {};
            runtime.install({
                kind: content.files ? "installWithContent" : "install",
                plan: content,
                id: target.id || "",
                name: target.id || name,
                game: installCatalog.game,
                loader: installCatalog.loader,
                loaderVersion: installCatalog.loaderVersion
            });
            root.draftEdited("content.setup", {});
            root.draftEdited("content.setupTarget", {});
            openPage("tasks");
            return;
        }
        if (!previewEnabled) {
            noticeRequested(qsTr("安装服务尚未接入，未创建安装任务"));
            return;
        }
        pendingInstanceName = name;
        if (instances.some(instance => instance.name === name))
            openPage("conflict");
        else {
            openPage("tasks");
            noticeRequested(qsTr("交互预览 · 安装服务尚未接入，未创建真实任务"));
        }
    }
    onRouteChanged: pageEntry.restart()
    function goBack() {
        if (joiningRoom) {
            multiplayer.leave_room();
            return;
        }
        if (!history.length)
            return;
        route = history[history.length - 1];
        history = history.slice(0, -1);
    }
    // 清理导航栈，不取消窗口级任务；同在启动入口时避免重复导航把面板收起。
    function goHome() {
        if (joiningRoom)
            multiplayer.leave_room();
        route = "";
        history = [];
        if (toolIndex !== 0)
            navigateRequested(0);
    }
    // 只收回成功选择的身份步骤；取消仍逐级 goBack，业务状态归 C++ 会话。
    function finishIdentity() {
        if (!["identity", "offlineIdentity", "deviceAuth"].includes(route))
            return;
        while (["identity", "offlineIdentity", "deviceAuth"].includes(route) && canGoBack)
            goBack();
    }
    onToolIndexChanged: {
        route = "";
        history = [];
        const destination = pendingNavigation;
        pendingNavigation = null;
        if (destination && destination.tool === toolIndex)
            openPage(destination.route);
    }
    signal selected(int index)
    signal launchRequested(int index, var contributions)
    signal cancelLaunchRequested
    signal stopGameRequested
    signal offlineIdentityRequested(string name)
    signal identitySelected(string id)
    signal draftEdited(string key, var value)
    signal microsoftAuthRequested
    signal microsoftCompletionRequested
    signal microsoftCancelRequested
    signal microsoftLogoutRequested
    signal navigateRequested(int index)
    signal themeRequested(string theme)
    signal noticeRequested(string message)
    signal catalogRequested
    signal catalogRefreshRequested
    signal gameVersionSelected(string version)
    signal loaderSelected(string kind)
    signal loaderVersionSelected(string version)
    signal loaderRetryRequested
    signal instanceNameEdited(string name)
    signal contentSetupRequested(string game, string loader)
    signal sourceMoveRequested(int index, int delta)
    signal sourceBaseUrlRequested(string value)
    readonly property var tools: [launchPage, catalogPage, roomsPage, friendsPage, settingsPage]
    readonly property var routes: ({
            selectInstance: {
                title: qsTr("选择游戏"),
                component: selectionPage
            },
            instances: {
                title: qsTr("游戏实例"),
                component: instancesPage
            },
            instance: {
                title: root.currentInstance.name,
                caption: root.currentInstance.version + " · " + root.currentInstance.loader,
                component: detailsPage
            },
            instanceFiles: {
                title: qsTr("模组与资源"),
                component: filesPage
            },
            instanceSettings: {
                title: qsTr("游戏设置"),
                component: instanceSettingsPage
            },
            gameSettings: {
                title: qsTr("游戏"),
                component: gameSettingsPage
            },
            language: {
                title: qsTr("语言"),
                component: languagePage
            },
            downloads: {
                title: qsTr("下载"),
                component: downloadsPage
            },
            general: {
                title: qsTr("常规"),
                component: generalPage
            },
            multiplayerSettings: {
                title: qsTr("联机服务"),
                component: multiplayerSettingsPage
            },
            deleteInstance: {
                title: qsTr("移除或删除"),
                component: deletePage
            },
            tasks: {
                title: qsTr("任务"),
                component: tasksPage
            },
            taskFiles: {
                title: qsTr("文件进度"),
                component: taskFilesPage
            },
            catalog: {
                title: qsTr("发现内容"),
                component: catalogPage
            },
            content: {
                title: (root.contentStatus.project || {}).title || qsTr("内容详情"),
                component: contentPage
            },
            install: {
                title: (root.pageState["content.setupTarget"] || {}).id ? qsTr("补装光影支持") : qsTr("安装游戏"),
                component: installPage
            },
            importPack: {
                title: qsTr("导入整合包"),
                component: importPage
            },
            exportPack: {
                title: qsTr("导出整合包"),
                caption: root.currentInstance.name,
                component: exportPage
            },
            conflict: {
                title: qsTr("处理同名实例"),
                component: conflictPage
            },
            room: {
                title: root.roomStatus.title || qsTr("房间"),
                caption: [(root.theme === "panel" ? "" : (root.roomStatus.game || {}).version), (root.theme === "panel" ? "" : (root.roomStatus.game || {}).loader), root.roomStatus.role === "host" ? (root.roomStatus.availability === "ready" ? qsTr("本地世界已连接") : root.theme === "panel" ? qsTr("请在游戏中对局域网开放") : qsTr("进入世界后，在暂停菜单选择“对局域网开放”。")) : (root.roomStatus.availability === "ready" ? qsTr("世界已开放") : qsTr("等待房主开放世界")), root.roomStatus.role === "host" ? "" : ({
                            p2p: qsTr("直连"),
                            relay: qsTr("中转")
                        })[root.roomStatus.connectionMode] || ""].filter(Boolean).join(" · "),
                component: roomPage
            },
            notifications: {
                title: root.pageState["friends.notificationCategory"] === "requests" ? qsTranslate("FriendsPage", "好友申请") : qsTranslate("FriendsPage", "联机通知"),
                component: notificationsPage
            },
            friendConversation: {
                title: qsTr("好友"),
                component: friendConversationPage
            },
            createRoom: {
                title: qsTr("创建房间"),
                component: createRoomPage
            },
            joinRoom: {
                title: qsTr("加入房间"),
                component: joinRoomPage
            },
            roomSettings: {
                title: qsTr("房间设置"),
                component: roomSettingsPage
            },
            inviteFriends: {
                title: qsTr("邀请好友"),
                component: inviteFriendsPage
            },
            sync: {
                title: qsTr("文件同步"),
                component: syncPage
            },
            nodes: {
                title: qsTr("联机节点"),
                component: nodesPage
            },
            account: {
                title: qsTr("账号"),
                component: accountPage
            },
            java: {
                title: qsTr("Java 管理"),
                component: javaPage
            },
            sources: {
                title: qsTr("下载来源"),
                component: sourcesPage
            },
            storage: {
                title: qsTr("存储位置"),
                component: storagePage
            },
            feedback: {
                title: qsTr("问题反馈"),
                component: feedbackPage
            },
            update: {
                title: qsTr("关于与更新"),
                component: updatePage
            },
            addFriend: {
                title: qsTr("添加好友"),
                component: addFriendPage
            },
            appearance: {
                title: qsTr("外观"),
                component: appearancePage
            },
            identity: {
                title: qsTr("游戏身份"),
                component: identityPage
            },
            deviceAuth: {
                title: qsTr("微软登录"),
                component: deviceAuthPage
            },
            skin: {
                title: qsTr("皮肤"),
                component: skinPage
            },
            logs: {
                title: qsTr("运行日志"),
                component: logsPage
            },
            buggLogin: {
                title: qsTr("登录 Bugg"),
                component: buggLoginPage
            },
            offlineIdentity: {
                title: qsTr("离线玩家"),
                component: offlineIdentityPage
            }
        })
    readonly property Item toolItem: joiningRoom ? joiningLoader.item as Item : pageLoader.item as Item
    readonly property bool fixedViewport: joiningRoom || ["logs", "catalog", "content", "selectInstance", "instances", "inviteFriends", "notifications", "friendConversation", "room"].includes(route) || (!route.length && [1, 2, 3].includes(toolIndex))
    readonly property real contentMaximumWidth: toolItem instanceof PageLayout ? toolItem.maximumWidth : 560
    implicitHeight: toolItem ? toolItem.implicitHeight : 0
    Loader {
        id: pageLoader
        objectName: "pageLoader"
        visible: !root.joiningRoom
        width: parent.width
        height: item instanceof Item ? (item as Item).implicitHeight : 0
        sourceComponent: root.route.length ? (!root.previewEnabled && root.unconnectedViews[root.route] ? unavailablePage : root.routes[root.route].component) : root.tools[Math.max(0, root.toolIndex)]
        opacity: root.pageReveal
        transform: Translate {
            y: (1 - root.pageReveal) * 7
        }
    }
    NumberAnimation {
        id: pageEntry
        target: root
        property: "pageReveal"
        from: 0
        to: 1
        duration: 170
        easing.type: Easing.OutCubic
    }
    Loader {
        id: joiningLoader
        width: parent.width
        height: item instanceof Item ? (item as Item).implicitHeight : 0
        active: root.joiningRoom
        sourceComponent: Component {
            JoiningRoomPage {
                viewportHeight: root.viewportHeight
                onCancelRequested: root.multiplayer.leave_room()
            }
        }
    }
    Component {
        id: unavailablePage
        PageLayout {
            UiText {
                objectName: "serviceUnavailable"
                width: parent.width
                text: root.unconnectedViews[root.route] || qsTr("服务尚未接入")
                color: DesignTokens.muted
                font.pixelSize: 13
            }
        }
    }
    Component {
        id: launchPage
        HomePage {
            room: root.roomStatus
            backdropTint: root.backdropTint
            instances: root.instances
            selectedIndex: root.selectedIndex
            spacious: root.theme !== "panel"
            viewportHeight: root.viewportHeight
            launchStatus: root.launchStatus
            identityStatus: root.identityStatus
            canStart: root.canStart
            loadingInstances: root.loadingInstances
            viewActive: root.viewActive
            onLaunchRequested: root.launchRequested(root.selectedIndex, {})
            onCancelRequested: root.cancelLaunchRequested()
            onStopRequested: root.stopGameRequested()
            onOpenRequested: route => route === "room" ? root.openToolPage(2, route) : root.openPage(route)
            onIdentitySelected: id => root.identitySelected(id)
        }
    }
    Component {
        id: roomsPage
        RoomsPage {
            service: root.multiplayer
            loginOrigin: root.preferences.multiplayerOrigin || ""
            viewportHeight: DesignTokens.comfortable ? root.viewportHeight : 470
            queryText: root.pageState["rooms.query"] || ""
            inviteText: root.pageState["rooms.invite"] || ""
            pageIndex: root.pageState["rooms.page"] || 0
            onEdited: (key, value) => root.draftEdited("rooms." + key, value)
            onOpenRequested: route => root.openPage(route)
        }
    }
    Component {
        id: friendsPage
        FriendsPage {
            service: root.multiplayer
            loginOrigin: root.preferences.multiplayerOrigin || ""
            viewportHeight: DesignTokens.comfortable ? root.viewportHeight : 470
            queryText: root.pageState["friends.query"] || ""
            selectedId: root.pageState["friends.selected"] || ""
            onNoticeRequested: message => root.noticeRequested(message)
            onEdited: (key, value) => root.draftEdited("friends." + key, value)
            onOpenRequested: route => root.openPage(route)
        }
    }
    Component {
        id: settingsPage
        SettingsPage {
            updateStatus: root.updateService ? root.updateService.status : ({})
            downloadSource: qsTr("%1 优先").arg(qsTr((root.sourceSettings.order || ["BUGG"])[0]))
            theme: root.theme
            languageName: root.languageService ? (root.languageService.options.find(item => item.id === root.preferences.language) || {}).name || root.preferences.language : qsTr("简体中文")
            onThemeRequested: theme => root.themeRequested(theme)
            onNoticeRequested: message => root.noticeRequested(message)
            onOpenRequested: route => root.openPage(route)
        }
    }
    Component {
        id: selectionPage
        InstancesPage {
            instances: root.instances
            selectedIndex: root.selectedIndex
            viewportHeight: DesignTokens.comfortable ? root.viewportHeight : 390
            swipeHintSeen: root.preferences.swipeHintSeen !== false
            onHintShown: {
                if (root.runtime)
                    root.runtime.set_preference("swipeHintSeen", true);
            }
            onOperationRequested: (index, route) => {
                root.selected(index);
                root.openPage(route);
            }
            selectionOnly: true
            queryText: root.pageState["instances.query"] || ""
            onQueryEdited: value => root.draftEdited("instances.query", value)
            onSelected: index => {
                root.selected(index);
                root.goBack();
            }
            onOpenRequested: route => root.openPage(route)
        }
    }
    Component {
        id: instancesPage
        InstancesPage {
            instances: root.instances
            selectedIndex: root.selectedIndex
            viewportHeight: DesignTokens.comfortable ? root.viewportHeight : 390
            swipeHintSeen: root.preferences.swipeHintSeen !== false
            onHintShown: {
                if (root.runtime)
                    root.runtime.set_preference("swipeHintSeen", true);
            }
            onOperationRequested: (index, route) => {
                root.selected(index);
                root.openPage(route);
            }
            queryText: root.pageState["instances.query"] || ""
            onQueryEdited: value => root.draftEdited("instances.query", value)
            onSelected: index => root.selected(index)
            onOpenRequested: route => root.openPage(route)
        }
    }
    Component {
        id: detailsPage
        InstanceDetailsPage {
            instance: root.currentInstance
            onOpenRequested: route => root.openPage(route)
            onNoticeRequested: message => root.noticeRequested(message)
        }
    }
    Component {
        id: filesPage
        InstanceFilesPage {
            snapshot: root.runtime ? root.runtime.content : ({})
            viewportHeight: DesignTokens.comfortable ? root.viewportHeight : 390
            onRefreshRequested: category => {
                if (root.runtime)
                    root.runtime.refresh_content(root.currentInstance.id, category);
            }
            onChangeRequested: (name, action) => {
                if (root.runtime)
                    root.runtime.change_content(root.currentInstance.id, category, name, action);
            }
            onFilesChosen: urls => {
                if (root.runtime)
                    root.runtime.add_content(root.currentInstance.id, category, urls);
            }
            onBrowseRequested: kind => {
                root.draftEdited("content.target", root.currentInstance.id);
                if (root.contentCatalog)
                    root.contentCatalog.browse(kind, "", root.currentInstance);
                root.openPage("catalog");
            }
        }
    }
    Component {
        id: instanceSettingsPage
        InstanceSettingsPage {
            enabled: !root.loadingInstances
            configuration: {
                root.settingsRevision;
                return root.runtime ? root.runtime.instance_settings(root.currentInstance.id) : ({
                        automatic: true,
                        memoryMB: 4096
                    });
            }
            environment: root.environment
            instanceSpecific: true
            onSettingEdited: (key, value) => {
                if (root.runtime)
                    root.runtime.set_game_setting(root.currentInstance.id, key, value);
            }
            onResetRequested: {
                if (root.runtime)
                    root.runtime.reset_instance_settings(root.currentInstance.id);
            }
            onOpenRequested: route => root.openPage(route)
        }
    }
    Component {
        id: gameSettingsPage
        InstanceSettingsPage {
            enabled: !root.loadingInstances
            configuration: {
                root.settingsRevision;
                return root.runtime ? root.runtime.instance_settings("") : ({});
            }
            environment: root.environment
            onSettingEdited: (key, value) => {
                if (root.runtime)
                    root.runtime.set_game_setting("", key, value);
            }
            onOpenRequested: route => root.openPage(route)
        }
    }
    Component {
        id: languagePage
        LanguagePage {
            enabled: !root.loadingInstances
            service: root.languageService
            selection: root.preferences.language
            contentTranslation: root.preferences.contentTranslation !== false
            onContentTranslationEdited: value => {
                if (root.runtime)
                    root.runtime.set_preference("contentTranslation", value);
            }
            onChosen: value => {
                if (root.runtime)
                    root.runtime.set_preference("language", value);
            }
        }
    }
    Component {
        id: downloadsPage
        DownloadsPage {
            enabled: !root.loadingInstances
            concurrency: root.preferences.concurrency
            sourceSummary: qsTr("%1 优先").arg(qsTr((root.sourceSettings.order || ["BUGG"])[0]))
            onConcurrencyEdited: value => {
                if (root.runtime)
                    root.runtime.set_preference("concurrency", value);
            }
            onOpenRequested: route => root.openPage(route)
        }
    }
    Component {
        id: multiplayerSettingsPage
        MultiplayerSettingsPage {
            enabled: !root.loadingInstances
            loginOrigin: root.preferences.multiplayerOrigin || ""
            customService: !!loginOrigin || root.pageState["multiplayer.custom"] === true
            onCustomServiceEdited: value => {
                root.draftEdited("multiplayer.custom", value);
                if (!value && root.runtime)
                    root.runtime.set_preference("multiplayerOrigin", "");
            }
            onOriginEdited: value => {
                if (root.runtime)
                    root.runtime.set_preference("multiplayerOrigin", value);
            }
        }
    }
    Component {
        id: generalPage
        GeneralPage {
            enabled: !root.loadingInstances
            afterLaunch: root.preferences.afterLaunch
            startCollapsed: root.preferences.startCollapsed || false
            showOverlayInFullscreen: root.preferences.showOverlayInFullscreen || false
            onShowOverlayInFullscreenEdited: value => {
                if (root.runtime)
                    root.runtime.set_preference("showOverlayInFullscreen", value);
            }
            onStartCollapsedEdited: value => {
                if (root.runtime)
                    root.runtime.set_preference("startCollapsed", value);
            }
            onAfterLaunchEdited: value => {
                if (root.runtime)
                    root.runtime.set_preference("afterLaunch", value);
            }
        }
    }
    Component {
        id: deletePage
        DeleteInstancePage {
            instanceName: root.currentInstance.name
            onDeleteRequested: permanent => {
                if (root.runtime && root.runtime.remove_instance(root.currentInstance.id, permanent)) {
                    root.goHome();
                    root.openPage("instances");
                }
            }
        }
    }
    Component {
        id: tasksPage
        TasksPage {
            viewportHeight: DesignTokens.comfortable ? root.viewportHeight : 390
            tasks: root.tasks
            onCancelRequested: id => {
                if (root.runtime)
                    root.runtime.cancel_task(id);
            }
            onRetryRequested: id => {
                if (root.runtime)
                    root.runtime.retry_task(id);
            }
            onClearRequested: {
                if (root.runtime)
                    root.runtime.clear_task_history();
            }
            onDependencyChoiceRequested: (id, choice) => {
                if (root.runtime)
                    root.runtime.resolve_dependencies(id, choice);
            }
        }
    }
    Component {
        id: taskFilesPage
        TaskFilesPage {
            onNoticeRequested: message => root.noticeRequested(message)
        }
    }
    Component {
        id: catalogPage
        CatalogPage {
            session: root.contentCatalog
            viewportHeight: DesignTokens.comfortable ? root.viewportHeight : 510
            instances: root.instances
            targetId: root.pageState["content.target"] === undefined ? root.currentInstance.id || "" : root.pageState["content.target"]
            filtersExpanded: root.pageState["content.filtersExpanded"] !== false
            onFilterExpansionRequested: expanded => root.draftEdited("content.filtersExpanded", expanded)
            Component.onCompleted: Qt.callLater(root.catalogRequested)
            onTargetChosen: id => root.draftEdited("content.target", id)
            onProjectRequested: id => {
                if (root.contentStatus.loading)
                    return;
                if (root.contentStatus.kind !== "modpack" && !root.pageState["content.target"] && root.currentInstance.id)
                    root.draftEdited("content.target", root.currentInstance.id);
                if (root.contentCatalog)
                    root.contentCatalog.open_project(id, root.instances.find(item => item.id === (root.pageState["content.target"] || root.currentInstance.id)) || {});
                root.openPage("content");
            }
            onOpenRequested: route => root.openPage(route)
        }
    }
    Component {
        id: contentPage
        ContentDetailsPage {
            session: root.contentCatalog
            viewportHeight: DesignTokens.comfortable ? root.viewportHeight : 510
            instances: root.instances
            targetId: root.pageState["content.target"] || root.currentInstance.id || ""
            inspection: root.runtime ? root.runtime.content_installation : ({})
            onTargetChosen: id => {
                root.draftEdited("content.target", id);
                if (root.contentCatalog)
                    root.contentCatalog.select_target(root.instances.find(item => item.id === id) || {});
            }
            onInspectRequested: (id, plan) => {
                if (root.runtime)
                    root.runtime.inspect_content_install(id, plan);
            }
            onInstallRequested: specification => {
                if (root.runtime) {
                    root.runtime.install(specification);
                    root.openPage("tasks");
                }
            }
            onSetupRequested: (game, loader) => {
                root.openPage("install");
                root.draftEdited("content.setup", root.contentStatus.plan || {});
                if (root.contentStatus.kind === "shader" || (root.contentStatus.plan || {}).kind === "shader")
                    root.draftEdited("content.setupTarget", root.contentStatus.target || {});
                root.contentSetupRequested(game, loader);
            }
        }
    }
    Component {
        id: installPage
        GameInstallPage {
            existingTarget: root.pageState["content.setupTarget"] || ({})
            contentTitle: (root.pageState["content.setup"] || {}).files ? (root.contentStatus.project || {}).title || "" : ""
            onContentRequested: {
                root.draftEdited("content.target", "");
                if (root.contentCatalog)
                    root.contentCatalog.browse("modpack");
                root.openPage("catalog");
            }
            catalog: root.installCatalog
            onCatalogRequested: root.catalogRequested()
            onRefreshRequested: root.catalogRefreshRequested()
            onGameSelected: version => root.gameVersionSelected(version)
            onLoaderSelected: kind => root.loaderSelected(kind)
            onLoaderVersionSelected: version => root.loaderVersionSelected(version)
            onLoaderRetryRequested: root.loaderRetryRequested()
            onNameEdited: name => root.instanceNameEdited(name)
            onNoticeRequested: message => root.noticeRequested(message)
            onInstallRequested: instanceName => root.beginInstall(instanceName)
        }
    }
    Component {
        id: importPage
        PackImportPage {
            preview: root.runtime ? root.runtime.pack_preview : ({})
            onInstallRequested: name => {
                if (root.runtime) {
                    root.runtime.import_pack(name);
                    root.openPage("tasks");
                }
            }
        }
    }
    Component {
        id: exportPage
        PackExportPage {
            instanceName: root.currentInstance.name
            onExportRequested: (url, compact, saves) => {
                if (root.runtime) {
                    root.runtime.export_pack(root.currentInstance.id, url, compact, saves);
                    root.openPage("tasks");
                }
            }
        }
    }
    Component {
        id: conflictPage
        InstanceConflictPage {
            instanceName: root.pendingInstanceName
            onNoticeRequested: message => root.noticeRequested(message)
        }
    }
    Component {
        id: createRoomPage
        CreateRoomPage {
            service: root.multiplayer
            instances: root.instances
            selectedIndex: root.selectedIndex
            draft: root.pageState["rooms.create"] || ({})
            instanceLocked: root.identityLocked
            enabled: root.launchStatus.state !== "preparing" && root.launchStatus.state !== "stopping"
            onSelected: index => root.selected(index)
            onEdited: (key, value) => root.draftEdited("rooms.create", Object.assign({}, draft, {
                    [key]: value
                }))
            onOpenRequested: route => root.openPage(route)
            onCreateRequested: (title, options) => {
                if (root.multiplayer)
                    root.multiplayer.create_room(title, root.currentInstance.directory || "", root.identityStatus.name || "", Object.assign({}, options, {
                        instanceId: root.currentInstance.id,
                        game: {
                            version: root.currentInstance.version,
                            loader: root.currentInstance.loader.toLowerCase(),
                            loader_version: root.currentInstance.loaderVersion || ""
                        }
                    }));
            }
            Component.onDestruction: {
                if (service && service.status.roomBusy)
                    service.leave_room();
                else if (service && !service.status.room)
                    service.cancel_invites();
            }
        }
    }
    Connections {
        target: root.multiplayer || null
        function onChanged() {
            if (root.multiplayer && root.multiplayer.status.state !== "ready") {
                if (["room", "roomSettings", "sync", "inviteFriends"].includes(root.route)) {
                    root.route = "";
                    root.history = [];
                }
                if (root.toolIndex === 3)
                    root.navigateRequested(2);
            }
        }
        function onRoom_joined() {
            if (["createRoom", "joinRoom"].includes(root.route))
                root.goBack();
            root.openToolPage(2, "room");
            if (root.roomStatus.role !== "host")
                root.multiplayer.select_room_instance(root.currentInstance.id || "");
        }
        function onPreparation_required() {
            root.draftEdited("rooms.view." + (root.roomStatus.id || ""), "files");
        }
        function onLaunch_requested(instanceId, contributions) {
            const index = root.instances.findIndex(item => item.id === instanceId);
            if (index >= 0) {
                root.launchRequested(index, contributions);
                if (contributions.lanServer && root.identityStatus.kind === "offline")
                    root.noticeRequested(qsTr("打开多人游戏，选择“【BUGG联机】”房间即可加入。"));
            } else
                root.noticeRequested(qsTr("房间使用的游戏已不存在"));
        }
        function onHost_required() {
            const destination = root.multiplayer.status.room ? "room" : "createRoom";
            root.openToolPage(2, destination);
        }
        function onRoom_command_completed(operation) {
            if (operation === "configure" && root.route === "roomSettings")
                root.goBack();
        }
        function onRoom_left() {
            if (["room", "roomSettings", "sync", "inviteFriends"].includes(root.route)) {
                root.route = "";
                root.history = [];
            }
        }
        function onSocial_completed(operation, target) {
            if (operation === "request" && root.route === "addFriend") {
                root.goBack();
                root.noticeRequested(qsTr("好友申请已发送"));
            }
        }
    }
    Component {
        id: roomPage
        RoomLobbyPage {
            service: root.multiplayer
            runtime: root.runtime
            instances: root.instances
            tasks: root.tasks
            launchStatus: root.launchStatus
            viewportHeight: DesignTokens.comfortable ? root.viewportHeight : 360
            chatDraft: root.pageState["rooms.chat." + (root.roomStatus.id || "")] || ""
            activeView: root.pageState["rooms.view." + (root.roomStatus.id || "")] || "chat"
            onViewEdited: value => root.draftEdited("rooms.view." + (root.roomStatus.id || ""), value)
            onChatEdited: value => root.draftEdited("rooms.chat." + (root.roomStatus.id || ""), value)
            onOpenRequested: route => root.openPage(route)
            onLaunchRequested: root.multiplayer.launch_room()
            onCancelRequested: root.cancelLaunchRequested()
            onNoticeRequested: message => root.noticeRequested(message)
        }
    }
    Component {
        id: joinRoomPage
        JoinRoomPage {
            service: root.multiplayer
            inviteText: root.pageState["rooms.invite"] || ""
            onEdited: value => root.draftEdited("rooms.invite", value)
            Component.onDestruction: {
                if (service && service.status.roomBusy)
                    service.leave_room();
            }
        }
    }
    Component {
        id: roomSettingsPage
        RoomSettingsPage {
            service: root.multiplayer
            draft: root.pageState["rooms.settings." + (room.id || "")] || ({})
            onEdited: (key, value) => root.draftEdited("rooms.settings." + (room.id || ""), Object.assign({}, draft, {
                    [key]: value
                }))
        }
    }
    Component {
        id: notificationsPage
        FriendsPage {
            service: root.multiplayer
            notificationMode: true
            notificationCategory: root.pageState["friends.notificationCategory"] || "rooms"
            onNoticeRequested: message => root.noticeRequested(message)
        }
    }
    Component {
        id: friendConversationPage
        FriendsPage {
            service: root.multiplayer
            viewportHeight: DesignTokens.comfortable ? root.viewportHeight : 340
            detailMode: true
            selectedId: root.pageState["friends.selected"] || ""
            onNoticeRequested: message => root.noticeRequested(message)
        }
    }
    Component {
        id: inviteFriendsPage
        FriendsPage {
            service: root.multiplayer
            viewportHeight: DesignTokens.comfortable ? root.viewportHeight : 420
            inviteMode: true
            queryText: root.pageState["friends.query"] || ""
            onEdited: (key, value) => root.draftEdited("friends." + key, value)
            onNoticeRequested: message => root.noticeRequested(message)
        }
    }
    Component {
        id: syncPage
        RoomSyncPage {
            instanceLocked: root.identityLocked
            service: root.multiplayer
            runtime: root.runtime
            tasks: root.tasks
            instances: root.instances
            onOpenRequested: route => root.goBack()
            onNoticeRequested: message => root.noticeRequested(message)
        }
    }
    Component {
        id: nodesPage
        NodesPage {
            service: root.multiplayer
            onNoticeRequested: message => root.noticeRequested(message)
        }
    }
    Component {
        id: accountPage
        AccountPage {
            identityStatus: root.identityStatus
            locked: root.identityLocked
            onMicrosoftLogoutRequested: root.microsoftLogoutRequested()
            onOpenRequested: route => root.openPage(route)
            onNoticeRequested: message => root.noticeRequested(message)
        }
    }
    Component {
        id: javaPage
        JavaPage {
            readonly property string targetInstance: root.history[root.history.length - 1] === "instanceSettings" ? root.currentInstance.id || "" : ""
            viewportHeight: DesignTokens.comfortable ? root.viewportHeight : 390
            javaEntries: root.environment.javaEntries || []
            selection: {
                root.settingsRevision;
                return root.runtime ? root.runtime.instance_settings(targetInstance).javaPath || "" : "";
            }
            onSelected: path => {
                if (root.runtime)
                    root.runtime.set_game_setting(targetInstance, "javaPath", path);
            }
            onRefreshRequested: {
                if (root.runtime)
                    root.runtime.refresh_environment();
            }
        }
    }
    Component {
        id: sourcesPage
        SourcesPage {
            sourceSettings: root.sourceSettings
            onMoveRequested: (index, delta) => root.sourceMoveRequested(index, delta)
            onBaseUrlRequested: value => root.sourceBaseUrlRequested(value)
        }
    }
    Component {
        id: storagePage
        StoragePage {
            gameRoot: root.runtime ? root.runtime.game_root : ".minecraft"
            cacheRoot: root.runtime ? root.runtime.cache_root : ""
            onCacheSelected: path => {
                if (root.runtime)
                    root.runtime.select_cache_root(path);
            }
            onDirectorySelected: path => {
                if (root.runtime)
                    root.runtime.select_game_root(path);
            }
            onOpenRequested: {
                if (root.runtime)
                    root.runtime.open_directory("");
            }
            onNoticeRequested: message => root.noticeRequested(message)
        }
    }
    Component {
        id: feedbackPage
        FeedbackPage {
            service: root.multiplayer
            onNoticeRequested: message => root.noticeRequested(message)
        }
    }
    Component {
        id: updatePage
        UpdatePage {
            service: root.updateService
            onNoticeRequested: message => root.noticeRequested(message)
        }
    }
    Component {
        id: addFriendPage
        AddFriendPage {
            service: root.multiplayer
            identifier: root.pageState["friends.identifier"] || ""
            onEdited: value => root.draftEdited("friends.identifier", value)
            onNoticeRequested: message => root.noticeRequested(message)
            Component.onDestruction: {
                if (service)
                    service.cancel_lookup();
            }
        }
    }
    Component {
        id: appearancePage
        AppearancePage {
            theme: root.theme
            backgrounds: root.preferences.backgrounds || root.pageState["appearance.backgrounds"] || []
            onThemeRequested: theme => root.themeRequested(theme)
            onBackgroundsEdited: urls => root.draftEdited("appearance.backgrounds", urls)
        }
    }
    Component {
        id: identityPage
        GameIdentityPage {
            viewportHeight: root.viewportHeight
            identityStatus: root.identityStatus
            locked: root.identityLocked
            onOpenRequested: route => {
                if (route === "deviceAuth" && root.identityStatus.microsoftName)
                    root.microsoftAuthRequested();
                else
                    root.openPage(route);
            }
            onNoticeRequested: message => root.noticeRequested(message)
        }
    }
    Component {
        id: deviceAuthPage
        DeviceAuthPage {
            viewportHeight: root.viewportHeight
            identityStatus: root.identityStatus
            locked: root.identityLocked
            previewEnabled: root.authPreviewEnabled
            onBeginRequested: root.microsoftAuthRequested()
            onCompleteRequested: root.microsoftCompletionRequested()
            onCancelRequested: root.microsoftCancelRequested()
        }
    }
    Component {
        id: skinPage
        SkinPage {
            onNoticeRequested: message => root.noticeRequested(message)
        }
    }
    Component {
        id: logsPage
        LogsPage {
            viewportHeight: DesignTokens.comfortable ? root.viewportHeight : 510
            runtime: root.runtime
            onNoticeRequested: message => root.noticeRequested(message)
        }
    }
    Component {
        id: buggLoginPage
        BuggLoginPage {
            service: root.multiplayer
        }
    }
    Component {
        id: offlineIdentityPage
        OfflineIdentityPage {
            viewportHeight: root.viewportHeight
            playerName: root.pageState["identity.offlineName"] === undefined ? root.identityStatus.offlineName || "" : root.pageState["identity.offlineName"]
            locked: root.identityLocked
            onNameEdited: value => root.draftEdited("identity.offlineName", value)
            onSaveRequested: name => root.offlineIdentityRequested(name)
        }
    }
}
