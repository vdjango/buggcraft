import QtQuick
import QtQuick.Layouts

// 只处理呈现页码，原列表和页码草稿仍归调用方；上一页/下一页共用图标按钮。
RowLayout {
    id: root
    property int itemCount: 0
    property int pageSize: 3
    property int pageIndex: 0
    property bool countKnown: true
    property bool hasMore: false
    readonly property int pageCount: Math.max(1, Math.ceil(itemCount / pageSize))
    readonly property int currentPage: Math.max(0, countKnown ? Math.min(pageIndex, pageCount - 1) : pageIndex)
    signal chosen(int index)
    spacing: 8
    IconButton {
        objectName: "previousPageButton"
        iconName: "chevron"
        rotation: 180
        accessibleName: qsTr("上一页")
        enabled: root.currentPage > 0
        onClicked: root.chosen(root.currentPage - 1)
    }
    UiText {
        text: root.countKnown ? (root.currentPage + 1) + " / " + root.pageCount : qsTr("第 %1 页").arg(root.currentPage + 1)
        font.pixelSize: 11
        color: DesignTokens.muted
    }
    IconButton {
        objectName: "nextPageButton"
        iconName: "chevron"
        accessibleName: qsTr("下一页")
        enabled: root.countKnown ? root.currentPage + 1 < root.pageCount : root.hasMore
        onClicked: root.chosen(root.currentPage + 1)
    }
}
