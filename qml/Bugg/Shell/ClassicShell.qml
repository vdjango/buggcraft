import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Bugg.DesignSystem

Item {
    id: root
    property real pageMode: 0
    property real contentReveal: 1
    property real contentHeight: 0
    property real contentMaximumWidth: 560
    property string title: ""
    property string caption: ""
    property bool canGoBack: false
    property bool showHeader: true
    property bool fixedViewport: false
    readonly property alias contentHost: pageSlot
    readonly property real viewportHeight: scroll.height
    signal backRequested
    function resetScroll() {
        const flickable = scroll.contentItem as Flickable;
        if (flickable)
            flickable.contentY = 0;
    }
    PageLayout {
        width: parent.width
        maximumWidth: root.contentMaximumWidth
        opacity: root.pageMode * root.contentReveal * (root.showHeader ? 1 : 0)
        visible: opacity > 0
        RowLayout {
            Layout.fillWidth: true
            spacing: 14
            IconButton {
                visible: root.canGoBack
                iconName: "arrow"
                rotation: 180
                accessibleName: qsTr("返回")
                onClicked: root.backRequested()
            }
            PageHeader {
                Layout.fillWidth: true
                title: root.title
                caption: root.caption
                titleSize: 25
            }
        }
    }
    ScrollView {
        id: scroll
        objectName: "pageScrollView"
        x: 0
        y: 60 * (1 - root.pageMode) + root.pageMode * (root.showHeader ? 80 : 0)
        width: parent.width
        height: Math.max(0, parent.height - y)
        contentWidth: availableWidth
        contentHeight: root.fixedViewport ? height : root.contentHeight
        clip: true
        opacity: root.contentReveal
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ScrollBar.vertical.policy: root.fixedViewport ? ScrollBar.AlwaysOff : ScrollBar.AsNeeded
        transform: Translate {
            y: (1 - root.contentReveal) * 9
        }
        Binding {
            target: scroll.contentItem
            property: "interactive"
            when: scroll.contentItem instanceof Flickable
            value: !root.fixedViewport && scroll.contentHeight > scroll.height
        }
        Item {
            id: pageSlot
            width: scroll.availableWidth
            implicitHeight: root.contentHeight
        }
    }
}
