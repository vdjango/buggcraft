pragma ComponentBehavior: Bound
import QtQuick
import QtMultimedia

// Local presentation only: one image or one silent, native-decoded video.
// Hidden backgrounds pause; removing a source releases its player.
Item {
    id: root
    property url source: ""
    property bool active: true
    property bool muted: true
    readonly property bool video: /\.(mp4|m4v|mov|webm|mkv)$/i.test(String(source))
    readonly property VideoLayer movieItem: movie.item as VideoLayer
    readonly property int status: !source.toString() ? Image.Null : video ? (movieItem ? movieItem.status : Image.Loading) : picture.status
    readonly property int playbackState: movieItem ? movieItem.playbackState : MediaPlayer.StoppedState
    readonly property bool playing: movieItem ? movieItem.playing : false
    readonly property bool rotated: picture.portrait
    clip: true
    Image {
        id: picture
        source: root.video ? "" : root.source
        asynchronous: true
        autoTransform: true
        sourceSize: Qt.size(1280, 800)
        readonly property bool portrait: implicitHeight > implicitWidth
        readonly property real aspect: implicitWidth > 0 && implicitHeight > 0 ? (portrait ? implicitHeight / implicitWidth : implicitWidth / implicitHeight) : 1
        readonly property real coverWidth: Math.max(root.width, root.height * aspect)
        readonly property real coverHeight: coverWidth / aspect
        readonly property real centerY: (root.height - coverHeight) / 2 - (portrait ? root.height * 0.035 : 0)
        width: portrait ? coverHeight : coverWidth
        height: portrait ? coverWidth : coverHeight
        x: (root.width - width) / 2
        y: centerY + coverHeight / 2 - height / 2
        rotation: portrait ? 90 : 0
        fillMode: Image.PreserveAspectFit
    }
    Loader {
        id: movie
        anchors.fill: parent
        active: root.video && root.source.toString().length > 0
        sourceComponent: VideoLayer {
            source: root.source
            active: root.active
            muted: root.muted
        }
    }
    component VideoLayer: Item {
        id: videoLayer
        required property url source
        required property bool active
        required property bool muted
        property bool frameReady: false
        readonly property int status: player.error !== MediaPlayer.NoError ? Image.Error : frameReady ? Image.Ready : Image.Loading
        readonly property int playbackState: player.playbackState
        readonly property bool playing: player.playbackState === MediaPlayer.PlayingState
        AudioOutput {
            id: audio
            muted: videoLayer.muted
            volume: 1
        }
        MediaPlayer {
            id: player
            source: videoLayer.source
            videoOutput: output
            audioOutput: audio
            loops: MediaPlayer.Infinite
            onMediaStatusChanged: {
                if (mediaStatus === MediaPlayer.LoadedMedia && videoLayer.active)
                    play();
            }
        }
        VideoOutput {
            id: output
            anchors.fill: parent
            fillMode: VideoOutput.PreserveAspectCrop
            onSourceRectChanged: {
                if (sourceRect.width > 0 && sourceRect.height > 0)
                    videoLayer.frameReady = true;
            }
        }
        onActiveChanged: {
            if (videoLayer.active)
                player.play();
            else
                player.pause();
        }
        onSourceChanged: frameReady = false
        Component.onCompleted: {
            if (videoLayer.active)
                player.play();
        }
    }
}
