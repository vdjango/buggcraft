import QtQuick
import QtQuick.Dialogs

// 与 FilePicker 一致的确认式目录选择；不扫描、不迁移文件。
FolderDialog {
    id: root
    signal directoryChosen(string path)
    onAccepted: directoryChosen(selectedFolder.toString())
}
