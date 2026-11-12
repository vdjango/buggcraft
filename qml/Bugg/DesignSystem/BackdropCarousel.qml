pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Effects
import Bugg.Presentation

// 输入本地 URL 列表和活动状态；只管理两层图片与呈现计时，不拥有设置或业务任务。
Item {
    id: root
    property var sources: []
    property url fallbackSource: ""
    property real radius: 12
    property bool shade: false
    property bool active: true
    property int interval: 12000
    readonly property url currentSource: currentIndex < 0 ? fallbackSource : front.source
    readonly property color averageColor: palette.averageColor
    readonly property var playlist: sources
    readonly property Image front: firstOnTop ? first : second
    readonly property Image back: firstOnTop ? second : first
    property bool firstOnTop: true
    property bool initialized: false
    property int currentIndex: -1
    property int pendingIndex: -1
    property int attemptsLeft: 0
    property real blend: 0
    clip: true
    BackdropPalette {
        id: palette
        source: root.currentSource
    }

    // 下一张就绪前保留当前图；失败仅尝试本轮剩余候选，避免损坏列表无限重试。
    function request(index, attempts) {
        if (attempts <= 0 || !playlist.length) {
            pendingIndex = -1;
            return;
        }
        attemptsLeft = attempts - 1;
        pendingIndex = index % playlist.length;
        back.source = playlist[pendingIndex];
        if (back.status === Image.Ready || back.status === Image.Error)
            imageSettled(back);
    }
    function imageSettled(image) {
        if (pendingIndex < 0 || image !== back)
            return;
        if (image.status === Image.Error) {
            request(pendingIndex + 1, attemptsLeft);
        } else if (image.status === Image.Ready && !fade.running) {
            fade.start();
        }
    }
    function reload() {
        if (!initialized)
            return;
        fade.stop();
        blend = 0;
        pendingIndex = -1;
        back.source = "";
        if (!playlist.length) {
            front.source = "";
            currentIndex = -1;
            return;
        }
        request(0, playlist.length);
    }
    onPlaylistChanged: reload()
    Component.onCompleted: {
        initialized = true;
        reload();
    }
    // 默认资源已做圆角；自选图在原生图形后端统一遮罩，不复制到页面。
    layer.enabled: GraphicsInfo.api !== GraphicsInfo.Software
    layer.effect: MultiEffect {
        maskEnabled: true
        maskSource: roundedMask
    }
    Rectangle {
        id: roundedMask
        width: root.width
        height: root.height
        radius: root.radius
        color: "white"
        layer.enabled: true
        visible: false
    }
    BorderImage {
        anchors.fill: parent
        source: root.fallbackSource
        asynchronous: true
        visible: root.currentIndex < 0
        border.left: 20
        border.top: 20
        border.right: 20
        border.bottom: 20
    }
    Image {
        id: first
        anchors.fill: parent
        asynchronous: true
        sourceSize: Qt.size(1280, 800)
        fillMode: Image.PreserveAspectCrop
        opacity: root.firstOnTop ? 1 : root.blend
        z: root.firstOnTop ? 0 : 1
        onStatusChanged: root.imageSettled(first)
    }
    Image {
        id: second
        anchors.fill: parent
        asynchronous: true
        sourceSize: Qt.size(1280, 800)
        fillMode: Image.PreserveAspectCrop
        opacity: root.firstOnTop ? root.blend : 1
        z: root.firstOnTop ? 1 : 0
        onStatusChanged: root.imageSettled(second)
    }
    Rectangle {
        anchors.fill: parent
        z: 2
        visible: root.shade
        gradient: Gradient {
            GradientStop {
                position: 0
                color: "#48000000"
            }
            GradientStop {
                position: 0.45
                color: "#10000000"
            }
            GradientStop {
                position: 1
                color: "#A0000000"
            }
        }
    }
    NumberAnimation {
        id: fade
        target: root
        property: "blend"
        from: 0
        to: 1
        duration: 420
        easing.type: Easing.InOutCubic
        onFinished: {
            root.firstOnTop = !root.firstOnTop;
            root.currentIndex = root.pendingIndex;
            root.pendingIndex = -1;
            root.blend = 0;
        }
    }
    Timer {
        objectName: "backdropRotationTimer"
        interval: Math.max(600, root.interval)
        repeat: true
        running: root.active && root.visible && root.playlist.length > 1 && root.pendingIndex < 0 && !fade.running
        onTriggered: root.request(root.currentIndex + 1, root.playlist.length)
    }
}
