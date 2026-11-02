import QtQuick
import QtQuick.Controls.Basic

ListView {
    id: root
    property bool hasMore: false
    property bool loading: false
    property bool loadFailed: false
    property bool appendPending: false
    property real previousY: 0
    property int previousCount: 0
    property real appendStarted: 0
    signal moreRequested()

    function scheduleCheck() { check.restart() }
    function finishAppend() {
        if (!appendPending || loading) return
        if (count <= previousCount && hasMore && !loadFailed && Date.now() - appendStarted < 2000) {
            check.restart()
            return
        }
        // QVariantList replacement resets the view; keep the reader's position.
        if (count > previousCount)
            contentY = Math.max(originY, Math.min(previousY, originY + Math.max(0, contentHeight - height)))
        appendPending = false
        scheduleCheck()
    }
    onContentYChanged: scheduleCheck()
    onHeightChanged: scheduleCheck()
    onVisibleChanged: scheduleCheck()
    onHasMoreChanged: scheduleCheck()
    onLoadingChanged: {
        if (!loading) Qt.callLater(finishAppend)
        scheduleCheck()
    }
    onCountChanged: {
        if (appendPending && !loading)
            Qt.callLater(finishAppend)
        scheduleCheck()
    }
    Timer {
        id: check
        interval: 100
        onTriggered: {
            if (root.appendPending) { root.finishAppend(); return }
            if (!root.visible || !root.hasMore || root.loading || root.loadFailed || root.appendPending || root.height <= 0) return
            if (root.contentHeight - (root.contentY - root.originY + root.height) > 100) return
            root.previousY = root.contentY
            root.previousCount = root.count
            root.appendStarted = Date.now()
            root.appendPending = true
            root.moreRequested()
            Qt.callLater(root.finishAppend)
        }
    }
    footer: Item {
        width: root.width; height: root.hasMore ? 34 : 0
        Label { anchors.centerIn: parent; text: root.loading ? "正在加载…" : root.loadFailed ? "加载失败，请重试" : "继续向下浏览"; color: "#a99dbd"; font.pixelSize: 11; visible: root.hasMore }
    }
    ScrollBar.vertical: ScrollBar {}
}
