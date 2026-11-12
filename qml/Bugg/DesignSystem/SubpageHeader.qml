import QtQuick
import QtQuick.Layouts

RowLayout {
    id: root
    property string title: ""
    property string caption: ""
    property int titleSize: 18
    property bool homeAsBack: false
    property bool worldIcon: false
    property bool wrapCaption: false
    property color captionColor: DesignTokens.muted
    property string actionIcon: ""
    property string actionName: ""
    signal actionRequested
    signal backRequested
    signal homeRequested
    spacing: 10
    IconButton {
        objectName: "subpageBackButton"
        Layout.alignment: Qt.AlignVCenter
        iconName: root.homeAsBack ? "home" : "arrow"
        rotation: root.homeAsBack ? 0 : 180
        accessibleName: root.homeAsBack ? qsTr("回到首页") : qsTr("返回")
        onClicked: root.homeAsBack ? root.homeRequested() : root.backRequested()
    }
    WorldMark {
        visible: root.worldIcon
        Layout.preferredWidth: 30
        Layout.preferredHeight: 30
    }
    PageHeader {
        objectName: "subpageTitle"
        title: root.title
        caption: root.caption
        titleSize: root.titleSize
        wrapCaption: root.wrapCaption
        captionColor: root.captionColor
        spacing: 2
        Layout.alignment: Qt.AlignVCenter
        Layout.fillWidth: true
    }
    IconButton {
        objectName: "subpageHomeButton"
        visible: !root.homeAsBack
        iconName: "home"
        accessibleName: qsTr("回到首页")
        onClicked: root.homeRequested()
    }
    IconButton {
        objectName: "subpageActionButton"
        visible: root.actionIcon.length > 0
        iconName: root.actionIcon
        accessibleName: root.actionName
        onClicked: root.actionRequested()
    }
}
