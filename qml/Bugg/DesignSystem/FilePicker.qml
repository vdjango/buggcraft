import QtQuick
import QtQuick.Dialogs
import QtCore

// 通用本地文件入口：输入标题/筛选/多选；只在确认后输出 URL，不读文件或保存设置。
FileDialog {
    id: root
    property bool multiple: false
    property bool saveMode: false
    property bool available: true
    // 保存对话框提供建议文件名；目录由系统负责，允许输入尚不存在的目标文件。
    property string suggestedName: ""
    signal filesChosen(var urls)
    fileMode: saveMode ? FileDialog.SaveFile : multiple ? FileDialog.OpenFiles : FileDialog.OpenFile
    currentFolder: StandardPaths.writableLocation(StandardPaths.DocumentsLocation)
    // 仅保存模式绑定目标；普通打开窗口不能赋空路径，否则 Qt 会尝试校验不存在的文件。
    // 原生窗口显示前提供默认目标；visibleChanged 已晚于系统对话框创建。
    Binding {
        target: root
        property: "selectedFile"
        when: root.saveMode && root.suggestedName.length > 0
        value: root.currentFolder + "/" + encodeURIComponent(root.suggestedName)
        restoreMode: Binding.RestoreNone
    }
    onAvailableChanged: {
        if (!available)
            close();
    }
    onAccepted: filesChosen(selectedFiles.map(url => url.toString()))
}
