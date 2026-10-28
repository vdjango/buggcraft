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
        anchors.margins: 18
        spacing: 10
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
            implicitHeight: versionDetails.implicitHeight + 20
            radius: 5
            color: "#24212d"
            border.color: "#40384e"
            ColumnLayout {
                id: versionDetails
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 10
                spacing: 4
                RowLayout {
                    Layout.fillWidth: true
                    Label { text: "下载版本"; color: "#bda9ee"; font.pixelSize: 11; font.bold: true }
                    Item { Layout.fillWidth: true }
                    Label { text: root.info.kind === "mod" ? "模组" : root.info.kind === "resourcepack" ? "资源包" : root.info.kind === "shader" ? "光影" : "整合包"; color: "#948ba5"; font.pixelSize: 10 }
                }
                Label { objectName: "content-download-version"; text: root.info.version || ""; color: "#eee8f7"; font.pixelSize: 14; font.bold: true; wrapMode: Text.Wrap; maximumLineCount: 2; elide: Text.ElideRight; textFormat: Text.PlainText; Layout.fillWidth: true }
                Label { text: [root.info.filename, root.info.size].filter(Boolean).join("  ·  "); visible: !!text; color: "#aaa1b7"; font.pixelSize: 11; maximumLineCount: 2; elide: Text.ElideMiddle; wrapMode: Text.Wrap; textFormat: Text.PlainText; Layout.fillWidth: true }
            }
        }

        ToolButton {
            id: targetToggle
            objectName: "content-download-target-toggle"
            Layout.fillWidth: true
            implicitHeight: 30
            text: root.info.kind === "modpack" ? "下载到新的独立游戏实例" : (root.info.targetExpanded ? "⌄" : "›") + "  下载到「" + (root.info.instance || "未选择") + "」"
            enabled: root.info.kind !== "modpack"
            onClicked: dialogModel.action("toggle-target")
            contentItem: Text { leftPadding: 10; rightPadding: 10; text: parent.text; color: "#c9b9ef"; font.pixelSize: 12; verticalAlignment: Text.AlignVCenter }
            background: Rectangle { radius: 4; color: parent.hovered ? "#2a2635" : "#211d2a"; border.color: "#40384e" }
        }

        ComboBox {
            id: targetPicker
            objectName: "content-download-target"
            visible: !!root.info.targetExpanded && root.info.kind !== "modpack"
            Layout.fillWidth: true
            model: root.info.instances || []
            currentIndex: Math.max(0, (root.info.instances || []).indexOf(root.info.instance || ""))
            onActivated: index => dialogModel.action("目标:" + textAt(index))
            contentItem: Text { leftPadding: 10; rightPadding: 30; text: parent.displayText; color: "#eee8f7"; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight; font.pixelSize: 12 }
            indicator: Text { x: targetPicker.width - width - 12; anchors.verticalCenter: parent.verticalCenter; text: "⌄"; font.pixelSize: 17; color: "#c9b9ef" }
            background: Rectangle { radius: 4; color: "#24212d"; border.color: "#62547d" }
            delegate: ItemDelegate {
                required property int index
                required property string modelData
                width: targetPicker.width
                highlighted: targetPicker.highlightedIndex === index
                contentItem: Text { text: modelData; color: "#eee8f7"; font.pixelSize: 12; elide: Text.ElideRight; verticalAlignment: Text.AlignVCenter }
                background: Rectangle { color: parent.highlighted ? "#45365e" : "#24212d"; radius: 3 }
            }
            popup: Popup {
                y: targetPicker.height + 3
                width: targetPicker.width
                padding: 4
                implicitHeight: Math.min(180, contentItem.implicitHeight + 8)
                contentItem: ListView {
                    clip: true
                    implicitHeight: contentHeight
                    model: targetPicker.popup.visible ? targetPicker.delegateModel : null
                    currentIndex: targetPicker.highlightedIndex
                    ScrollBar.vertical: ScrollBar {}
                }
                background: Rectangle { color: "#24212d"; border.color: "#62547d"; radius: 5 }
            }
        }

        ScrollView {
            Layout.fillWidth: true
            Layout.preferredHeight: 78
            contentWidth: availableWidth
            clip: true
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
            ColumnLayout {
                width: parent.width
                spacing: 5
                Label { text: root.info.environment || ""; color: "#d4c8e8"; font.pixelSize: 12; Layout.fillWidth: true; wrapMode: Text.Wrap }
                Label {
                    objectName: "content-download-compatibility"
                    text: root.info.compatibility || ""
                    color: root.info.compatibilityState === "incompatible" ? "#f09a9a" : root.info.compatibilityState === "compatible" ? "#add3b6" : "#dfc18d"
                    font.pixelSize: 12; wrapMode: Text.Wrap; Layout.fillWidth: true
                    textFormat: Text.PlainText
                }
                Label {
                    text: root.info.target || ""; color: "#91869f"; font.pixelSize: 11
                    Layout.fillWidth: true; elide: Text.ElideMiddle
                    HoverHandler { id: pathHover }
                    ToolTip.visible: pathHover.hovered; ToolTip.text: text
                }
            }
        }
        Label {
            Layout.fillWidth: true
            visible: !!root.info.error
            text: root.info.error || ""
            color: "#f09a9a"
            wrapMode: Text.Wrap
            font.pixelSize: 11
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            Item { Layout.fillWidth: true }
            ActionButton { objectName: "content-download-cancel"; text: "取消"; implicitWidth: 82; implicitHeight: 34; onClicked: dialogModel.action("取消") }
            ActionButton { objectName: "content-download-confirm"; text: "确认下载"; implicitWidth: 104; implicitHeight: 34; primary: true; enabled: !!root.info.targetValid && !root.state.working; onClicked: dialogModel.action("确认下载") }
        }
    }
}
