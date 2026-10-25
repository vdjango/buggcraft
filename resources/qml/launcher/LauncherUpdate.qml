import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root
    property var state: dialogModel.view
    property var info: state.data
    property var noteItems: String(root.state.detail || "").replace(/\r/g, "").split("\n").map(function(line) {
        return line.trim().replace(/^[-*•]\s*/, "")
    }).filter(function(line) { return line.length > 0 })
    color: "#272937"
    border.color: "#655e9b"
    radius: 6
    Connections { target: dialogModel; function onChanged() { root.state = dialogModel.view } }

    MouseArea {
        anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
        height: 66
        onPressed: dialogModel.dragWindow()
    }
    ColumnLayout {
        anchors.fill: parent; anchors.margins: 20; spacing: 12
        RowLayout {
            Layout.fillWidth: true; spacing: 10
            Rectangle {
                implicitWidth: 32; implicitHeight: 32; radius: 6; color: "#37304f"
                Label { anchors.centerIn: parent; text: "↑"; color: "#c7baff"; font.pixelSize: 23; font.bold: true }
            }
            Label { text: "Buggcraft"; color: "#eeeef4"; font.pixelSize: 15; font.bold: true }
            Label { text: "启动器更新"; color: "#a9a4bc"; font.pixelSize: 12 }
            Item { Layout.fillWidth: true }
            Rectangle {
                implicitWidth: channelLabel.implicitWidth + 18; implicitHeight: 26; radius: 5
                color: "#343047"; border.color: "#55496e"
                Label { id: channelLabel; anchors.centerIn: parent; text: root.info.channelName || "稳定版"; color: "#c7baff"; font.pixelSize: 11 }
            }
            ToolButton {
                objectName: "update-close"; enabled: !root.state.working
                implicitWidth: 28; implicitHeight: 28; text: "×"
                Accessible.name: "关闭更新提示"
                contentItem: Text { text: parent.text; color: parent.enabled ? "#bcb5cc" : "#625e73"; font.pixelSize: 23; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                background: Rectangle { radius: 4; color: parent.hovered && parent.enabled ? "#3a354a" : "transparent" }
                onClicked: dialogModel.action("关闭")
            }
        }
        ColumnLayout {
            Layout.fillWidth: true; spacing: 5
            Label {
                objectName: "update-title"; Layout.fillWidth: true
                text: root.state.title; color: "#f3f0fa"; font.pixelSize: 20; font.bold: true
                wrapMode: Text.Wrap; textFormat: Text.PlainText
            }
            Label {
                objectName: "update-message"; Layout.fillWidth: true
                text: root.state.message; color: "#bdb7cd"; font.pixelSize: 12
                wrapMode: Text.Wrap; textFormat: Text.PlainText; lineHeight: 1.25
            }
        }
        Rectangle {
            Layout.fillWidth: true; implicitHeight: versionRow.implicitHeight + 20
            visible: !!root.info.version
            color: "#222431"; radius: 6; border.color: "#454054"
            RowLayout {
                id: versionRow
                anchors.left: parent.left; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                anchors.margins: 12; spacing: 12
                ColumnLayout {
                    Layout.fillWidth: true; Layout.preferredWidth: 1; spacing: 8
                    Label { text: "当前版本"; font.pixelSize: 11; color: "#9993ad" }
                    Label { objectName: "update-current-version"; Layout.fillWidth: true; text: root.info.currentVersion || ""; font.pixelSize: 13; color: "#d1ccdf"; wrapMode: Text.WrapAnywhere; textFormat: Text.PlainText }
                }
                Label { text: "→"; font.pixelSize: 22; color: "#8c7fba" }
                ColumnLayout {
                    Layout.fillWidth: true; Layout.preferredWidth: 1; spacing: 8
                    RowLayout {
                        Label { text: "新版本"; font.pixelSize: 11; color: "#bca8ff" }
                        Label { visible: !!root.info.packageSize; text: "·  " + (root.info.packageSize || ""); font.pixelSize: 11; color: "#9993ad" }
                    }
                    Label { objectName: "update-new-version"; Layout.fillWidth: true; text: root.info.version || ""; font.pixelSize: 13; font.bold: true; color: "#c9bbff"; wrapMode: Text.WrapAnywhere; textFormat: Text.PlainText }
                }
            }
        }
        ColumnLayout {
            Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumHeight: 90; spacing: 7
            Label { text: root.info.phase === "error" ? "处理建议" : "本次更新"; color: "#eee8f6"; font.pixelSize: 12; font.bold: true }
            ScrollView {
                id: notesScroll
                Layout.fillWidth: true; Layout.fillHeight: true
                contentWidth: availableWidth; clip: true
                ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                ColumnLayout {
                    objectName: "update-notes"; width: notesScroll.availableWidth; spacing: 7
                    Repeater {
                        model: root.noteItems
                        delegate: RowLayout {
                            required property string modelData
                            Layout.fillWidth: true; spacing: 9
                            Rectangle { Layout.alignment: Qt.AlignTop; Layout.topMargin: 6; width: 5; height: 5; radius: 2; color: "#a58bf3" }
                            Label {
                                Layout.fillWidth: true; text: modelData; color: "#c0bbcf"; font.pixelSize: 12
                                wrapMode: Text.Wrap; textFormat: Text.PlainText
                            }
                        }
                    }
                    Label { visible: root.noteItems.length === 0; text: "本次更新没有附加说明。"; color: "#9d96ad"; font.pixelSize: 12 }
                }
            }
        }
        ColumnLayout {
            Layout.fillWidth: true; visible: root.state.working; spacing: 10
            RowLayout {
                Layout.fillWidth: true
                Label { objectName: "update-progress-text"; Layout.fillWidth: true; text: root.info.progressText || "正在下载更新…"; color: "#cec4e9"; font.pixelSize: 12 }
                Label { text: Math.round(root.state.progress * 100) + "%"; color: "#c9bbff"; font.pixelSize: 12; font.bold: true }
            }
            ProgressBar {
                id: downloadProgress
                objectName: "update-progress"; Layout.fillWidth: true; implicitHeight: 6
                from: 0; to: 1; value: root.state.progress
                background: Rectangle { radius: 3; color: "#3b354d" }
                contentItem: Item { Rectangle { width: parent.width * downloadProgress.visualPosition; height: parent.height; radius: 3; color: "#9476ff" } }
            }
        }
        Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: "#454052" }
        Label {
            objectName: "update-footer"; Layout.fillWidth: true
            text: root.info.footer || "启动后自动检查，运行期间每 4 小时检查一次。"
            wrapMode: Text.Wrap; color: "#9992ac"; font.pixelSize: 11
        }
        RowLayout {
            Layout.fillWidth: true; spacing: 12
            Item { Layout.fillWidth: true }
            Repeater {
                model: root.state.actions
                ActionButton {
                    required property string modelData
                    required property int index
                    objectName: "update-action-" + index
                    text: modelData; implicitWidth: modelData === root.state.primaryAction ? 156 : 112; implicitHeight: 38
                    primary: modelData === root.state.primaryAction
                    enabled: root.state.actionsEnabled
                    onClicked: dialogModel.action(modelData)
                }
            }
        }
    }
}
