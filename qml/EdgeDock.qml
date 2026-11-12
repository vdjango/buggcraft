import QtQuick

Item {
    id: root

    required property Window targetWindow
    required property var desktopEnvironment
    property real expandedWidth: 410
    property real expandedHeight: 76
    property bool autoFoldEnabled: true
    property bool dockingEnabled: true
    property bool pointerInside: false
    property bool folded: false
    property real foldReveal: 1
    property bool instantReveal: false
    readonly property int snapDistance: 28
    readonly property bool dragging: releasePoll.running
    readonly property bool foldAnimating: foldMotion.running
    readonly property bool compact: folded || foldAnimating || instantReveal
    readonly property int foldEdge: attachment & Qt.TopEdge ? Qt.TopEdge : attachment & Qt.LeftEdge ? Qt.LeftEdge : Qt.RightEdge
    readonly property bool verticalHandle: foldEdge !== Qt.TopEdge
    readonly property real foldedWidth: verticalHandle ? 44 : 88
    readonly property real foldedHeight: verticalHandle ? 88 : 40
    readonly property real layoutReveal: Math.max(0, Math.min(1.02, foldReveal))
    readonly property real displayWidth: foldedWidth + (expandedWidth - foldedWidth) * layoutReveal
    readonly property real displayHeight: foldedHeight + (expandedHeight - foldedHeight) * layoutReveal
    property int attachment: 0
    property rect workArea: Qt.rect(0, 0, 0, 0)
    property point restingPosition: Qt.point(0, 0)
    property bool ready: false
    property bool adjusting: false
    property real destinationX: 0
    property real destinationY: 0

    // 当前屏幕工作区内计算最近可吸附边；底部保留给任务栏。
    function nearestEdge() {
        refreshWorkArea();
        const distances = [Math.abs(targetWindow.x - workArea.x), Math.abs(workArea.x + workArea.width - targetWindow.x - targetWindow.width), Math.abs(targetWindow.y - workArea.y)];
        return [Qt.LeftEdge, Qt.RightEdge, Qt.TopEdge][distances.indexOf(Math.min(...distances))];
    }
    function dockNearest(edge, immediate = false) {
        if (!ready || dragging || workArea.width <= 0)
            return false;
        attachment = edge || nearestEdge();
        restingPosition = Qt.point(targetWindow.x, targetWindow.y);
        if (immediate) {
            foldAfterDock.stop();
            autoFold.stop();
            settleAnimation.stop();
            instantReveal = true;
            foldMotion.stop();
            folded = true;
            foldReveal = 0;
            reposition(false);
            instantReveal = false;
            return true;
        }
        reposition(true);
        foldAfterDock.restart();
        return true;
    }
    property Timer foldAfterDock: Timer {
        interval: 270
        onTriggered: root.setFolded(true)
    }
    function setFolded(value) {
        if (!value)
            foldAfterDock.stop();
        if (value && (!dockingEnabled || !attachment || dragging))
            return false;
        autoFold.stop();
        folded = value;
        foldReveal = value ? 0 : 1;
        if (!value)
            updateAutoFold();
        return true;
    }

    function toggleFold() {
        return setFolded(!folded);
    }

    function setPointerInside(inside) {
        pointerInside = inside;
        updateAutoFold();
    }

    function updateAutoFold() {
        if (dockingEnabled && autoFoldEnabled && attachment && !folded && !dragging && !pointerInside) {
            if (!autoFold.running)
                autoFold.start();
        } else {
            autoFold.stop();
        }
    }

    function refreshWorkArea() {
        const area = desktopEnvironment.available_geometry(targetWindow);
        if (area.width > 0 && area.height > 0)
            workArea = area;
    }

    function beginMove() {
        foldAfterDock.stop();
        if (!dockingEnabled || dragging)
            return;
        autoFold.stop();
        settleAnimation.stop();
        instantReveal = true;
        foldMotion.stop();
        folded = false;
        foldReveal = 1;
        reposition(false);
        instantReveal = false;
        attachment = 0;
        releasePoll.start();
        targetWindow.startSystemMove();
    }

    function finishMove() {
        releasePoll.stop();
        if (!dockingEnabled)
            return;
        refreshWorkArea();
        if (workArea.width <= 0 || workArea.height <= 0)
            return;
        restingPosition = Qt.point(targetWindow.x, targetWindow.y);
        let edges = 0;
        const leftDistance = Math.abs(targetWindow.x - workArea.x);
        const rightDistance = Math.abs(targetWindow.x + targetWindow.width - workArea.x - workArea.width);
        if (Math.min(leftDistance, rightDistance) <= snapDistance)
            edges |= leftDistance <= rightDistance ? Qt.LeftEdge : Qt.RightEdge;
        if (Math.abs(targetWindow.y - workArea.y) <= snapDistance)
            edges |= Qt.TopEdge;
        attachment = edges;
        reposition(true);
        pointerInside = desktopEnvironment.pointer_inside(targetWindow);
        updateAutoFold();
    }

    function reposition(animated) {
        if (!dockingEnabled || !ready || dragging || adjusting || workArea.width <= 0 || workArea.height <= 0)
            return;
        adjusting = true;
        settleAnimation.stop();
        const left = workArea.x;
        const top = workArea.y;
        const right = Math.max(left, left + workArea.width - targetWindow.width);
        const bottom = Math.max(top, top + workArea.height - targetWindow.height);
        const amount = 1 - Math.max(0, Math.min(1, foldReveal));
        const shiftX = foldEdge === Qt.TopEdge ? (expandedWidth - targetWindow.width) / 2 : 0;
        const shiftY = verticalHandle ? (76 - foldedHeight) * amount / 2 : 0;
        destinationX = attachment & Qt.LeftEdge ? left : attachment & Qt.RightEdge ? right : Math.max(left, Math.min(restingPosition.x + shiftX, right));
        destinationY = attachment & Qt.TopEdge ? top : Math.max(top, Math.min(restingPosition.y + shiftY, bottom));
        if (animated) {
            settleAnimation.restart();
        } else {
            targetWindow.x = destinationX;
            targetWindow.y = destinationY;
        }
        adjusting = false;
    }

    function refreshPlacement() {
        if (!dockingEnabled || !ready || dragging || adjusting)
            return;
        refreshWorkArea();
        reposition(false);
    }

    visible: false
    onAutoFoldEnabledChanged: updateAutoFold()
    onDockingEnabledChanged: {
        if (!dockingEnabled) {
            autoFold.stop();
            releasePoll.stop();
            settleAnimation.stop();
            foldMotion.stop();
            instantReveal = true;
            folded = false;
            foldReveal = 1;
            instantReveal = false;
        }
    }

    Behavior on foldReveal {
        enabled: root.ready && !root.instantReveal
        NumberAnimation {
            id: foldMotion
            duration: root.folded ? 200 : 260
            easing.type: root.folded ? Easing.OutCubic : Easing.OutBack
            easing.overshoot: 0.6
        }
    }

    property Timer autoFold: Timer {
        interval: 450
        onTriggered: root.setFolded(true)
    }

    // 原生窗口移动/缩放可能没有发送 HoverHandler 离开事件；只校正读数，复用原折叠入口。
    property Timer pointerPoll: Timer {
        interval: 120
        repeat: true
        running: root.ready && root.targetWindow.visible && root.dockingEnabled && root.autoFoldEnabled && !!root.attachment && !root.folded && !root.dragging
        onTriggered: {
            const inside = root.desktopEnvironment.pointer_inside(root.targetWindow);
            root.setPointerInside(inside);
        }
    }

    property Timer releasePoll: Timer {
        interval: 16
        repeat: true
        onTriggered: {
            if (!root.desktopEnvironment.left_button_pressed())
                root.finishMove();
        }
    }

    property ParallelAnimation settleAnimation: ParallelAnimation {
        NumberAnimation {
            target: root.targetWindow
            property: "x"
            to: root.destinationX
            duration: 260
            easing.type: Easing.OutQuint
        }
        NumberAnimation {
            target: root.targetWindow
            property: "y"
            to: root.destinationY
            duration: 260
            easing.type: Easing.OutQuint
        }
    }

    property Connections windowChanges: Connections {
        target: root.targetWindow
        function onWidthChanged() {
            root.reposition(false);
        }
        function onHeightChanged() {
            root.reposition(false);
        }
        function onScreenChanged() {
            Qt.callLater(root.refreshPlacement);
        }
    }

    property Connections desktopChanges: Connections {
        target: root.desktopEnvironment
        function onAvailable_geometry_changed() {
            Qt.callLater(root.refreshPlacement);
        }
    }

    Component.onCompleted: Qt.callLater(function () {
        root.restingPosition = Qt.point(root.targetWindow.x, root.targetWindow.y);
        root.refreshWorkArea();
        root.ready = true;
        root.reposition(false);
    })
}
