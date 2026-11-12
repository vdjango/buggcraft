import QtQuick
import QtQuick.Layouts

// 一个分配滑块；预算由原生环境服务给出，页面不另算物理上限。
ColumnLayout {
    id: root
    property bool automatic: true
    property int memoryMB: 4096
    property int automaticMemoryMB: 1024
    property int totalMB: 0
    property int availableMB: 0
    property int maximumMB: 1024
    readonly property int allocationMB: Math.min(maximumMB, automatic ? automaticMemoryMB : memoryMB)
    signal automaticEdited(bool value)
    signal memoryEdited(int value)
    spacing: 16
    RowLayout {
        Layout.fillWidth: true
        CheckOption {
            objectName: "automaticMemoryOption"
            Layout.fillWidth: true
            text: qsTr("自动分配内存")
            checked: root.automatic
            onToggled: root.automaticEdited(checked)
        }
        InputField {
            objectName: "memoryValueField"
            Layout.preferredWidth: 90
            visible: !root.automatic
            text: (root.allocationMB / 1024).toFixed(2).replace(/0+$/, "").replace(/\.$/, "")
            inputMethodHints: Qt.ImhFormattedNumbersOnly
            validator: DoubleValidator {
                bottom: 0.5
                top: root.maximumMB / 1024
                decimals: 2
                locale: "C"
            }
            onEditingFinished: {
                if (acceptableInput)
                    root.memoryEdited(Math.min(root.maximumMB, Math.max(512, Math.round(Number(text) * 1024 / 256) * 256)));
                text = Qt.binding(() => (root.allocationMB / 1024).toFixed(2).replace(/0+$/, "").replace(/\.$/, ""));
            }
        }
        UiText {
            visible: root.automatic
            text: (root.allocationMB / 1024).toFixed(1)
            font.pixelSize: 21
            font.weight: Font.DemiBold
        }
        UiText {
            text: "GiB"
            color: DesignTokens.muted
            font.pixelSize: 12
        }
    }
    ValueSlider {
        objectName: "memorySlider"
        Layout.fillWidth: true
        visible: !root.automatic
        from: 512
        to: Math.max(768, root.maximumMB)
        stepSize: 256
        value: root.allocationMB
        enabled: !root.automatic && root.maximumMB > 512
        onEdited: value => root.memoryEdited(Math.min(root.maximumMB, Math.round(value)))
        Accessible.name: qsTr("游戏内存")
    }
    RowLayout {
        Layout.fillWidth: true
        UiText {
            Layout.fillWidth: true
            text: qsTr("可用 %1 GiB").arg((root.availableMB / 1024).toFixed(1))
            color: DesignTokens.muted
            font.pixelSize: 12
        }
        UiText {
            text: qsTr("可分配上限 %1 GiB").arg((root.maximumMB / 1024).toFixed(1))
            color: DesignTokens.muted
            font.pixelSize: 12
        }
    }
}
