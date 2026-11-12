pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Dense diagnostic row. Selection and native input feedback share the existing surface.
AbstractButton {
    id: root
    required property var entry
    property bool selected: false
    property bool narrow: false
    readonly property color severityColor: entry.level === "FATAL" || entry.level === "ERROR" ? DesignTokens.danger : entry.level === "WARN" ? DesignTokens.warning : DesignTokens.text
    implicitHeight: 27
    padding: 4
    hoverEnabled: true
    Accessible.name: [entry.time, entry.level, entry.mod || entry.logger || entry.module, entry.message].join(" ")
    background: InteractiveSurface {
        control: root
        radius: 0
        selected: root.selected
    }
    contentItem: RowLayout {
        spacing: 8
        UiText {
            Layout.preferredWidth: root.narrow ? 54 : 88
            text: (root.entry.time || "").split("T").pop().slice(0, root.narrow ? 8 : 12)
            font.family: "Consolas, monospace"
            font.pixelSize: 10
            color: DesignTokens.muted
        }
        UiText {
            Layout.preferredWidth: 39
            text: root.entry.level || "INFO"
            font.family: "Consolas, monospace"
            font.pixelSize: 10
            color: root.severityColor
        }
        UiText {
            Layout.preferredWidth: root.narrow ? 65 : 125
            text: root.entry.mod || root.entry.logger || root.entry.module || "—"
            font.pixelSize: 11
            color: DesignTokens.muted
        }
        UiText {
            Layout.fillWidth: true
            text: (root.entry.message || "").split("\n")[0]
            textFormat: Text.PlainText
            font.family: "Consolas, monospace"
            font.pixelSize: 11
            color: root.severityColor
        }
    }
}
