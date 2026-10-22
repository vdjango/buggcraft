import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Rectangle {
    id: header
    height: 42
    color: "#251f30"
    property string title: ""
    property bool navigationVisible: false
    property string navigationText: "‹"
    property string navigationName: "返回"
    property string navigationObjectName: "back-hall"
    property bool navigationDanger: false
    property string closeName: "关闭窗口"
    property string closeObjectName: "close-window"
    property string minimizeName: "最小化"
    signal navigate()
    signal minimize()
    signal closeRequested()
    signal dragRequested()

    MouseArea { anchors.fill: parent; onPressed: header.dragRequested() }
    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 12; anchors.rightMargin: 6
        spacing: 8
        HeaderAction {
            objectName: header.navigationObjectName
            visible: header.navigationVisible
            text: header.navigationText
            label: header.navigationName
            danger: header.navigationDanger
            backArrow: header.navigationText === "‹"
            iconSize: 13
            onClicked: header.navigate()
        }
        CopyText {
            objectName: "window-page-title"
            Layout.fillWidth: true
            text: header.title
            font.pixelSize: 14; font.weight: Font.DemiBold
            color: "#eee8fa"
            wrapMode: Text.NoWrap; elide: Text.ElideRight
        }
        HeaderAction {
            objectName: "minimize-window"
            text: "−"; label: header.minimizeName
            onClicked: header.minimize()
        }
        HeaderAction {
            objectName: header.closeObjectName
            text: "×"; label: header.closeName
            onClicked: header.closeRequested()
        }
    }
}
