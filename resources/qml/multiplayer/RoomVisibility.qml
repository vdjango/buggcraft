import QtQuick
import QtQuick.Controls.Basic

CheckBox {
    id: control
    implicitHeight: 30
    spacing: 12
    indicator: Rectangle {
        x: 0; y: (control.height - height) / 2
        width: 18; height: 18
        color: control.checked ? "#7859ef" : "#181923"
        border.color: control.activeFocus ? "#dbceff" : "#89729f"
        CopyText { anchors.centerIn: parent; text: "✓"; visible: control.checked; color: "white"; font.pixelSize: 16 }
    }
    contentItem: CopyText { leftPadding: 27; text: control.text; color: "#e9e0f7"; font.pixelSize: 12; verticalAlignment: Text.AlignVCenter }
}
