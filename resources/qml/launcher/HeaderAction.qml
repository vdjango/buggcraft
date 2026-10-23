import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Button {
    id: control
    property url artwork
    property url leadingIcon
    property url trailingIcon
    property bool selected: false
    property bool expanded: false
    implicitWidth: 125; implicitHeight: 32
    padding: 0
    hoverEnabled: true
    background: Item {
        Image { anchors.fill: parent; source: control.artwork; smooth: false }
        Rectangle {
            anchors.fill: parent; anchors.margins: 5
            color: control.selected ? "#806e63ff" : control.down ? "#504b426e" : control.hovered ? "#304b426e" : "transparent"
            border.color: control.activeFocus ? "#c2b7ff" : "transparent"
        }
    }
    contentItem: Item {
      RowLayout {
        objectName: control.objectName + "-content"
        anchors.centerIn: parent
        width: Math.min(implicitWidth, parent.width - 20)
        spacing: 5
        Image { visible: !!control.leadingIcon.toString(); source: control.leadingIcon; Layout.preferredWidth: 20; Layout.preferredHeight: 20; fillMode: Image.PreserveAspectFit }
        Text {
            objectName: control.objectName + "-label"
            Layout.fillWidth: true; Layout.maximumWidth: implicitWidth; text: control.text; color: "#f2f2f2"
            font.pixelSize: 13; font.bold: true; elide: Text.ElideMiddle
            horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
        }
        Image {
            visible: !!control.trailingIcon.toString(); source: control.trailingIcon
            Layout.preferredWidth: 12; Layout.preferredHeight: 12; fillMode: Image.PreserveAspectFit
            rotation: control.expanded ? 180 : 0
        }
      }
    }
    HoverHandler { cursorShape: Qt.PointingHandCursor }
    Accessible.name: text
}
