import QtQuick
import QtQuick.Controls

Dialog {
    id: control
    modal: true
    focus: true
    palette.window: "#211f2b"
    palette.windowText: "#efedf5"
    palette.text: "#efedf5"
    palette.button: "#302a40"
    palette.buttonText: "#efedf5"
    palette.highlight: "#7859ff"
    background: Rectangle { color: "#211f2b"; border.color: "#8b85da"; radius: 6 }
    header: Label {
        text: control.title
        visible: text.length > 0
        padding: 14
        color: "#f2edf8"
        font.pixelSize: 15
        font.bold: true
        elide: Text.ElideRight
        background: Rectangle { color: "#2c273c"; radius: 6 }
    }
}
