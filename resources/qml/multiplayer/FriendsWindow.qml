import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Rectangle {
    width: 410; height: 470; color: "#17151f"
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
        x: 14; y: 55; width: parent.width - 28; height: parent.height - 69; spacing: 8
        Loader {
            objectName: "friends-page-loader"; Layout.fillWidth: true; Layout.fillHeight: true
            source: vm.page === "friendForm" ? "FriendForm.qml" : "Friends.qml"
        }
        CopyText {
            objectName: "friend-feedback"; Layout.fillWidth: true
            visible: !!vm.error || !!vm.notice; text: vm.error || vm.notice
            color: vm.error ? "#ffc2bd" : "#cbb8ee"; font.pixelSize: 12
        }
    }
    Shortcut { sequence: "Escape"; onActivated: lobby.act(vm.page === "friendForm" ? "navigate" : "close", {page:"friends"}) }
}
