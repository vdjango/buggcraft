import QtQuick
import Qt.labs.platform as Platform

QtObject {
    id: root
    required property Window targetWindow
    required property var dock
    property string theme: "small"
    property bool collapsed: false
    property real layoutProgress: theme !== "panel" && !collapsed ? 1 : 0
    readonly property real pageWidth: theme === "small" ? 800 : theme === "large" ? 1180 : 960
    readonly property real pageHeight: theme === "small" ? 520 : theme === "large" ? 740 : 600
    readonly property bool switching: layoutMotion.running
    property int collapseEdge: 0
    property bool edgeCollapsing: false
    property var desktopEnvironment: null
    property bool showOverlayInFullscreen: false
    property bool closing: false
    property bool fullscreenSuppressed: false
    readonly property bool trayAvailable: trayIcon.available
    // Native platform tray; no second window, task session or Widgets fallback.
    property Platform.SystemTrayIcon trayIcon: Platform.SystemTrayIcon {
        objectName: "panelTrayIcon"
        visible: root.theme === "panel" && available && !root.closing
        icon.source: Qt.resolvedUrl("assets/bugg-tray.png")
        tooltip: "Bugg"
        onActivated: reason => {
            if (reason === Platform.SystemTrayIcon.Trigger || reason === Platform.SystemTrayIcon.DoubleClick)
                root.restoreFromTray();
        }
        menu: Platform.Menu {
            Platform.MenuItem {
                text: qsTr("打开悬浮面板")
                onTriggered: root.restoreFromTray()
            }
            Platform.MenuItem {
                text: qsTr("切换为紧凑窗口")
                onTriggered: {
                    root.selectTheme("small");
                    root.restoreFromTray();
                }
            }
            Platform.MenuSeparator {}
            Platform.MenuItem {
                text: qsTr("退出 Bugg")
                onTriggered: root.targetWindow.close()
            }
        }
    }
    function restoreFromTray() {
        if (closing)
            return;
        fullscreenSuppressed = false;
        selectTheme(theme);
        targetWindow.showNormal();
        targetWindow.raise();
        targetWindow.requestActivate();
    }
    // Only folded entries are suppressed. Never reopen a user-hidden/minimized window.
    function updateFullscreenSuppression() {
        const suppress = !closing && !showOverlayInFullscreen && dock.folded && targetWindow.visibility !== Window.Minimized && desktopEnvironment && desktopEnvironment.fullscreen_foreground(targetWindow);
        if (suppress && !fullscreenSuppressed && targetWindow.visible) {
            fullscreenSuppressed = true;
            targetWindow.hide();
        } else if (!suppress && fullscreenSuppressed) {
            fullscreenSuppressed = false;
            if (!closing)
                targetWindow.showNormal();
        }
    }
    property Timer fullscreenPoll: Timer {
        interval: 500
        repeat: true
        running: !root.closing && (root.fullscreenSuppressed || (!root.showOverlayInFullscreen && root.dock.folded && root.targetWindow.visible && root.targetWindow.visibility !== Window.Minimized))
        triggeredOnStart: true
        onTriggered: root.updateFullscreenSuppression()
    }
    onShowOverlayInFullscreenChanged: updateFullscreenSuppression()
    function selectTheme(value) {
        if (!["panel", "small", "classic", "large"].includes(value))
            return false;
        edgeCollapsing = false;
        collapsed = false;
        dock.setFolded(false);
        theme = value;
        return true;
    }
    // Commit one final dock state without displaying an intermediate panel.
    function collapseToEdge(edge = 0) {
        if (edgeCollapsing || dock.folded)
            return;
        collapseEdge = edge || dock.nearestEdge();
        edgeCollapsing = true;
        collapsed = true;
        dock.dockNearest(collapseEdge, true);
        edgeCollapsing = false;
    }
    Behavior on layoutProgress {
        enabled: !root.edgeCollapsing
        NumberAnimation {
            id: layoutMotion
            duration: root.edgeCollapsing ? 200 : 260
            easing.type: Easing.InOutCubic
        }
    }
}
