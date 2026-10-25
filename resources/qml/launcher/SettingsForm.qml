import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

ScrollView {
    id: root
    objectName: "settings-scroll"
    property var expansion: ({})
    property var memoryInfo: settingsPage.memoryInfo
    clip: true
    contentWidth: availableWidth
    ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
    ColumnLayout {
        width: root.availableWidth
        spacing: 10
        Item { Layout.preferredHeight: 5 }
        Repeater {
            model: settingsPage.groups
            delegate: SettingsSection {
                id: group
                required property var modelData
                objectName: "setting-group-" + modelData.key
                Layout.fillWidth: true
                Layout.leftMargin: 15; Layout.rightMargin: 15
                title: modelData.title
                summary: modelData.summary
                collapsible: modelData.collapsible
                inlineControl: modelData.inline
                headerVisible: modelData.kind !== "memory" && modelData.kind !== "standalone-toggle"
                expanded: root.expansion[modelData.key] === undefined ? modelData.expanded : root.expansion[modelData.key]
                onExpandedChanged: root.expansion[modelData.key] = expanded
                headerControl: modelData.inline ? inlineChoice : modelData.key === "settings.general.update" ? releases : null
                Component {
                    id: inlineChoice
                    ChoiceBox {
                        implicitWidth: 280; implicitHeight: 28
                        model: group.modelData.options.map(function(option) { return option.title })
                        currentIndex: Math.max(0, group.modelData.options.findIndex(function(option) { return option.value === group.modelData.value }))
                        enabled: group.modelData.enabled
                        onActivated: settingsPage.setValue(group.modelData.key, group.modelData.options[currentIndex].value)
                    }
                }
                Component { id: releases; ActionButton { text: "打开官网版本页"; implicitHeight: 28; onClicked: settingsPage.openReleases() } }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 10
                    RowLayout {
                        visible: group.modelData.kind === "radio-horizontal"
                        Layout.fillWidth: true
                        Repeater {
                            model: group.modelData.kind === "radio-horizontal" ? group.modelData.options : []
                            delegate: SettingOption {
                                required property var modelData
                                Layout.preferredWidth: 105
                                text: modelData.title; checked: group.modelData.value === modelData.value
                                enabled: group.modelData.enabled
                                onChosen: settingsPage.setValue(group.modelData.key, modelData.value)
                            }
                        }
                        Item { Layout.fillWidth: true }
                    }
                    Repeater {
                        model: group.modelData.kind === "radio" ? group.modelData.options : []
                        delegate: SettingOption {
                            required property var modelData
                            objectName: "setting-option-" + group.modelData.key + "-" + index
                            required property int index
                            Layout.fillWidth: true
                            text: modelData.title; description: modelData.description
                            checked: group.modelData.value === modelData.value
                            enabled: group.modelData.enabled
                            onChosen: settingsPage.setValue(group.modelData.key, modelData.value)
                        }
                    }
                    ChoiceBox {
                        visible: group.modelData.kind === "choice" && !group.modelData.inline
                        Layout.fillWidth: true; implicitHeight: 30
                        model: group.modelData.options.map(function(option) { return option.title })
                        currentIndex: Math.max(0, group.modelData.options.findIndex(function(option) { return option.value === group.modelData.value }))
                        enabled: group.modelData.enabled
                        onActivated: settingsPage.setValue(group.modelData.key, group.modelData.options[currentIndex].value)
                    }
                    SettingOption {
                        visible: ["instance", "standalone-toggle", "memory"].indexOf(group.modelData.kind) >= 0
                        objectName: "setting-toggle-" + group.modelData.key
                        Layout.fillWidth: true
                        text: group.modelData.kind === "memory" ? "自动分配内存" : group.modelData.title
                        canToggle: true
                        checked: !!group.modelData.value
                        enabled: group.modelData.enabled
                        onChosen: settingsPage.setValue(group.modelData.key, !group.modelData.value)
                    }
                    RowLayout {
                        visible: group.modelData.kind === "opacity"
                        Layout.fillWidth: true
                        spacing: 15
                        Slider {
                            id: opacitySlider
                            objectName: group.modelData.kind === "opacity" ? "setting-opacity-slider" : ""
                            Layout.fillWidth: true
                            from: 35; to: 100; stepSize: 1; snapMode: Slider.SnapAlways
                            value: group.modelData.kind === "opacity" ? group.modelData.value : 85
                            implicitHeight: 26
                            background: Rectangle {
                                x: opacitySlider.leftPadding; y: (opacitySlider.height - height) / 2
                                width: opacitySlider.availableWidth; height: 3; color: "#cc5e5d68"
                                Rectangle { width: opacitySlider.visualPosition * parent.width; height: parent.height; color: "#b37492f6" }
                            }
                            handle: Rectangle {
                                x: opacitySlider.leftPadding + opacitySlider.visualPosition * (opacitySlider.availableWidth - width)
                                y: (opacitySlider.height - height) / 2
                                width: 12; height: 12; radius: 6; color: "#cc7492f6"; border.color: "#e6ffffff"
                            }
                            onMoved: if (!pressed) settingsPage.setValue("launcher.opacity", Math.round(value))
                            onPressedChanged: if (!pressed && group.modelData.kind === "opacity") settingsPage.setValue("launcher.opacity", Math.round(value))
                        }
                        Label { Layout.preferredWidth: 42; horizontalAlignment: Text.AlignRight; text: Math.round(opacitySlider.value) + "%"; color: "#e0d9ec"; font.pixelSize: 13 }
                    }
                    ColumnLayout {
                        id: memoryBlock
                        visible: group.modelData.kind === "memory"
                        Layout.fillWidth: true
                        property var memoryField: group.modelData.memory || ({value:2048, options:[512, 4096], enabled:false})
                        spacing: 10
                        RowLayout {
                            Layout.fillWidth: true; spacing: 15
                            Label { text: "游戏内存分配"; color: "white"; font.pixelSize: 13 }
                            Slider {
                                id: memory
                                objectName: "setting-memory-slider"
                                Layout.fillWidth: true
                                from: memoryBlock.memoryField.options[0]; to: memoryBlock.memoryField.options[1]
                                stepSize: 512; snapMode: Slider.SnapAlways
                                implicitHeight: 26
                                background: Rectangle {
                                    x: memory.leftPadding; y: (memory.height - height) / 2
                                    width: memory.availableWidth; height: 3; color: "#cc5e5d68"
                                    Rectangle { width: memory.visualPosition * parent.width; height: parent.height; color: "#b37492f6" }
                                }
                                handle: Rectangle {
                                    x: memory.leftPadding + memory.visualPosition * (memory.availableWidth - width)
                                    y: (memory.height - height) / 2
                                    width: 12; height: 12; radius: 6
                                    color: "#cc7492f6"; border.color: "#e6ffffff"
                                }
                                value: memoryBlock.memoryField.value
                                enabled: memoryBlock.memoryField.enabled
                                onMoved: if (!pressed) settingsPage.setValue("memory.allocation", Math.round(value))
                                onPressedChanged: if (!pressed && enabled) settingsPage.setValue("memory.allocation", Math.round(value))
                            }
                            Label { text: Math.round(memory.value) + " MB"; color: "#e0d9ec"; font.pixelSize: 13 }
                        }
                        Rectangle {
                            Layout.fillWidth: true; implicitHeight: 12; color: "#4b526b"
                            property real usedRatio: Math.min(1, (root.memoryInfo.used || 0) / Math.max(1, root.memoryInfo.total))
                            Rectangle { height: parent.height; width: parent.width * parent.usedRatio; color: "#678aff" }
                            Rectangle { x: parent.width * parent.usedRatio; height: parent.height; width: parent.width * Math.min(1 - parent.usedRatio, memory.value / Math.max(1, root.memoryInfo.total)); color: memory.enabled ? "#ffc864" : "#aaaaaa" }
                        }
                        Label {
                            Layout.fillWidth: true
                            text: "设备中已使用 " + ((root.memoryInfo.used || 0) / 1024).toFixed(2) + " GB  |  设备总内存 " + ((root.memoryInfo.total || 0) / 1024).toFixed(2) + " GB  |  可用 " + ((root.memoryInfo.available || 0) / 1024).toFixed(2) + " GB"
                            color: "#ccc4d8"; font.pixelSize: 12; wrapMode: Text.Wrap
                        }
                    }
                    Label {
                        visible: !!group.modelData.description && group.modelData.kind !== "memory"
                        Layout.fillWidth: true
                        text: group.modelData.description; color: "#b2aabd"; font.pixelSize: 12; wrapMode: Text.Wrap
                    }
                }
            }
        }
        Item { Layout.preferredHeight: 5 }
    }
}
