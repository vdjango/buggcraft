pragma ComponentBehavior: Bound
import QtQuick

// Read-only bounded block document. Only visible image blocks are instantiated;
// HTML image tags were extracted in the catalogue worker before reaching QML.
ListViewport {
    id: root
    property var blocks: []
    property string introduction: ""
    model: blocks
    spacing: 12
    header: Column {
        width: root.width
        spacing: 12
        UiText {
            width: parent.width
            text: root.introduction
            visible: text.length > 0
            wrapMode: Text.Wrap
            elide: Text.ElideNone
            font.pixelSize: DesignTokens.controlTextSize
            color: DesignTokens.muted
            bottomPadding: 12
        }
    }
    delegate: Column {
        id: block
        required property var modelData
        width: ListView.view.width
        spacing: 6
        ContentImage {
            // Linked badges and video previews are supporting actions. Keep
            // their presentation compact so they do not displace the article.
            width: parent.width
            height: implicitHeight
            visible: !!block.modelData.image
            source: block.modelData.image || ""
            link: block.modelData.link || ""
            displayWidth: block.modelData.width || 0
            displayHeight: block.modelData.height || 0
            alignment: block.modelData.alignment || "left"
            illustration: true
            accessibleName: block.modelData.title || qsTr("项目图片")
        }
        UiText {
            width: parent.width - 10
            text: block.modelData.title || ""
            visible: text.length > 0
            color: DesignTokens.muted
            font.pixelSize: 11
            wrapMode: Text.Wrap
        }
        Text {
            width: parent.width - 10
            text: block.modelData.html || ""
            visible: text.length > 0
            textFormat: Text.RichText
            wrapMode: Text.Wrap
            color: DesignTokens.text
            linkColor: DesignTokens.accent
            font.family: DesignTokens.fontFamily
            font.pixelSize: DesignTokens.controlTextSize
            onLinkActivated: link => {
                if (/^https?:\/\//i.test(link))
                    Qt.openUrlExternally(link);
            }
        }
    }
}
