import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

RowLayout {
    id: root
    property string address: ""
    visible: address.length > 0
    spacing: 6
    Label { text: "下载源："; color: "#b6a8c6"; font.pixelSize: 11 }
    Label {
        objectName: root.objectName + "-text"
        Layout.fillWidth: true; Layout.minimumWidth: 0
        Layout.preferredHeight: 20; padding: 0
        text: root.address
        elide: Text.ElideRight; textFormat: Text.PlainText
        color: "#d1c3e9"; font.pixelSize: 11
        Accessible.name: "当前下载源"
        ToolTip.visible: addressHover.hovered
        ToolTip.text: root.address
        HoverHandler { id: addressHover }
    }
}
