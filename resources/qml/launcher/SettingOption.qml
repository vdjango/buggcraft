import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

RadioButton {
    id: control
    property string description: ""
    property bool canToggle: false
    signal chosen()
    // Radio choices must always keep exactly one selected. Only explicit
    // standalone toggles may be switched off.
    autoExclusive: !canToggle
    implicitHeight: 34
    implicitWidth: 220
    leftPadding: 32
    rightPadding: 0
    topPadding: 5
    bottomPadding: 5
    onClicked: chosen()
    indicator: Rectangle {
        objectName: control.objectName + "-indicator"
        x: 0; y: (control.height - height) / 2
        width: 20; height: 20; color: "transparent"
        opacity: control.enabled ? 1 : 0.5
        Image { anchors.centerIn: parent; width: 20; height: 20; source: "../../images/version/" + (control.checked ? "selected1.png" : "not-selected1.png") }
    }
    contentItem: RowLayout {
        spacing: 16
        Label {
            objectName: control.objectName + "-label"
            Layout.fillWidth: true; Layout.minimumWidth: 0
            text: control.text; color: control.enabled ? "#ffffff" : "#aba5b6"
            font.pixelSize: 13; elide: Text.ElideRight
        }
        Label {
            objectName: control.objectName + "-description"
            Layout.preferredWidth: Math.min(implicitWidth, control.availableWidth * 0.64)
            Layout.minimumWidth: 0
            text: control.description; visible: !!text; color: "#aaa2b7"; font.pixelSize: 12
            horizontalAlignment: Text.AlignRight; elide: Text.ElideMiddle
            HoverHandler { id: descriptionHover }
            ToolTip.visible: descriptionHover.hovered && truncated
            ToolTip.text: text
        }
    }
}
