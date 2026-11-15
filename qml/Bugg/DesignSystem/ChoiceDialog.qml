pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Reusable modal choice presentation. The caller owns state and side effects.
ModalSurface {
    id: root
    property string title: ""
    property string message: ""
    property string errorText: ""
    property var options: []
    property bool busy: false
    property bool requireReading: false
    property bool readComplete: false
    signal chosen(string value)
    padding: 20
    height: Math.min(implicitHeight, maximumDialogHeight)
    onVisibleChanged: if (visible && requireReading) {
        readComplete = false;
        const view = messageScroll.contentItem as Flickable;
        if (view)
            view.contentY = 0;
        Qt.callLater(() => {
            if (root.visible && messageLabel.implicitHeight <= messageScroll.availableHeight + 1)
                root.readComplete = true;
        });
    }
    contentItem: ColumnLayout {
        spacing: 12
        UiText {
            Layout.fillWidth: true
            text: root.title
            color: DesignTokens.neutralText
            font.pixelSize: 17
            font.bold: true
            wrapMode: Text.Wrap
        }
        ScrollView {
            id: messageScroll
            objectName: "choiceMessageScroll"
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 0
            Layout.preferredHeight: root.requireReading ? Math.min(290, root.maximumDialogHeight * 0.42) : Math.min(messageLabel.implicitHeight, root.maximumDialogHeight * 0.45)
            clip: true
            contentWidth: availableWidth
            contentHeight: messageLabel.implicitHeight
            rightPadding: 14
            UiText {
                id: messageLabel
                width: messageScroll.availableWidth
                text: root.message
                color: DesignTokens.neutralText
                wrapMode: Text.Wrap
                elide: Text.ElideNone
                textFormat: Text.PlainText
            }
            ScrollBar.vertical: ScrollBar {
                id: messageBar
                objectName: "choiceVerticalScrollBar"
                parent: messageScroll
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                anchors.right: parent.right
                orientation: Qt.Vertical
                width: 6
                policy: root.requireReading ? ScrollBar.AlwaysOn : ScrollBar.AsNeeded
                minimumSize: 0.12
                active: true
                contentItem: Rectangle {
                    implicitWidth: 6
                    radius: 3
                    color: DesignTokens.neutralAccent
                    opacity: messageBar.pressed ? 1 : 0.65
                }
                background: Rectangle {
                    implicitWidth: 6
                    radius: 3
                    color: DesignTokens.neutralWash
                }
            }
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
            Connections {
                target: messageScroll.contentItem
                function onContentYChanged() {
                    const view = messageScroll.contentItem as Flickable;
                    if (root.visible && view && view.contentHeight > view.height && view.contentY + view.height >= view.contentHeight - 1)
                        root.readComplete = true;
                }
            }
        }
        UiText {
            objectName: "agreementScrollHint"
            Layout.fillWidth: true
            visible: root.requireReading
            text: root.readComplete ? qsTr("已阅读完毕，请选择是否同意") : qsTr("↓ 下方还有内容，请向下滚动阅读")
            color: root.readComplete ? DesignTokens.success : DesignTokens.neutralAccent
            font.pixelSize: 12
            wrapMode: Text.Wrap
        }
        NoticeBanner {
            Layout.fillWidth: true
            visible: !!root.errorText
            text: root.errorText
            color: DesignTokens.warning
        }
        Repeater {
            model: root.options
            ActionButton {
                required property var modelData
                objectName: "choiceOption_" + modelData.id
                Layout.fillWidth: true
                Layout.maximumWidth: Number.POSITIVE_INFINITY
                text: modelData.name
                variant: modelData.variant || "outline"
                neutral: true
                enabled: !root.busy && (modelData.enabled === undefined || modelData.enabled)
                onClicked: root.chosen(modelData.id)
            }
        }
    }
}
