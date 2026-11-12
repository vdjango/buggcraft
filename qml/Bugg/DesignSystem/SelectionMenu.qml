pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// 通用选择弹层：items 为 id/name/caption/initials 快照；不保存业务选择或执行服务。
Popup {
    id: root
    property var items: []
    property string selectedId: ""
    property string emptyText: qsTr("暂无可选项")
    property string actionText: ""
    property bool available: true
    signal chosen(string id)
    signal actionRequested
    width: 236
    padding: 8
    margins: 8
    focus: true
    // 中性半透明浮层保留背景层次；文字不继承场景白字，避免自选背景影响阅读。
    palette.window: DesignTokens.floatingSurface
    palette.text: DesignTokens.neutralText
    palette.windowText: DesignTokens.neutralText
    palette.buttonText: DesignTokens.neutralText
    palette.placeholderText: DesignTokens.neutralMuted
    palette.button: DesignTokens.floatingHover
    palette.midlight: DesignTokens.floatingSelection
    palette.light: DesignTokens.floatingSelection
    palette.mid: DesignTokens.quiet
    palette.highlight: DesignTokens.neutralAccent
    onAvailableChanged: {
        if (!available)
            close();
    }
    implicitHeight: Math.min(360, choices.implicitHeight + topPadding + bottomPadding)
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    background: Surface {
        color: root.palette.window
        borderColor: DesignTokens.controlBorder
        borderWidth: 1
    }
    contentItem: ScrollView {
        clip: true
        contentWidth: availableWidth
        ColumnLayout {
            id: choices
            width: parent.width
            spacing: 2
            Repeater {
                model: root.items
                ListRow {
                    id: choice
                    required property var modelData
                    objectName: "profileChoice_" + modelData.id
                    Layout.fillWidth: true
                    implicitHeight: modelData.initials ? 60 : 44
                    iconName: ""
                    text: modelData.name
                    caption: qsTr(modelData.caption || "")
                    selected: modelData.id === root.selectedId
                    showChevron: false
                    leadingSize: 30
                    leadingComponent: modelData.initials ? choiceAvatar : null
                    Component {
                        id: choiceAvatar
                        Avatar {
                            initials: choice.modelData.initials || "?"
                            tint: choice.palette.highlight
                        }
                    }
                    onClicked: {
                        root.close();
                        root.chosen(modelData.id);
                    }
                }
            }
            UiText {
                visible: root.items.length === 0 && root.actionText.length === 0
                Layout.fillWidth: true
                Layout.margins: 12
                text: root.emptyText
                color: root.palette.placeholderText
                font.pixelSize: 12
            }
            Divider {
                Layout.fillWidth: true
                visible: root.actionText.length > 0 && root.items.length > 0
            }
            ActionButton {
                objectName: "profileManageButton"
                Layout.fillWidth: true
                Layout.maximumWidth: Number.POSITIVE_INFINITY
                visible: root.actionText.length > 0
                text: root.actionText
                compact: true
                variant: "ghost"
                onClicked: {
                    root.close();
                    root.actionRequested();
                }
            }
        }
    }
}
