import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Rectangle {
    width: 520; height: 540; color: "#17151f"
    border.color: "#9281d3"; border.width: 2
    property var vm: lobby.view
    WindowHeader {
        x: 2; y: 2; width: parent.width - 4
        title: vm.page === "friendForm" ? (vm.editIndex >= 0 ? "编辑好友" : "添加好友") : "我的好友"
        navigationVisible: vm.page === "friendForm"
        navigationObjectName: "back-friends"
        navigationName: "返回好友列表"
        closeObjectName: "close-friends"
        closeName: "关闭好友窗口"
        minimizeName: "最小化好友窗口"
        onNavigate: lobby.act("navigate", {page:"friends"})
        onMinimize: lobby.act("minimize", {})
        onCloseRequested: lobby.act("close", {})
        onDragRequested: lobby.act("drag", {})
    }
    ColumnLayout {
        x: 18; y: 60; width: parent.width - 36; height: parent.height - 78; spacing: 10
        Loader {
            objectName: "friends-page-loader"; Layout.fillWidth: true; Layout.fillHeight: true
            source: vm.page === "friendForm" ? "FriendForm.qml" : "Friends.qml"
        }
        Rectangle {
            Layout.fillWidth: true; implicitHeight: Math.max(36, feedback.implicitHeight + 16)
            visible: !!vm.error || !!vm.notice; color: vm.error ? "#39242f" : "#2c243b"
            border.color: vm.error ? "#81505d" : "#57446e"
            RowLayout {
                anchors.fill: parent; anchors.margins: 8
                CopyText { id: feedback; objectName: "friend-feedback"; Layout.fillWidth: true; text: vm.error || vm.notice; color: vm.error ? "#ffc2bd" : "#d6c6ed"; font.pixelSize: 12; wrapMode: Text.Wrap }
                HeaderAction { text: "×"; label: "关闭提示"; implicitWidth: 24; implicitHeight: 24; onClicked: lobby.act("clearError", {}) }
            }
        }
    }
    Timer { interval: 5000; running: !!vm.notice && !vm.error && !vm.friendBusy; onTriggered: lobby.act("clearError", {}) }
    Shortcut { sequence: "Escape"; onActivated: lobby.act(vm.page === "friendForm" ? "navigate" : "close", {page:"friends"}) }
}
