import QtQuick
import QtQuick.Layouts

ColumnLayout {
    property var vm: lobby.view
    spacing: 12
    CopyText { Layout.fillWidth: true; text: "在游戏里重新对局域网开放，再选择世界。房间和邀请码会保留。" }
    RowLayout {
        Layout.fillWidth: true
        CopyText { Layout.fillWidth: true; text: "本机开放的世界"; font.bold: true; color: "#eee8fb" }
        ActionButton { objectName: "rediscover-worlds"; text: vm.busy ? "查找中…" : "重新查找"; enabled: !vm.busy; onClicked: lobby.act("discover", {}) }
    }
    Repeater {
        model: vm.worlds
        delegate: ActionButton {
            required property var modelData
            required property int index
            objectName: "resume-world-" + index
            Layout.fillWidth: true; enabled: !vm.busy
            text: modelData.version + " · 端口 " + modelData.port + "     使用这个世界"
            onClicked: lobby.act("applyWorld", {port:modelData.port})
        }
    }
    CopyText { Layout.fillWidth: true; text: "没有找到时，填写游戏显示的端口"; font.pixelSize: 12 }
    RowLayout {
        Layout.fillWidth: true
        InputField { id: port; objectName: "resume-world-port"; Layout.fillWidth: true; placeholderText: "例如 51234"; maximumLength: 5; validator: IntValidator { bottom: 1; top: 65535 } }
        ActionButton { objectName: "resume-world-submit"; text: "恢复联机"; primary: true; enabled: port.acceptableInput && !vm.busy; onClicked: lobby.act("applyWorld", {port:Number(port.text)}) }
    }
    Item { Layout.fillHeight: true }
}
