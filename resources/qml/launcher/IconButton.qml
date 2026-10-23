import QtQuick
import QtQuick.Controls.Basic

Button {
    id: control
    property url source
    implicitWidth: 30; implicitHeight: 30
    ToolTip.visible: hovered
    ToolTip.text: text
    Accessible.name: text
    background: Item {}
    contentItem: Item {
        Image { anchors.centerIn: parent; width: 16; height: 16; source: control.source; opacity: control.enabled ? 1 : 0.5 }
    }
}
