pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// 可搜索选择器：options 为 id/name/caption/group，group 为不可选标题；selection 归调用方。
ColumnLayout {
    id: root
    property string label: ""
    property var options: []
    property string selection: ""
    property string placeholderText: qsTr("请选择")
    property string searchPlaceholder: qsTr("搜索")
    property bool busy: false
    property bool showSelectedCaption: true
    property bool compact: false
    property real popupWidth: 0
    signal chosen(string id)
    // mapToItem is evaluated after layout, when the popup actually opens.
    // A binding evaluated while an ancestor is still collapsed keeps stale coordinates.
    function positionPopup() {
        if (!dropdown.parent)
            return;
        const anchor = control.mapToItem(dropdown.parent, 0, 0);
        dropdown.x = Math.max(4, Math.min(anchor.x, dropdown.parent.width - dropdown.width - 4));
        dropdown.y = anchor.y + control.height + dropdown.height + 4 <= dropdown.parent.height ? anchor.y + control.height + 4 : Math.max(4, anchor.y - dropdown.height - 4);
    }
    spacing: 8
    UiText {
        visible: root.label.length > 0
        text: root.label
        color: DesignTokens.text
        font.pixelSize: DesignTokens.comfortable ? 13 : 11
    }
    ComboBox {
        id: control
        objectName: root.objectName + "Control"
        Layout.fillWidth: true
        implicitHeight: root.compact ? 30 : DesignTokens.controlHeight
        hoverEnabled: true
        enabled: root.options.length > 0
        model: root.options
        textRole: "name"
        valueRole: "id"
        currentIndex: root.options.findIndex(item => item.id === root.selection)
        displayText: currentIndex >= 0 ? (root.options[currentIndex].shortName || root.options[currentIndex].name) + (root.showSelectedCaption && root.options[currentIndex].caption ? " · " + qsTr(root.options[currentIndex].caption) : "") : root.busy ? qsTr("正在获取…") : root.placeholderText
        leftPadding: root.compact ? 10 : 14
        rightPadding: root.compact ? 26 : 36
        onActivated: index => root.chosen(root.options[index].id)
        background: InteractiveSurface {
            control: control
            animateFeedback: false
            restingColor: DesignTokens.surface
            hoverColor: DesignTokens.surfaceHover
            border.width: 1
            border.color: control.activeFocus ? DesignTokens.quiet : DesignTokens.controlBorder
        }
        contentItem: UiText {
            text: control.displayText
            color: control.enabled ? DesignTokens.text : DesignTokens.muted
            verticalAlignment: Text.AlignVCenter
            font.pixelSize: root.compact ? 12 : DesignTokens.comfortable ? 14 : 12
        }
        indicator: AppIcon {
            x: control.width - width - (root.compact ? 8 : 14)
            y: (control.height - height) / 2
            width: 12
            height: 12
            name: "chevron"
            rotation: 90
            color: DesignTokens.muted
        }
        popup: Popup {
            id: dropdown
            objectName: root.objectName + "Popup"
            parent: Overlay.overlay
            width: Math.min(parent ? parent.width - 8 : 400, Math.max(control.width, root.popupWidth))
            padding: 6
            height: Math.min(300, parent ? parent.height - 8 : 300, Math.max(64, list.contentHeight + (search.visible ? search.implicitHeight + 18 : 12)))
            closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
            onOpened: {
                root.positionPopup();
                search.clear();
                if (search.visible)
                    search.forceActiveFocus();
                else
                    list.forceActiveFocus();
            }
            onHeightChanged: {
                if (opened)
                    root.positionPopup();
            }
            onWidthChanged: {
                if (opened)
                    root.positionPopup();
            }
            background: Surface {
                color: DesignTokens.elevated
                borderColor: DesignTokens.controlBorder
                borderWidth: 1
            }
            contentItem: ColumnLayout {
                spacing: 6
                InputField {
                    id: search
                    objectName: "versionSearchField"
                    visible: root.options.length > 8
                    Layout.fillWidth: true
                    placeholderText: root.searchPlaceholder
                    leadingIcon: "compass"
                    onAccepted: {
                        if (list.count > 0) {
                            root.chosen(list.model[0].id);
                            dropdown.close();
                        }
                    }
                }
                ListView {
                    id: list
                    objectName: "versionOptionsList"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    spacing: 2
                    model: root.options.filter(item => (item.name + " " + (item.caption || "") + " " + (item.group || "")).toLowerCase().includes(search.text.trim().toLowerCase()))
                    ScrollBar.vertical: ScrollBar {}
                    delegate: Column {
                        id: option
                        required property var modelData
                        required property int index
                        width: list.width
                        UiText {
                            objectName: root.objectName + "Group_" + (option.modelData.group || "")
                            visible: !!option.modelData.group && (option.index === 0 || list.model[option.index - 1].group !== option.modelData.group)
                            width: parent.width
                            text: option.modelData.group || ""
                            topPadding: 12
                            bottomPadding: 5
                            leftPadding: 10
                            font.pixelSize: DesignTokens.comfortable ? 12 : 11
                            font.weight: Font.DemiBold
                            color: DesignTokens.muted
                        }
                        ListRow {
                            objectName: root.objectName + "Option_" + option.modelData.id
                            x: option.modelData.group ? 12 : 0
                            width: parent.width - x
                            implicitHeight: caption.length ? DesignTokens.detailedRowHeight : DesignTokens.controlHeight
                            iconName: ""
                            text: option.modelData.name
                            caption: qsTr(option.modelData.caption || "")
                            selected: option.modelData.id === root.selection
                            showChevron: false
                            onClicked: {
                                root.chosen(option.modelData.id);
                                dropdown.close();
                            }
                        }
                    }
                }
            }
        }
    }
}
