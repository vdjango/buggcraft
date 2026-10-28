import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root
    property var entries: []
    property int currentIndex: 0
    property string resourceBase: ""
    signal activated(int index)
    implicitWidth: 199
    Column {
        anchors.top: parent.top; anchors.topMargin: 20
        anchors.left: parent.left; anchors.leftMargin: 12
        width: 155
        spacing: 0
        Rectangle { width: parent.width; height: 2; color: "#8b85da" }
        Item { width: 1; height: 10 }
        Repeater {
            model: root.entries
            delegate: Button {
                required property int index
                required property string modelData
                objectName: "navigation-option-" + index
                width: 155; height: 44
                text: modelData
                background: Item {
                    Image {
                        anchors.fill: parent
                        source: root.currentIndex === index ? root.resourceBase + "images/user/external_tab_btn_active.png" : ""
                        visible: root.currentIndex === index
                    }
                }
                contentItem: Text { text: modelData; color: "#ffffff"; font.pixelSize: 13; font.weight: Font.DemiBold; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                onClicked: root.activated(index)
            }
        }
    }
}
