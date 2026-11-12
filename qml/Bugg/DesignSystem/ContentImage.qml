import QtQuick
import QtQuick.Window

// Generic bounded asynchronous thumbnail/illustration. Qt owns image transport
// and decoding; pages never query a business API or decode image bytes.
Item {
    id: root
    property url source: ""
    property bool illustration: false
    property string accessibleName: ""
    property url link: ""
    property size decodedSize: Qt.size(0, 0)
    property real displayWidth: 0
    property real displayHeight: 0
    property string alignment: "center"
    readonly property real naturalWidth: displayWidth > 0 ? displayWidth : displayHeight > 0 && aspectRatio > 0 ? displayHeight / aspectRatio : decodedSize.width
    readonly property real aspectRatio: displayWidth > 0 && displayHeight > 0 ? displayHeight / displayWidth : decodedSize.width > 0 ? decodedSize.height / decodedSize.width : 1
    readonly property bool ready: picture.status === Image.Ready
    readonly property bool loading: picture.status === Image.Loading
    implicitWidth: illustration ? 320 : 40
    implicitHeight: illustration ? (ready && naturalWidth > 0 ? Math.min(width, naturalWidth) * aspectRatio : 36) : implicitWidth
    clip: true
    Accessible.name: accessibleName
    HoverHandler {
        enabled: root.link.toString().length > 0
        cursorShape: Qt.PointingHandCursor
    }
    TapHandler {
        enabled: root.link.toString().length > 0
        onTapped: Qt.openUrlExternally(root.link)
    }
    Rectangle {
        anchors.fill: parent
        color: DesignTokens.surface
        radius: root.illustration ? 6 : 10
        visible: picture.status !== Image.Ready
    }
    AppIcon {
        anchors.centerIn: parent
        name: "library"
        width: 22
        height: 22
        color: DesignTokens.quiet
        visible: picture.status !== Image.Ready && (!root.illustration || picture.status !== Image.Error)
    }
    ActionButton {
        anchors.centerIn: parent
        visible: root.illustration && picture.status === Image.Error && root.source.toString().length > 0
        text: qsTr("图片暂不可用 · 查看原图")
        compact: true
        variant: "ghost"
        onClicked: Qt.openUrlExternally(root.source)
    }
    Image {
        id: picture
        objectName: "contentPicture"
        x: root.alignment === "left" ? 0 : root.alignment === "right" ? root.width - width : (root.width - width) / 2
        anchors.top: parent.top
        width: root.illustration && root.ready && root.naturalWidth > 0 ? Math.min(root.width, root.naturalWidth) : root.width
        height: parent.height
        source: root.source
        asynchronous: true
        fillMode: Image.PreserveAspectFit
        sourceSize.width: root.illustration ? (root.displayWidth > 0 ? Math.min(1024, Math.ceil(root.displayWidth * Screen.devicePixelRatio)) : 0) : 96
        cache: true
        onStatusChanged: {
            if (status === Image.Ready)
                root.decodedSize = Qt.size(implicitWidth, implicitHeight);
        }
    }
}
