import QtQuick
import QtQuick.Controls
import "../shared" as Shared

ComboBox {
    id: control
    property bool tutorialHighlight: false
    readonly property bool tutorialPopupVisible: control.popup.visible
    implicitHeight: 36
    implicitWidth: 240
    font.pixelSize: 12
    contentItem: Text {
        text: control.displayText
        color: control.enabled ? "#efedf5" : "#96909f"
        font: control.font
        leftPadding: 10
        rightPadding: 24
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideMiddle
    }
    indicator: Canvas {
        x: control.width - 20; anchors.verticalCenter: parent.verticalCenter
        width: 10; height: 6
        onPaint: {
            var ctx = getContext("2d")
            ctx.fillStyle = "#d8d0ef"
            ctx.beginPath(); ctx.moveTo(0, 0); ctx.lineTo(10, 0); ctx.lineTo(5, 6); ctx.closePath(); ctx.fill()
        }
    }
    background: Rectangle {
        color: "#1a1923"
        radius: 0
        border.width: control.activeFocus || (control.popup && control.popup.visible) ? 1 : 0
        border.color: control.activeFocus || (control.popup && control.popup.visible) ? "#a99bf8" : "#625277"
    }
    Shared.AttentionFrame {
        objectName: "choice-tutorial-glow"
        active: control.tutorialHighlight
        tint: "#a99bf8"
    }
    onTutorialHighlightChanged: if (!tutorialHighlight) control.popup.close()
    delegate: ItemDelegate {
        required property int index
        required property var modelData
        objectName: "choice-option-" + index
        width: control.popup.width - 8
        height: 36
        highlighted: control.highlightedIndex === index
        contentItem: Text {
            text: modelData
            color: "#f2edf8"
            font.pixelSize: 12
            elide: Text.ElideMiddle
            verticalAlignment: Text.AlignVCenter
        }
        background: Rectangle {
            radius: 3
            color: parent.highlighted ? "#51456e" : control.currentIndex === parent.index ? "#392b58" : "transparent"
            border.color: control.currentIndex === parent.index ? "#a99bf8" : "transparent"
        }
    }
    popup: Popup {
        y: control.height + 3
        width: control.width
        padding: 4
        implicitHeight: Math.min(contentItem.implicitHeight + 8, 192)
        contentItem: ListView {
            objectName: control.objectName + "-popup"
            clip: true
            implicitHeight: count > 0 ? contentHeight : 44
            currentIndex: control.highlightedIndex
            model: control.popup.visible ? control.delegateModel : null
            ScrollBar.vertical: ScrollBar { }
            Text {
                anchors.centerIn: parent
                visible: parent.count === 0
                text: "暂无可选项"
                color: "#b4acc5"
                font.pixelSize: 12
            }
        }
        background: Rectangle {
            color: "#211f2b"; radius: 5; border.color: "#71658a"; border.width: 1
            Shared.AttentionFrame { active: control.tutorialHighlight; tint: "#a99bf8" }
        }
    }
}
