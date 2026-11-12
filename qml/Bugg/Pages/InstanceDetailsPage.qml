import QtQuick
import QtQuick.Layouts
import Bugg.DesignSystem

PageLayout {
    id: root
    required property var instance
    signal openRequested(string route)
    signal noticeRequested(string message)
    SettingRow {
        Layout.fillWidth: true
        text: qsTr("模组与资源")
        value: qsTr("管理")
        onClicked: root.openRequested("instanceFiles")
    }
    SettingRow {
        Layout.fillWidth: true
        text: "Java"
        value: qsTr("自动选择")
        onClicked: root.openRequested("java")
    }
    SettingRow {
        Layout.fillWidth: true
        text: qsTr("导出整合包")
        onClicked: root.openRequested("exportPack")
    }
    SettingRow {
        Layout.fillWidth: true
        text: qsTr("实例设置")
        value: qsTr("内存")
        onClicked: root.openRequested("instanceSettings")
    }
    Divider {
        Layout.fillWidth: true
    }
    ActionButton {
        text: qsTr("移除或删除实例")
        variant: "ghost"
        compact: true
        onClicked: root.openRequested("deleteInstance")
    }
}
