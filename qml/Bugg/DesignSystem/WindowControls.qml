import QtQuick
import QtQuick.Layouts

RowLayout {
    id: root
    property bool showCollapse: false
    property bool showDivider: true
    property string closeIcon: "close"
    property string closeName: qsTr("关闭")
    signal collapseRequested
    signal closeRequested
    spacing: 7
    Divider {
        visible: root.showDivider
        implicitWidth: 1
        implicitHeight: 13
        Layout.rightMargin: 4
    }
    IconButton {
        objectName: "collapseWindowButton"
        visible: root.showCollapse
        iconName: "collapse"
        feedbackEnabled: false
        accessibleName: qsTr("吸附到屏幕顶部")
        onClicked: root.collapseRequested()
    }
    IconButton {
        objectName: "closeWindowButton"
        implicitWidth: 24
        iconName: root.closeIcon
        rotation: root.closeIcon === "arrow" ? 180 : 0
        feedbackEnabled: false
        accessibleName: root.closeName
        onClicked: root.closeRequested()
    }
}
