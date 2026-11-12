import QtQuick
import QtQuick.Layouts
import Bugg.DesignSystem

PageLayout {
    id: root
    required property string instanceName
    property int choice: 0
    signal noticeRequested(string message)
    UiText {
        Layout.fillWidth: true
        text: qsTr("已存在同名实例：") + root.instanceName
        wrapMode: Text.WordWrap
        font.pixelSize: DesignTokens.comfortable ? 15 : 13
        font.weight: Font.DemiBold
    }
    ChoiceCard {
        Layout.fillWidth: true
        text: qsTr("换个名称")
        iconName: "plus"
        caption: qsTr("保留已有实例")
        selected: root.choice === 0
        onClicked: root.choice = 0
    }
    FormField {
        visible: root.choice === 0
        Layout.fillWidth: true
        label: qsTr("新实例名称")
        text: root.instanceName + " (2)"
    }
    ChoiceCard {
        Layout.fillWidth: true
        text: qsTr("继续未完成的安装")
        iconName: "download"
        caption: qsTr("核对文件，只补齐缺失内容")
        selected: root.choice === 1
        onClicked: root.choice = 1
    }
    ActionButton {
        Layout.fillWidth: true
        text: qsTr("继续")
        compact: true
        onClicked: root.noticeRequested(qsTr("交互预览 · 实例安装服务尚未接入，未修改本地文件"))
    }
}
