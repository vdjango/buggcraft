pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Effects
import Bugg.Presentation

// 两层媒体交叉淡入；图片和视频由 BackdropMedia 统一管理，切页/收起时暂停视频。
Item {
    id: root
    property var sources: []
    property url fallbackSource: ""
    property real radius: 12
    property bool shade: false
    property bool active: true
    property bool soundEnabled: false
    property string blurStyle: "edges"
    property real blurAmount: 0.35
    property real vignette: 0.35
    property int interval: 12000
    readonly property url currentSource: currentIndex < 0 ? fallbackSource : playlist[currentIndex]
    readonly property color averageColor: palette.averageColor
    readonly property bool videoPlaying: front.playing
    readonly property var playlist: sources
    readonly property var front: firstOnTop ? first : second
    readonly property var back: firstOnTop ? second : first
    property bool firstOnTop: true
    property bool initialized: false
    property string loadedPlaylist: ""
    property int currentIndex: -1
    property int pendingIndex: -1
    property int attemptsLeft: 0
    property real blend: 0
    clip: true

    BackdropPalette {
        id: palette
        source: root.front.video ? "" : root.currentSource
    }
    function request(index, attempts) {
        if (attempts <= 0 || !playlist.length) {
            pendingIndex = -1;
            return;
        }
        pendingIndex = ((index % playlist.length) + playlist.length) % playlist.length;
        attemptsLeft = attempts - 1;
        back.source = playlist[pendingIndex];
        if (back.status === Image.Ready)
            mediaSettled(back);
        else if (back.status === Image.Error)
            request(pendingIndex + 1, attemptsLeft);
    }
    function mediaSettled(media) {
        if (pendingIndex < 0 || media !== back)
            return;
        if (media.status === Image.Error)
            request(pendingIndex + 1, attemptsLeft);
        else if (media.status === Image.Ready && !fade.running)
            fade.start();
    }
    function reload() {
        if (!initialized)
            return;
        const nextPlaylist = JSON.stringify(playlist);
        if (loadedPlaylist === nextPlaylist)
            return;
        loadedPlaylist = nextPlaylist;
        fade.stop();
        blend = 0;
        pendingIndex = -1;
        first.source = "";
        second.source = "";
        currentIndex = -1;
        if (playlist.length)
            request(0, playlist.length);
    }
    onPlaylistChanged: reload()
    Component.onCompleted: {
        initialized = true;
        reload();
    }

    layer.enabled: GraphicsInfo.api !== GraphicsInfo.Software
    layer.effect: MultiEffect {
        maskEnabled: true
        maskSource: roundedMask
    }
    RoundedMask {
        id: roundedMask
        width: root.width
        height: root.height
        radius: root.radius
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
    Item {
        id: mediaStack
        anchors.fill: parent
        BackdropMedia {
            id: first
            anchors.fill: parent
            active: root.active && root.visible && (root.firstOnTop || root.pendingIndex >= 0)
            muted: !root.soundEnabled || !root.firstOnTop
            opacity: root.firstOnTop ? 1 : root.blend
            z: root.firstOnTop ? 0 : 1
            onStatusChanged: root.mediaSettled(first)
        }
        BackdropMedia {
            id: second
            anchors.fill: parent
            active: root.active && root.visible && (!root.firstOnTop || root.pendingIndex >= 0)
            muted: !root.soundEnabled || root.firstOnTop
            opacity: root.firstOnTop ? root.blend : 1
            z: root.firstOnTop ? 1 : 0
            onStatusChanged: root.mediaSettled(second)
        }
    }
    ShaderEffectSource {
        id: blurSource
        anchors.fill: parent
        sourceItem: mediaStack
        textureSize: Qt.size(Math.max(1, Math.round(root.width / 2)), Math.max(1, Math.round(root.height / 2)))
        hideSource: false
        visible: false
        live: root.active && root.blurStyle !== "none" && root.blurAmount > 0
    }
    Rectangle {
        id: blurMask
        width: root.width
        height: root.height
        visible: true
        gradient: Gradient {
            GradientStop {
                position: 0
                color: "white"
            }
            GradientStop {
                position: 0.28
                color: root.blurStyle === "full" ? "white" : "transparent"
            }
            GradientStop {
                position: 0.68
                color: root.blurStyle === "full" ? "white" : "transparent"
            }
            GradientStop {
                position: 1
                color: root.blurStyle === "top" ? "transparent" : "white"
            }
        }
    }
    ShaderEffectSource {
        id: blurMaskTexture
        sourceItem: blurMask
        hideSource: true
        visible: false
        live: root.blurStyle !== "none" && root.blurAmount > 0
    }
    MultiEffect {
        anchors.fill: parent
        z: 2
        source: blurSource
        visible: root.blurStyle !== "none" && root.blurAmount > 0 && GraphicsInfo.api !== GraphicsInfo.Software
        blurEnabled: true
        blur: Math.min(1, root.blurAmount)
        blurMax: 40
        maskEnabled: true
        maskSource: blurMaskTexture
        maskThresholdMin: 0.5
        maskSpreadAtMin: 1
        autoPaddingEnabled: false
    }
    Rectangle {
        anchors.fill: parent
        z: 3
        visible: root.shade || root.vignette > 0
        gradient: Gradient {
            GradientStop {
                position: 0
                color: Qt.rgba(0.02, 0.04, 0.08, root.vignette * 0.8)
            }
            GradientStop {
                position: 0.45
                color: Qt.rgba(0, 0, 0, root.vignette * 0.03)
            }
            GradientStop {
                position: 1
                color: Qt.rgba(0.02, 0.04, 0.08, root.vignette)
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
            root.back.source = "";
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
