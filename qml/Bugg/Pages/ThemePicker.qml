import QtQuick
import Bugg.DesignSystem

SelectField {
    id: root
    objectName: "themeSelector"
    required property string theme
    signal themeRequested(string theme)
    label: qsTr("窗口尺寸")
    selection: theme
    options: [
        {
            id: "panel",
            name: qsTr("悬浮面板")
        },
        {
            id: "small",
            name: qsTr("紧凑窗口")
        },
        {
            id: "classic",
            name: qsTr("标准窗口")
        },
        {
            id: "large",
            name: qsTr("宽屏窗口")
        }
    ]
    onChosen: value => root.themeRequested(value)
}
