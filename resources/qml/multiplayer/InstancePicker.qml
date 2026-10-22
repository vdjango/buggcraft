import QtQuick
import QtQuick.Layouts

ColumnLayout {
    property var vm: lobby.view
    spacing: 4
    RowLayout {
        Layout.fillWidth: true; spacing: 8
        CopyText { text: "游戏配置"; color: "#d8d5f0"; font.pixelSize:11 }
        ChoiceBox {
            objectName: "instance-picker"
            Layout.fillWidth: true
            model: vm.instances
            displayText: vm.instanceId || "选择已安装的游戏"
            currentIndex: vm.instances.indexOf(vm.instanceId)
            enabled: !vm.instanceLocked && !vm.instanceLoading && vm.instances.length > 0
            onActivated: lobby.act("selectInstance", {id: currentText})
        }
    }
    CopyText {
        Layout.fillWidth: true; font.pixelSize: 11
        text: vm.instanceLoading ? "正在读取游戏信息…" : vm.instanceError ||
            (vm.instanceLocked ? "使用正在运行的游戏版本；退出游戏后可切换。" :
            vm.version ? "与首页同步 · " + vm.version + " · " + (vm.loader === "vanilla" ? "原版" : vm.loader + " " + vm.loaderVersion) :
            vm.instances.length ? "与首页共用选择，版本和模组自动读取。" : "还没有已安装实例，请先到首页下载或导入游戏。")
        color: vm.instanceError ? "#ffc2bd" : "#aaa8c5"
    }
}
