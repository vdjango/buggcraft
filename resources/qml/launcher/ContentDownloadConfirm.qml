import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Rectangle {
    id: root
    property var state: dialogModel.view
    property var info: state.data
    color: "#191720"
    border.color: "#655493"
    radius: 7
    Connections { target: dialogModel; function onChanged() { root.state = dialogModel.view } }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 22
        spacing: 14
        RowLayout {
            Layout.fillWidth: true
            spacing: 10
            Rectangle {
                Layout.preferredWidth: 34
                Layout.preferredHeight: 34
                radius: 6
                color: "#302944"
                Label { anchors.centerIn: parent; text: "↓"; color: "#c8b7ff"; font.pixelSize: 21; font.bold: true }
            }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 2
                Label { text: "确认下载"; color: "#f1edf8"; font.pixelSize: 18; font.bold: true }
                Label { text: root.info.project || "资源"; color: "#a69bb9"; font.pixelSize: 12; elide: Text.ElideRight; Layout.fillWidth: true }
            }
            ToolButton {
                objectName: "content-download-close"
                text: "×"
                Accessible.name: "取消下载"
                onClicked: dialogModel.action("取消")
                contentItem: Text { text: parent.text; color: "#bcb5ca"; font.pixelSize: 23; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                background: Rectangle { radius: 4; color: parent.hovered ? "#302b3b" : "transparent" }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            implicitHeight: versionDetails.implicitHeight + 24
            radius: 5
            color: "#24212d"
            border.color: "#40384e"
            ColumnLayout {
                id: versionDetails
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 12
                spacing: 5
                Label { text: "下载的版本"; color: "#9f94b1"; font.pixelSize: 11 }
                Label { objectName: "content-download-version"; text: root.info.version || ""; color: "#eee8f7"; font.pixelSize: 14; font.bold: true; wrapMode: Text.Wrap; Layout.fillWidth: true }
                Label { text: [root.info.filename, root.info.size].filter(Boolean).join("  ·  "); color: "#aaa1b7"; font.pixelSize: 11; wrapMode: Text.Wrap; Layout.fillWidth: true }
            }
        }

        ToolButton {
            id: targetToggle
            objectName: "content-download-target-toggle"
            Layout.fillWidth: true
            implicitHeight: 30
            text: (root.info.targetExpanded ? "⌄" : "›") + "  下载到「" + (root.info.instance || "未选择") + "」"
            onClicked: dialogModel.action("toggle-target")
            contentItem: Text { text: parent.text; color: "#c9b9ef"; font.pixelSize: 12; verticalAlignment: Text.AlignVCenter }
            background: Rectangle { radius: 4; color: parent.hovered ? "#2a2635" : "transparent" }
        }

        ComboBox {
            id: targetPicker
            objectName: "content-download-target"
            visible: !!root.info.targetExpanded && root.info.kind !== "modpack"
            Layout.fillWidth: true
            model: root.info.instances || []
            currentIndex: Math.max(0, (root.info.instances || []).indexOf(root.info.instance || ""))
            onActivated: index => dialogModel.action("目标:" + textAt(index))
            contentItem: Text { leftPadding: 10; text: parent.displayText; color: "#eee8f7"; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight; font.pixelSize: 12 }
            background: Rectangle { radius: 4; color: "#24212d"; border.color: "#62547d" }
        }

        Label {
            Layout.fillWidth: true
            visible: !!root.info.targetExpanded && root.info.kind === "modpack"
            text: "整合包将创建独立实例，目标游戏版本由整合包文件决定。"
            color: "#b9afc9"
            wrapMode: Text.Wrap
            font.pixelSize: 11
        }
        Label {
            Layout.fillWidth: true
            visible: !!root.info.error
            text: root.info.error || ""
            color: "#f09a9a"
            wrapMode: Text.Wrap
            font.pixelSize: 11
        }

        Item { Layout.fillHeight: true; Layout.minimumHeight: 0 }
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            Item { Layout.fillWidth: true }
            ActionButton { text: "取消"; implicitWidth: 82; implicitHeight: 34; onClicked: dialogModel.action("取消") }
            ActionButton { objectName: "content-download-confirm"; text: "确认下载"; implicitWidth: 104; implicitHeight: 34; primary: true; enabled: root.info.kind === "modpack" || !!root.info.instance; onClicked: dialogModel.action("确认下载") }
        }
    }
}
