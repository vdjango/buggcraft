import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Rectangle {
    id: root
    property var state: dialogModel.view
    color: "#191722"
    radius: 14
    border.color: "#65518c"
    Connections { target: dialogModel; function onChanged() { root.state = dialogModel.view } }
    MouseArea {
        anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
        height: 82
        onPressed: dialogModel.dragWindow()
    }
    ColumnLayout {
        anchors.fill: parent; anchors.margins: 26; spacing: 18
        Item {
            Layout.fillWidth: true; Layout.preferredHeight: 48
            Rectangle {
                id: icon
                anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter
                width: 42; height: 42; radius: 13; color: "#382956"
                Label { anchors.centerIn: parent; text: "?"; color: "#d6c2ff"; font.pixelSize: 25; font.bold: true }
            }
            ColumnLayout {
                anchors.left: icon.right; anchors.leftMargin: 14
                anchors.right: close.left; anchors.rightMargin: 14
                anchors.verticalCenter: parent.verticalCenter; spacing: 4
                Label { text: "反馈问题"; color: "#f4efff"; font.pixelSize: 21; font.bold: true }
                Label { text: "描述问题，帮助我们找到原因"; color: "#b8aecb"; font.pixelSize: 12 }
            }
            ActionButton {
                id: close
                anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                objectName: "feedback-close"; text: "×"; implicitWidth: 34; onClicked: dialogModel.action("cancel")
            }
        }
        Rectangle { Layout.fillWidth: true; height: 1; color: "#342c45" }
        ScrollView {
            id: scroll
            Layout.fillWidth: true; Layout.fillHeight: true
            contentWidth: availableWidth; contentHeight: body.implicitHeight
            clip: true; ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
            ColumnLayout {
                id: body
                width: scroll.availableWidth; spacing: 12
                Label { text: "遇到了什么问题？"; color: "#ede6fa"; font.pixelSize: 14; font.bold: true }
                ScrollView {
                    Layout.fillWidth: true; Layout.preferredHeight: 170
                    clip: true; ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                    TextArea {
                        id: content
                        objectName: "feedback-content"
                        text: root.state.data.content || ""
                        placeholderText: "例如：加入朋友房间后一直连接中。\n可以补充操作步骤、出现时间和预期结果。"
                        placeholderTextColor: "#9489aa"
                        color: "#f1ecfa"; selectionColor: "#6f4bc0"; selectedTextColor: "#ffffff"
                        font.pixelSize: 14; wrapMode: TextEdit.Wrap; selectByMouse: true
                        padding: 14; focus: true
                        background: Rectangle {
                            radius: 9; color: "#231e30"
                            border.color: content.activeFocus ? "#a285e2" : "#4b3e62"
                        }
                        onTextChanged: dialogModel.setDataValue("content", text)
                        Component.onCompleted: forceActiveFocus()
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    Label { objectName: "feedback-error"; text: root.state.data.error || ""; color: "#ffb4c4"; font.pixelSize: 12; wrapMode: Text.Wrap; Layout.fillWidth: true }
                    Label { text: content.length + " / 4000"; color: content.length > 4000 ? "#ffb4c4" : "#a59ab7"; font.pixelSize: 12 }
                }
                Rectangle {
                    Layout.fillWidth: true; implicitHeight: collection.implicitHeight + 28
                    color: "#24202f"; radius: 10; border.color: "#3b324d"
                    ColumnLayout {
                        id: collection
                        anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
                        anchors.margins: 14; spacing: 9
                        Label { text: "提交时会自动收集"; color: "#e4d9f9"; font.pixelSize: 13; font.bold: true }
                        Label {
                            objectName: "feedback-collection-info"
                            Layout.fillWidth: true; color: "#beb3cf"; font.pixelSize: 12; wrapMode: Text.Wrap
                            text: "• 系统、启动器、Java 和游戏版本，模组与资源列表\n• 网络地址、网卡、路由、DNS，以及节点与联机连接记录\n• 启动器和游戏日志、崩溃记录"
                            lineHeight: 1.45
                        }
                        Label {
                            objectName: "feedback-privacy-info"
                            Layout.fillWidth: true; color: "#a99bbd"; font.pixelSize: 12; wrapMode: Text.Wrap
                            text: "不收集存档或设置文件；识别到的密码、令牌会脱敏。日志仍可能包含本地路径、网络地址和游戏聊天。"
                            lineHeight: 1.35
                        }
                    }
                }
                Label {
                    objectName: "feedback-recipient"
                    Layout.fillWidth: true; color: "#b5a8c9"; font.pixelSize: 12; wrapMode: Text.Wrap
                    text: "接收方：" + root.state.data.node + "的反馈管理员；启用联邦同步时，受信任节点管理员也可查看。"
                    lineHeight: 1.35
                }
            }
        }
        RowLayout {
            Layout.fillWidth: true; spacing: 10
            Label { Layout.fillWidth: true; text: "点击提交即同意收集并发送上述信息"; color: "#a99bbd"; font.pixelSize: 11; wrapMode: Text.Wrap }
            ActionButton { objectName: "feedback-cancel"; text: "取消"; implicitWidth: 70; onClicked: dialogModel.action("cancel") }
            ActionButton {
                objectName: "feedback-submit"; text: "提交问题"; primary: true; implicitWidth: 104
                enabled: root.state.actionsEnabled && content.text.trim().length > 0 && content.length <= 4000
                onClicked: dialogModel.action("submit")
            }
        }
    }
}
