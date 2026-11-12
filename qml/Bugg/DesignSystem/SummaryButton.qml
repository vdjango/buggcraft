import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

AbstractButton {
    id: root
    property string caption: ""
    property bool expanded: false
    property bool centered: false
    property int titleSize: 14
    property int titleWeight: Font.DemiBold
    property bool feedbackEnabled: true
    property bool frosted: false
    property real fadeOpacity: 0.2
    property color backdropTint: "#243D44"
    Behavior on backdropTint {
        ColorAnimation {
            duration: 420
        }
    }
    property string iconName: ""
    padding: frosted ? 20 : 0
    implicitHeight: 45
    hoverEnabled: true
    background: InteractiveSurface {
        control: root
        visible: root.feedbackEnabled || root.frosted
        restingColor: "transparent"
        faded: root.frosted
        fadeOpacity: root.fadeOpacity
        backdropTint: root.backdropTint
        hoverFeedbackEnabled: root.feedbackEnabled
        radius: 14
    }
    contentItem: ColumnLayout {
        spacing: 5
        RowLayout {
            Layout.alignment: root.centered ? Qt.AlignHCenter : Qt.AlignLeft
            spacing: 8
            AppIcon {
                visible: root.iconName.length > 0
                name: root.iconName
                implicitWidth: 22
                implicitHeight: 22
                color: DesignTokens.text
            }
            UiText {
                Layout.maximumWidth: Math.max(0, root.availableWidth - (root.iconName.length ? 62 : 24))
                text: root.text
                font.pixelSize: root.titleSize
                font.weight: root.titleWeight
                elide: Text.ElideRight
            }
            AppIcon {
                implicitWidth: 11
                implicitHeight: 11
                name: "down"
                color: DesignTokens.muted
                rotation: root.expanded ? 180 : 0
                Behavior on rotation {
                    NumberAnimation {
                        duration: 180
                        easing.type: Easing.OutCubic
                    }
                }
            }
        }
        UiText {
            Layout.alignment: root.centered ? Qt.AlignHCenter : Qt.AlignLeft
            Layout.maximumWidth: root.availableWidth
            text: root.caption
            visible: text.length > 0
            font.pixelSize: DesignTokens.comfortable ? 13 : 10
            color: DesignTokens.muted
            elide: Text.ElideRight
        }
    }
}
