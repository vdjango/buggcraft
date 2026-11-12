import QtQuick
import QtQuick.Layouts
import Bugg.DesignSystem

PageLayout {
    id: root
    property int concurrency: 6
    property string sourceSummary: "BUGG"
    signal concurrencyEdited(int value)
    signal openRequested(string route)
    SelectField {
        objectName: "concurrencySelector"
        Layout.fillWidth: true
        label: qsTr("同时下载数量")
        selection: String(root.concurrency)
        options: [1, 2, 4, 6, 8, 16, 32].map(value => ({
                    id: String(value),
                    name: String(value)
                }))
        onChosen: value => root.concurrencyEdited(Number(value))
    }
    SettingRow {
        objectName: "downloadSourcesRow"
        Layout.fillWidth: true
        text: qsTr("来源优先级")
        value: root.sourceSummary
        onClicked: root.openRequested("sources")
    }
}
