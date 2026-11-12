import QtQuick
import QtQuick.Layouts
import Bugg.DesignSystem

PageLayout {
    id: root
    required property string theme
    property var backgrounds: []
    signal themeRequested(string theme)
    signal backgroundsEdited(var urls)
    ThemePicker {
        Layout.fillWidth: true
        theme: root.theme
        onThemeRequested: theme => root.themeRequested(theme)
    }
    SettingRow {
        objectName: "backgroundPickerRow"
        Layout.fillWidth: true
        text: qsTr("启动背景")
        value: root.backgrounds.length ? root.backgrounds.length + qsTr(" 张 · 自动轮播") : qsTr("默认轮播 · 更换图片")
        onClicked: imagePicker.open()
    }
    ActionButton {
        objectName: "resetBackgroundButton"
        visible: root.backgrounds.length > 0
        text: qsTr("恢复默认背景")
        variant: "ghost"
        compact: true
        onClicked: root.backgroundsEdited([])
    }
    FilePicker {
        id: imagePicker
        objectName: "backgroundFilePicker"
        title: qsTr("选择启动背景（可多选）")
        multiple: true
        nameFilters: [qsTr("图片 (*.png *.jpg *.jpeg *.webp)")]
        onFilesChosen: urls => root.backgroundsEdited(urls)
    }
}
