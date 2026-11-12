import QtQuick
import QtQuick.Controls

AbstractButton {
    id: root
    property bool docked: false
    signal moveRequested
    objectName: "brandButton"
    implicitWidth: 27
    implicitHeight: 29
    hoverEnabled: true
    Accessible.name: docked ? qsTr("收起到屏幕边缘") : "Bugg"
    background: InteractiveSurface {
        control: root
        restingColor: DesignTokens.accentWash
    }
    contentItem: UiText {
        text: "B"
        font.family: "Segoe UI"
        font.pixelSize: 18
        font.weight: Font.Black
        color: DesignTokens.accent
        horizontalAlignment: Text.AlignHCenter
    }
    DragHandler {
        target: null
        onActiveChanged: if (active)
            root.moveRequested()
    }
}
