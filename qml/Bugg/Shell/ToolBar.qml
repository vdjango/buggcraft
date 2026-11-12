pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import Bugg.DesignSystem

Item {
    id: root
    required property var dock
    property int activeTool: -1
    property bool showWindowControls: true
    property real pageMode: 0
    property bool friendsVisible: false
    property var activity: ({
            active: false,
            progress: -1
        })
    signal navigateRequested(int index)
    signal tasksRequested
    signal closeRequested
    implicitHeight: 60
    ProgressSurface {
        objectName: "toolbarActivity"
        anchors.fill: parent
        active: root.activity.active === true
        progress: root.activity.progress === undefined ? -1 : root.activity.progress
        fluid: true
        cornerRadius: 18
    }
    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 14 + root.pageMode * 6
        anchors.rightMargin: 10
        spacing: 4
        BrandButton {
            docked: root.dock.attachment !== 0
            Layout.rightMargin: 5
            onClicked: root.dock.attachment ? root.dock.toggleFold() : root.navigateRequested(-1)
            onMoveRequested: root.dock.beginMove()
        }
        UiText {
            text: "Bugg"
            visible: root.pageMode > 0.5
            font.pixelSize: 18
            font.weight: Font.DemiBold
            Layout.rightMargin: 44 * root.pageMode
        }
        NavigationBar {
            objectName: "mainNavigation"
            itemWidth: 52 + root.pageMode * 22
            itemHeight: 34 + root.pageMode * 8
            underline: root.pageMode > 0.5
            items: (root.pageMode > 0.5 ? [qsTr("启动"), qsTr("广场"), qsTr("联机")] : [qsTr("启动"), qsTr("联机")]).concat(root.friendsVisible ? [qsTr("好友")] : [])
            toolIds: (root.pageMode > 0.5 ? [0, 1, 2] : [0, 2]).concat(root.friendsVisible ? [3] : [])
            selectedIndex: root.activeTool < 4 ? root.activeTool : -1
            onSelected: index => root.navigateRequested(index)
        }
        Item {
            Layout.fillWidth: true
            Layout.minimumWidth: 3
        }
        IconButton {
            objectName: "downloadTasksButton"
            iconName: "download"
            accessibleName: qsTr("任务")
            onClicked: root.tasksRequested()
        }
        IconButton {
            objectName: "settingsButton"
            iconName: "settings"
            accessibleName: qsTr("设置")
            selected: root.activeTool === 4
            onClicked: root.navigateRequested(4)
        }
        WindowControls {
            visible: root.showWindowControls
            onCloseRequested: root.closeRequested()
        }
    }
}
