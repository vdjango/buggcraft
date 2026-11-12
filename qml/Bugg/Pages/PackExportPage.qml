pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import Bugg.DesignSystem

PageLayout {
    id: root
    required property string instanceName
    property bool compactPack: true
    signal exportRequested(string url, bool compact, bool saves)
    maximumWidth: 640
    SelectField {
        objectName: "packFormatSelector"
        Layout.fillWidth: true
        label: qsTr("导出格式")
        selection: root.compactPack ? "compact" : "full"
        options: [
            {
                id: "compact",
                name: qsTr("精简包"),
                caption: ".buggpack"
            },
            {
                id: "full",
                name: qsTr("完整包"),
                caption: ".buggpack"
            }
        ]
        onChosen: id => root.compactPack = id === "compact"
    }
    UiText {
        Layout.fillWidth: true
        text: root.compactPack ? qsTr("可下载的资源保留链接，其余文件放入包内。") : qsTr("包含模组、资源和配置。")
        color: DesignTokens.muted
        wrapMode: Text.Wrap
    }
    CheckOption {
        id: saves
        text: qsTr("包含存档")
    }
    ActionButton {
        Layout.alignment: Qt.AlignRight
        text: qsTr("选择位置并导出")
        onClicked: destination.open()
    }
    FilePicker {
        id: destination
        objectName: "packExportFilePicker"
        saveMode: true
        title: qsTr("导出整合包")
        nameFilters: ["Buggcraft (*.buggpack)"]
        defaultSuffix: "buggpack"
        suggestedName: root.instanceName + ".buggpack"
        onFilesChosen: urls => {
            if (urls.length)
                root.exportRequested(urls[0], root.compactPack, saves.checked);
        }
    }
}
