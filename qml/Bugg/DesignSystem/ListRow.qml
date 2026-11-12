import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

AbstractButton {
    id: root
    // leadingComponent 为头像/世界图标插槽；列表绘制与反馈仍由本组件统一负责。
    property string caption: ""
    property string value: ""
    property string iconName: "folder"
    property bool selected: false
    property bool hoverFeedbackEnabled: true
    property bool animateFeedback: false
    property bool compact: false
    property bool faded: false
    property real fadeOpacity: 0.1
    property color backdropTint: "#243D44"
    property bool showChevron: true
    property bool showSelectionMark: true
    property bool showTrailing: true
    property Component leadingComponent: null
    property Component trailingComponent: null
    property real leadingSize: compact ? 30 : DesignTokens.comfortable ? 40 : 32
    implicitHeight: compact ? DesignTokens.rowHeight : DesignTokens.detailedRowHeight
    hoverEnabled: true
    padding: compact ? 8 : 10
    Accessible.name: text + "，" + caption
    background: InteractiveSurface {
        control: root
        radius: 10
        selected: root.selected
        hoverFeedbackEnabled: root.hoverFeedbackEnabled
        animateFeedback: root.animateFeedback
        faded: root.faded
        fadeOpacity: root.fadeOpacity
        backdropTint: root.backdropTint
        hoverColor: root.palette.button
        selectedColor: root.palette.light
        pressedColor: root.palette.midlight
    }
    contentItem: RowLayout {
        spacing: 12
        AppIcon {
            visible: !root.leadingComponent && root.iconName.length > 0
            name: root.iconName
            implicitWidth: 22
            implicitHeight: 22
            color: root.selected ? root.palette.highlight : root.palette.placeholderText
        }
        Loader {
            active: !!root.leadingComponent
            visible: active
            Layout.preferredWidth: root.leadingSize
            Layout.preferredHeight: root.leadingSize
            sourceComponent: root.leadingComponent
        }
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 5
            UiText {
                Layout.fillWidth: true
                text: root.text
                horizontalAlignment: root.mirrored ? Text.AlignRight : Text.AlignLeft
                color: root.palette.text
                font.pixelSize: DesignTokens.comfortable ? 15 : 12
                font.weight: Font.DemiBold
            }
            UiText {
                Layout.fillWidth: true
                text: root.caption
                horizontalAlignment: root.mirrored ? Text.AlignRight : Text.AlignLeft
                visible: root.caption.length > 0
                color: root.faded ? root.palette.text : root.palette.placeholderText
                font.pixelSize: DesignTokens.comfortable ? 12 : 10
            }
        }
        UiText {
            visible: root.value.length > 0
            text: root.value
            font.pixelSize: 10
            color: root.faded ? root.palette.text : root.palette.placeholderText
        }
        Loader {
            active: !!root.trailingComponent && root.showTrailing
            visible: active
            sourceComponent: root.trailingComponent
        }
        AppIcon {
            visible: root.showChevron || (root.selected && root.showSelectionMark)
            name: root.selected && root.showSelectionMark ? "check" : "chevron"
            implicitWidth: 12
            implicitHeight: 12
            color: root.palette.mid
        }
    }
}
