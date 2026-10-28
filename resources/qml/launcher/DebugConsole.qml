import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root
    color: "#272937"; radius: 6; border.color: "#655e9b"
    property var state: debugLogs.view
    component LogCheck: CheckBox {
        id: control
        implicitHeight: 32; spacing: 7
        indicator: Rectangle {
            x: 0; y: (control.height - height) / 2; width: 19; height: 19; radius: 4
            color: control.checked ? "#7754ed" : "#1b1d28"
            border.color: control.activeFocus ? "#baacff" : control.checked ? "#9679ff" : "#716985"
            Text { anchors.centerIn: parent; text: "✓"; visible: control.checked; color: "white"; font.pixelSize: 14 }
        }
        contentItem: Text { text: control.text; color: "#c9c3d6"; font.pixelSize: 12; verticalAlignment: Text.AlignVCenter; leftPadding: 26 }
    }
    Connections { target: debugLogs; function onChanged() { root.state = debugLogs.view; if (root.state.follow && !root.state.paused) Qt.callLater(function() { output.positionViewAtEnd() }) } }
    MouseArea { anchors.top: parent.top; width: parent.width; height: 55; onPressed: dialogModel.dragWindow() }
    ColumnLayout {
        anchors.fill: parent; anchors.margins: 20; spacing: 10
        RowLayout {
            Layout.fillWidth: true
            Label { text: "Minecraft · 游戏日志"; color: "#f1edf8"; font.pixelSize: 19; font.bold: true; Layout.fillWidth: true }
            Label { text: "错误 " + root.state.errors; color: "#ff8f9c"; font.pixelSize: 12 }
            Label { text: "警告 " + root.state.warnings; color: "#f1ca79"; font.pixelSize: 12; leftPadding: 12 }
        }
        Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: "#454052" }
        RowLayout {
            Layout.fillWidth: true; spacing: 8
            TextField {
                objectName: "debug-search"; Layout.fillWidth: true; implicitHeight: 36
                placeholderText: "搜索消息、模组 ID、异常或文件路径…"; color: "#f1edf8"; selectByMouse: true
                placeholderTextColor: "#9690ab"
                onTextChanged: debugLogs.search(text)
                background: Rectangle { color: "#1b1d28"; border.color: parent.activeFocus ? "#a99bf8" : "#494255"; radius: 4 }
            }
            LogCheck { objectName: "debug-regex"; text: "正则"; onToggled: debugLogs.useRegex(checked) }
            ActionButton { objectName: "debug-pause"; text: root.state.paused ? "继续接收" : "暂停显示"; onClicked: debugLogs.togglePaused() }
        }
        RowLayout {
            Layout.fillWidth: true; spacing: 8
            ChoiceBox { objectName: "debug-level"; Layout.preferredWidth: 160; model: root.state.levels; onActivated: debugLogs.selectLevel(currentIndex) }
            ChoiceBox { objectName: "debug-category"; Layout.preferredWidth: 135; model: root.state.categories; onActivated: debugLogs.selectCategory(currentIndex) }
            ChoiceBox { objectName: "debug-logger"; Layout.fillWidth: true; model: root.state.loggers; onActivated: debugLogs.selectLogger(currentText) }
            LogCheck { objectName: "debug-follow"; text: "自动滚动"; checked: true; onToggled: debugLogs.setFollow(checked) }
        }
        Label { visible: !!root.state.error; text: root.state.error; color: "#ff8f9c"; Layout.fillWidth: true; wrapMode: Text.Wrap }
        Rectangle {
            Layout.fillWidth: true; Layout.fillHeight: true; color: "#191c27"; border.color: "#454052"; radius: 4
            ListView {
                id: output; objectName: "debug-log-list"
                anchors.fill: parent; anchors.margins: 6; clip: true; model: debugLogs; spacing: 2
                reuseItems: true; ScrollBar.vertical: ScrollBar {}
                delegate: Rectangle {
                    required property int lineNumber
                    required property string body
                    required property string severity
                    required property string tint
                    required property string category
                    required property string logger
                    objectName: "debug-log-row-" + lineNumber
                    width: output.width - 12; height: Math.max(30, message.implicitHeight + 10)
                    color: severity === "ERROR" || severity === "FATAL" ? "#30202d" : lineNumber % 2 ? "#1e212d" : "transparent"
                    RowLayout {
                        anchors.fill: parent; anchors.leftMargin: 5; anchors.rightMargin: 5; spacing: 9
                        Label { text: lineNumber; color: "#767d96"; Layout.preferredWidth: 42; font.family: "Consolas"; font.pixelSize: 11; Layout.alignment: Qt.AlignTop; topPadding: 5 }
                        Label { text: severity; color: tint; font.bold: true; font.pixelSize: 10; Layout.preferredWidth: 42; Layout.alignment: Qt.AlignTop; topPadding: 5 }
                        TextEdit { id: message; objectName: "debug-message-" + lineNumber; text: body; textFormat: TextEdit.RichText; color: "#e1dfea"; font.family: "Consolas"; font.pixelSize: 12; readOnly: true; selectByMouse: true; wrapMode: TextEdit.Wrap; Layout.fillWidth: true; Layout.preferredHeight: implicitHeight; Layout.alignment: Qt.AlignVCenter }
                    }
                    ToolTip.text: category + " · " + logger
                    ToolTip.visible: hover.hovered
                    HoverHandler { id: hover }
                }
                Label { anchors.centerIn: parent; visible: output.count === 0; text: root.state.total ? "没有匹配的日志" : "等待游戏输出…"; color: "#9690ab" }
            }
        }
        RowLayout {
            Layout.fillWidth: true; spacing: 8
            Label { text: "显示 " + root.state.shown + " / " + root.state.total + " 条 · 保留最近 5000 条"; color: "#a5a0b8"; font.pixelSize: 11; Layout.fillWidth: true }
            Label { text: root.state.notice; color: "#a8d995"; font.pixelSize: 11 }
            ActionButton { objectName: "debug-copy"; text: "复制筛选结果"; onClicked: debugLogs.copyVisible() }
            ActionButton { objectName: "debug-export"; text: "导出筛选结果"; onClicked: debugLogs.saveVisible() }
            ActionButton { objectName: "dialog-action-0"; text: "关闭"; primary: true; onClicked: dialogModel.action("关闭") }
        }
    }
}
