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
    function revealTutorialTarget(targetName) {
        for (var i = 0; i < settingsGroups.count; ++i) {
            var section = settingsGroups.itemAt(i)
            if (section && (targetName === "setting-group-" + section.modelData.key ||
                            targetName === (section.modelData.key === "game.language" ? "setting-select-game-language" : "setting-select-" + section.modelData.key) ||
                            targetName === "setting-toggle-" + section.modelData.key))
                section.expanded = true
        }
        Qt.callLater(function() {
            function find(item) {
                if (item.objectName === targetName && item.visible && item.width > 0 && item.height > 0)
                    return item
                for (var j = 0; j < item.children.length; ++j) {
                    var match = find(item.children[j])
                    if (match) return match
                }
                return null
            }
            var control = find(root.contentItem)
            if (!control) return
            var position = control.mapToItem(root.contentItem.contentItem, 0, 0)
            var top = position.y - 16
            var bottom = position.y + control.height + 16
            var flick = root.contentItem
            var maximum = Math.max(0, flick.contentHeight - flick.height)
            if (top < flick.contentY || bottom > flick.contentY + flick.height)
                flick.contentY = Math.max(0, Math.min(maximum, top - (flick.height - control.height) / 2))
        })
    }
    Connections {
        target: settingsPage
        function onTutorialTargetRequested(targetName) { root.revealTutorialTarget(targetName) }
    }
    ColumnLayout {
        width: root.availableWidth
        spacing: 10
        Item { Layout.preferredHeight: 5 }
        Repeater {
            id: settingsGroups
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
                        objectName: "setting-select-" + group.modelData.key
                        implicitWidth: 280; implicitHeight: 28
                        model: group.modelData.options.map(function(option) { return option.title })
                        currentIndex: Math.max(0, group.modelData.options.findIndex(function(option) { return option.value === group.modelData.value }))
                        enabled: group.modelData.enabled
                        onActivated: settingsPage.setValue(group.modelData.key, group.modelData.options[currentIndex].value)
                    }
                }
                Component {
                    id: releases
                    RowLayout {
                        spacing: 8
                        ActionButton {
                            objectName: "launcher-check-updates"
                            text: settingsPage.updateBusy ? "正在处理…" : "检查更新"
                            enabled: !settingsPage.updateBusy
                            implicitHeight: 28
                            onClicked: settingsPage.checkUpdates()
                        }
                        ActionButton { text: "官网版本页"; implicitHeight: 28; onClicked: settingsPage.openReleases() }
                    }
                }
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
                                objectName: "launcher-update-channel-" + modelData.value
                                Layout.preferredWidth: 105
                                text: modelData.title; checked: group.modelData.value === modelData.value
                                enabled: group.modelData.enabled
                                onChosen: settingsPage.setValue(group.modelData.key, modelData.value)
                            }
                        }
                        Item { Layout.fillWidth: true }
                    }
                    Label {
                        objectName: "launcher-update-status"
                        visible: group.modelData.key === "settings.general.update"
                        Layout.fillWidth: true
                        text: "当前版本：" + settingsPage.currentVersion + "  ·  " + settingsPage.updateStatus
                        color: "#cce5e5ee"
                        font.pixelSize: 12
                        elide: Text.ElideRight
                        HoverHandler { id: updateStatusHover }
                        ToolTip.visible: updateStatusHover.hovered
                        ToolTip.text: text
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
                            onChosen: {
                                if (group.modelData.key === "multiplayer.quick_action") tutorial.action("quick_action")
                                settingsPage.setValue(group.modelData.key, modelData.value)
                            }
                        }
                    }
                    ChoiceBox {
                        objectName: group.modelData.kind === "choice" && !group.modelData.inline ? (group.modelData.key === "game.language" ? "setting-select-game-language" : "setting-select-" + group.modelData.key) : ""
                        visible: group.modelData.kind === "choice" && !group.modelData.inline
                        Layout.fillWidth: true; implicitHeight: 30
                        tutorialHighlight: group.modelData.key === "game.language" && typeof tutorial !== "undefined" && tutorial.demoStep === "language"
                        model: group.modelData.options.map(function(option) { return option.title })
                        currentIndex: Math.max(0, group.modelData.options.findIndex(function(option) { return option.value === group.modelData.value }))
                        enabled: group.modelData.enabled
                        onActivated: {
                            var key = group.modelData.key
                            var value = group.modelData.options[currentIndex].value
                            if (key === "game.language") tutorial.action("language")
                            settingsPage.setValue(key, value)
                        }
                    }
                    Loader {
                        Layout.fillWidth: true
                        active: group.modelData.kind === "source-priority"
                        visible: active
                        sourceComponent: Component {
                        ColumnLayout {
                        spacing: 8
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 12
                            SettingOption {
                                objectName: group.modelData.kind === "source-priority" ? "content-source-manual" : ""
                                Layout.fillWidth: true
                                text: "按顺序尝试"
                                checked: !group.modelData.automatic
                                onChosen: settingsPage.setContentAutomatic(false)
                            }
                            SettingOption {
                                objectName: group.modelData.kind === "source-priority" ? "content-source-auto" : ""
                                Layout.fillWidth: true
                                text: "自动测速"
                                checked: !!group.modelData.automatic
                                onChosen: settingsPage.setContentAutomatic(true)
                            }
                        }
                        Repeater {
                            model: group.modelData.kind === "source-priority" ? group.modelData.priorities : []
                            delegate: Rectangle {
                                required property var modelData
                                required property int index
                                objectName: "content-source-row-" + modelData.source
                                Layout.fillWidth: true
                                implicitHeight: 64
                                color: index === 0 ? "#413c335b" : "#30241f35"
                                border.width: 1
                                border.color: index === 0 ? "#8a73bd" : "#50465f"
                                radius: 6
                                opacity: group.modelData.automatic ? 0.6 : 1
                                RowLayout {
                                    anchors.fill: parent
                                    anchors.margins: 10
                                    spacing: 10
                                    Rectangle {
                                        Layout.preferredWidth: 28; Layout.preferredHeight: 28
                                        radius: 5; color: index === 0 ? "#8063c6" : "#42394f"
                                        Label { anchors.centerIn: parent; text: index + 1; color: "white"; font.bold: true }
                                    }
                                    ColumnLayout {
                                        Layout.fillWidth: true; spacing: 3
                                        Label {
                                            Layout.fillWidth: true
                                            text: modelData.source + (index === 0 ? "  ·  优先" : "")
                                            color: "#f0e9fa"; font.pixelSize: 13; font.bold: true
                                        }
                                        Label {
                                            Layout.fillWidth: true
                                            text: modelData.description
                                            color: modelData.source === "MCIM" || modelData.source === "Modrinth" ? "#d7c294" : "#b9aecb"
                                            font.pixelSize: 11; elide: Text.ElideRight
                                        }
                                    }
                                    ActionButton {
                                        objectName: "content-source-up-" + modelData.source
                                        text: "上移"; implicitWidth: 52; implicitHeight: 28
                                        enabled: !group.modelData.automatic && index > 0
                                        onClicked: settingsPage.moveContentSource(index, -1)
                                    }
                                    ActionButton {
                                        objectName: "content-source-down-" + modelData.source
                                        text: "下移"; implicitWidth: 52; implicitHeight: 28
                                        enabled: !group.modelData.automatic && index + 1 < group.modelData.priorities.length
                                        onClicked: settingsPage.moveContentSource(index, 1)
                                    }
                                }
                            }
                        }
                        SettingOption {
                            objectName: group.modelData.kind === "source-priority" ? "content-source-include-mcim" : ""
                            Layout.fillWidth: true
                            text: "加入 MCIM 备选（不推荐）"
                            canToggle: true
                            checked: !!group.modelData.mcim
                            enabled: !group.modelData.automatic
                            onChosen: settingsPage.setContentMcim(!group.modelData.mcim)
                        }
                        }
                        }
                    }
                    SettingOption {
                        visible: ["instance", "standalone-toggle", "memory"].indexOf(group.modelData.kind) >= 0
                        objectName: "setting-toggle-" + group.modelData.key
                        Layout.fillWidth: true
                        text: group.modelData.kind === "memory" ? "自动分配内存" : group.modelData.title
                        canToggle: true
                        checked: !!group.modelData.value
                        enabled: group.modelData.enabled
                        onChosen: {
                            var key = group.modelData.key
                            var value = !group.modelData.value
                            if (key === "translation.enabled") tutorial.action("translation")
                            if (key === "multiplayer.quick_action") tutorial.action("quick_action")
                            settingsPage.setValue(key, value)
                        }
                    }
                    RowLayout {
                        visible: group.modelData.kind === "opacity"
                        Layout.fillWidth: true
                        spacing: 15
                        Slider {
                            id: opacitySlider
                            focusPolicy: Qt.StrongFocus
                            objectName: group.modelData.kind === "opacity" ? "setting-opacity-slider" : ""
                            Layout.fillWidth: true
                            from: 35; to: 100; stepSize: 1; snapMode: Slider.SnapAlways
                            value: group.modelData.kind === "opacity" ? settingsPage.sliderValues.opacity : 85
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
                            Layout.fillWidth: true; spacing: 14
                            Label { objectName: group.modelData.kind === "memory" ? "setting-memory-label" : ""; Layout.preferredWidth: 130; text: "游戏内存分配"; color: "white"; font.pixelSize: 13 }
                            Slider {
                                id: memory
                                focusPolicy: Qt.StrongFocus
                                objectName: group.modelData.kind === "memory" ? "setting-memory-slider" : ""
                                Layout.fillWidth: true
                                from: memoryBlock.memoryField.options[0]
                                to: Math.max(from, root.memoryInfo.total > 0 ? root.memoryInfo.total - 1024 : memoryBlock.memoryField.options[1])
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
                                value: settingsPage.sliderValues.memory
                                enabled: memoryBlock.memoryField.enabled
                                onMoved: if (!pressed) settingsPage.setValue("memory.allocation", Math.round(value))
                                onPressedChanged: if (!pressed && enabled) settingsPage.setValue("memory.allocation", Math.round(value))
                            }
                            Label { Layout.preferredWidth: 76; horizontalAlignment: Text.AlignRight; text: (memory.value / 1024).toFixed(1) + " GB"; color: "#e0d9ec"; font.pixelSize: 13 }
                        }
                        Rectangle {
                            objectName: group.modelData.kind === "memory" ? "setting-memory-bar" : ""
                            Layout.fillWidth: true; implicitHeight: 10; color: "#4b526b"
                            property real usedRatio: Math.min(1, (root.memoryInfo.used || 0) / Math.max(1, root.memoryInfo.total))
                            Rectangle { height: parent.height; width: parent.width * parent.usedRatio; color: "#678aff" }
                            Rectangle { x: parent.width * parent.usedRatio; height: parent.height; width: parent.width * Math.min(1 - parent.usedRatio, memory.value / Math.max(1, root.memoryInfo.total)); color: memory.enabled ? "#ffc864" : "#aaaaaa" }
                        }
                        Label {
                            objectName: group.modelData.kind === "memory" ? "setting-memory-info" : ""
                            Layout.fillWidth: true
                            text: root.memoryInfo.total > 0
                                  ? "电脑共 " + (root.memoryInfo.total / 1024).toFixed(0) + " GB，目前可用 " + (root.memoryInfo.available / 1024).toFixed(1) + " GB。建议开启自动分配，内存并非越大越好。"
                                  : "正在读取系统内存信息…"
                            color: "#ccc4d8"; font.pixelSize: 12; wrapMode: Text.Wrap
                        }
                    }
                    Label {
                        objectName: "setting-description-" + group.modelData.key
                        visible: !!group.modelData.description && group.modelData.kind !== "memory" && group.modelData.key !== "settings.general.update"
                        Layout.fillWidth: true
                        text: group.modelData.description; color: "#b2aabd"; font.pixelSize: 12; wrapMode: Text.Wrap
                    }
                    RowLayout {
                        property var sourceField: group.modelData.translationSource || ({title: "", options: [], value: "", enabled: false})
                        visible: group.modelData.key === "translation.enabled" && !!group.modelData.value
                        Layout.fillWidth: true
                        spacing: 14
                        Label {
                            Layout.preferredWidth: 130
                            text: parent.sourceField.title
                            color: "white"; font.pixelSize: 13
                        }
                        ChoiceBox {
                            objectName: group.modelData.key === "translation.enabled" ? "setting-select-translation.source" : ""
                            Layout.fillWidth: true
                            model: parent.sourceField.options
                            currentIndex: Math.max(0, parent.sourceField.options.indexOf(parent.sourceField.value))
                            enabled: parent.sourceField.enabled
                            onActivated: settingsPage.setValue("translation.source", parent.sourceField.options[currentIndex])
                            HoverHandler { id: translationSourceHover }
                            ToolTip.visible: translationSourceHover.hovered
                            ToolTip.text: parent.sourceField.description || ""
                        }
                    }
                }
            }
        }
        Item { Layout.preferredHeight: 5 }
    }
}
