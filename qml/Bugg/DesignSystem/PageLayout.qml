import QtQuick
import QtQuick.Layouts

Item {
    id: root
    default property alias content: column.data
    property int spacing: DesignTokens.comfortable ? 22 : 14
    property real maximumWidth: 560
    property real minimumHeight: 0
    property bool centered: false
    property real verticalPadding: DesignTokens.comfortable ? 24 : 16
    property real horizontalPadding: DesignTokens.comfortable ? 32 : 20
    implicitHeight: Math.max(minimumHeight, column.implicitHeight + verticalPadding * 2)
    ColumnLayout {
        id: column
        x: (parent.width - width) / 2
        y: root.centered ? (parent.height - height) / 2 : root.verticalPadding
        width: Math.min(root.maximumWidth, parent.width - root.horizontalPadding * 2)
        spacing: root.spacing
    }
}
