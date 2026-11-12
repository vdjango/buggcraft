import QtQuick
import Bugg.DesignSystem

Item {
    id: root
    required property var dock
    property int activeTool: -1
    property real pageMode: 0
    property real contentReveal: 0
    property real contentHeight: 0
    property real contentMaximumWidth: 560
    property string notice: ""
    property string title: ""
    property string caption: ""
    property color captionColor: DesignTokens.muted
    property bool canGoBack: false
    property bool roomHeader: false
    property bool roomManager: false
    property bool friendsVisible: false
    property bool showPageHeader: true
    property bool fixedViewport: false
    readonly property bool showingSubpage: canGoBack && activeTool >= 0
    property bool immersiveHome: false
    property bool backdropAllowed: true
    property var backgrounds: []
    property bool backgroundActive: true
    property var activity: ({
            active: false,
            progress: -1
        })
    property real preferredPageHeight: 600
    readonly property real pageExtent: Math.min(preferredPageHeight, Math.max(400, dock.workArea.height - 30))
    readonly property real noticeExtent: notice.length ? noticeBanner.implicitHeight + 20 : 0
    readonly property real requestedHeight: (76 + (activeTool >= 0 ? contentHeight + noticeExtent : 0)) * (1 - pageMode) + pageExtent * pageMode
    readonly property alias contentHost: page.contentHost
    readonly property alias backdropColor: frame.backdropColor
    readonly property real viewportHeight: page.viewportHeight
    readonly property real bodyReveal: Math.max(0, Math.min(1, (dock.foldReveal - 0.38) / 0.62))
    signal navigateRequested(int index)
    signal tasksRequested
    signal backRequested
    signal homeRequested
    signal headerActionRequested
    signal collapseRequested
    signal closeRequested
    function resetScroll() {
        page.resetScroll();
    }
    HoverHandler {
        onHoveredChanged: root.dock.setPointerInside(hovered)
    }
    WindowFrame {
        id: frame
        anchors.fill: parent
        radius: 19 - root.pageMode * 7
        color: root.immersiveHome ? DesignTokens.sceneBase : root.pageMode > 0.5 ? DesignTokens.elevated : DesignTokens.background
        backdropSource: DesignTokens.homeBackdrop
        backdropSources: root.backgrounds.length ? root.backgrounds : DesignTokens.homeBackdrops
        backdropShade: root.backgrounds.length > 0
        backdropActive: root.backgroundActive
        backdropOpacity: root.immersiveHome ? 1 : 0
        // 收起/贴边时立即去掉图片，不能把整张背景压缩成小条。
        backdropVisible: root.backdropAllowed && !root.dock.compact && root.activeTool >= 0 && root.pageMode > 0.5
    }
    Item {
        id: body
        width: root.dock.expandedWidth
        height: root.height
        x: root.dock.foldEdge === Qt.TopEdge ? (parent.width - width) / 2 : root.dock.foldEdge === Qt.RightEdge ? parent.width - width : 0
        opacity: root.bodyReveal
        enabled: !root.dock.folded && root.dock.foldReveal > 0.85
        visible: opacity > 0
        DragHandler {
            target: null
            enabled: !root.dock.dragging
            grabPermissions: PointerHandler.CanTakeOverFromItems | PointerHandler.ApprovesTakeOverByAnything
            onActiveChanged: if (active)
                root.dock.beginMove()
        }
        ClassicShell {
            id: page
            x: 8
            y: 5 + root.pageMode * 72
            width: parent.width - 16
            height: Math.max(0, body.height - 16 - root.pageMode * (72 + root.noticeExtent))
            pageMode: root.pageMode
            contentReveal: root.contentReveal
            contentHeight: root.contentHeight
            contentMaximumWidth: root.contentMaximumWidth
            title: root.title
            caption: root.caption
            canGoBack: root.canGoBack
            showHeader: !root.canGoBack && root.showPageHeader
            fixedViewport: root.fixedViewport
            onBackRequested: root.backRequested()
        }
        WindowControls {
            id: pageWindowControls
            objectName: "pageWindowControls"
            x: parent.width - width - 28
            y: root.showingSubpage ? contextHeader.y + (contextHeader.height - height) / 2 : toolbar.y + (toolbar.height - height) / 2
            opacity: root.showingSubpage ? 1 : root.pageMode
            visible: opacity > 0
            enabled: root.showingSubpage || root.pageMode > 0.5
            showDivider: false
            showCollapse: root.pageMode > 0.5
            closeIcon: root.roomHeader ? "arrow" : "close"
            closeName: root.roomHeader ? qsTr("离开房间并返回") : qsTr("关闭")
            onCollapseRequested: root.collapseRequested()
            onCloseRequested: root.closeRequested()
        }
        ToolBar {
            id: toolbar
            objectName: "floatingToolBar"
            x: 8
            y: 5 + root.pageMode * 8
            width: 394 + root.pageMode * (parent.width - 506)
            height: 60
            dock: root.dock
            activeTool: root.activeTool
            pageMode: root.pageMode
            showWindowControls: root.pageMode < 0.5
            activity: root.activity
            friendsVisible: root.friendsVisible
            opacity: root.showingSubpage ? 0 : 1
            visible: opacity > 0
            enabled: !root.showingSubpage
            Behavior on opacity {
                NumberAnimation {
                    duration: 140
                    easing.type: Easing.OutCubic
                }
            }
            onNavigateRequested: index => root.navigateRequested(index)
            onTasksRequested: root.tasksRequested()
            onCloseRequested: root.closeRequested()
        }
        SubpageHeader {
            id: contextHeader
            objectName: "contextHeader"
            x: 28
            // 顶栏上下边界为窗口内沿和分隔线；两种尺寸共用同一条中心线。
            y: (root.roomHeader ? 7 : 13) + root.pageMode * 6
            width: pageWindowControls.x - x - 20
            height: root.roomHeader ? 56 : 44
            title: root.title
            caption: root.caption
            wrapCaption: root.roomHeader && root.pageMode > 0.5
            captionColor: root.captionColor
            homeAsBack: root.roomHeader
            worldIcon: root.roomHeader && root.pageMode > 0.5
            actionIcon: root.roomHeader && root.roomManager ? "settings" : ""
            actionName: qsTr("房间设置")
            onActionRequested: root.headerActionRequested()
            titleSize: root.pageMode > 0.5 ? 18 : 16
            opacity: root.showingSubpage ? 1 : 0
            visible: opacity > 0
            enabled: root.showingSubpage
            Behavior on opacity {
                NumberAnimation {
                    duration: 140
                    easing.type: Easing.OutCubic
                }
            }
            onBackRequested: root.backRequested()
            onHomeRequested: root.homeRequested()
        }
        Divider {
            objectName: "headerDivider"
            x: 28
            y: 65 + root.pageMode * 12
            width: parent.width - 56
            opacity: root.immersiveHome ? 0 : root.pageMode + (1 - root.pageMode) * (root.activeTool >= 0 ? 1 : 0)
        }
        NoticeBanner {
            id: noticeBanner
            x: root.pageMode > 0.5 ? (parent.width - width) / 2 : 28
            y: root.pageMode > 0.5 ? body.height - root.noticeExtent - 12 : 65 + root.contentHeight
            width: root.pageMode > 0.5 ? Math.min(560, parent.width - 96) : parent.width - 56
            text: root.notice
        }
    }
    DockHandle {
        x: 8
        y: 5
        width: parent.width - 16
        height: parent.height - 16
        edge: root.dock.foldEdge
        opacity: Math.max(0, Math.min(1, (0.6 - root.dock.foldReveal) / 0.6))
        visible: opacity > 0
        enabled: root.dock.folded
        onClicked: root.dock.toggleFold()
        onMoveRequested: root.dock.beginMove()
    }
}
