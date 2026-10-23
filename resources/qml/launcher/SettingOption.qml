import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

RadioButton {
    id: control
    property string description: ""
    property bool canToggle: false
    signal chosen()
    autoExclusive: false
    implicitHeight: 30
    implicitWidth: 220
    padding: 3
    onClicked: chosen()
    indicator: Rectangle {
        x: 3; y: (control.height - height) / 2
        width: 30; height: 30; color: "transparent"
        opacity: control.enabled ? 1 : 0.5
        Image { anchors.centerIn: parent; width: 20; height: 20; source: "../../images/version/" + (control.checked ? "selected1.png" : "not-selected1.png") }
    }
    contentItem: Item {
        implicitWidth: 220; implicitHeight: 30
        RowLayout {
            anchors.fill: parent; anchors.leftMargin: 35
            spacing: 5
            Label { Layout.maximumWidth: 220; text: control.text; color: control.enabled ? "#ffffff" : "#aba5b6"; font.pixelSize: 13; elide: Text.ElideRight }
            Item { Layout.fillWidth: !control.description }
            Label { objectName: control.objectName + "-description"; Layout.fillWidth: true; Layout.minimumWidth: 0; Layout.maximumWidth: 400; text: control.description; visible: !!text; color: "#888888"; font.pixelSize: 12; horizontalAlignment: Text.AlignRight; elide: Text.ElideMiddle }
        }
    }
}
