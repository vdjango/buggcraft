import QtQuick
import QtQuick.Layouts
import Bugg.DesignSystem

PageLayout {
    id: root
    objectName: "gameSettingsPage"
    property var configuration: ({})
    property var environment: ({})
    property bool instanceSpecific: false
    signal settingEdited(string key, var value)
    signal resetRequested
    signal openRequested(string route)
    maximumWidth: 700
    spacing: DesignTokens.comfortable ? 20 : 12
    UiText {
        text: qsTr("内存")
        font.weight: Font.DemiBold
        font.pixelSize: 14
    }
    MemoryControl {
        Layout.fillWidth: true
        automatic: root.configuration.automatic !== false
        memoryMB: root.configuration.memoryMB || 4096
        automaticMemoryMB: root.configuration.automaticMemoryMB || root.environment.automaticMemoryMB || 1024
        maximumMB: root.environment.maximumMemoryMB || 1024
        totalMB: root.environment.totalMB || 0
        availableMB: root.environment.availableMB || 0
        onAutomaticEdited: value => root.settingEdited("automatic", value)
        onMemoryEdited: value => root.settingEdited("memoryMB", value)
    }
    Divider {
        Layout.fillWidth: true
    }
    UiText {
        text: qsTr("显示")
        font.weight: Font.DemiBold
        font.pixelSize: 14
    }
    SelectField {
        objectName: "displayModeSelector"
        Layout.fillWidth: true
        label: qsTr("显示模式")
        selection: root.configuration.fullscreen === true ? "fullscreen" : root.configuration.resolution || "1280x720"
        options: [
            {
                id: "fullscreen",
                name: qsTr("全屏")
            }
        ].concat(["854x480", "1280x720", "1600x900", "1920x1080", "2560x1440"].map(value => ({
                    id: value,
                    name: qsTr("窗口") + " · " + value.replace("x", " × ")
                })))
        onChosen: value => {
            if (value !== "fullscreen")
                root.settingEdited("resolution", value);
            root.settingEdited("fullscreen", value === "fullscreen");
        }
    }
    Divider {
        Layout.fillWidth: true
    }
    SettingRow {
        Layout.fillWidth: true
        text: qsTr("Java 运行环境")
        iconName: "chevron"
        value: root.configuration.javaPath ? qsTr("指定 Java") : qsTr("自动选择")
        onClicked: root.openRequested("java")
    }
    ActionButton {
        objectName: "resetGameSettingsButton"
        Layout.alignment: Qt.AlignLeft
        visible: root.instanceSpecific && root.configuration.overridden === true
        text: qsTr("恢复全局设置")
        variant: "ghost"
        compact: true
        onClicked: root.resetRequested()
    }
}
