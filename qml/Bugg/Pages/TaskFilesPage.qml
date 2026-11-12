import QtQuick
import QtQuick.Layouts
import Bugg.DesignSystem

PageLayout {
    id: root
    signal noticeRequested(string message)
    ProgressItem {
        Layout.fillWidth: true
        title: qsTr("客户端核心 · 示例文件")
        state: qsTr("已完成")
        caption: qsTr("下载源：BMCLAPI · 哈希校验通过")
        progress: 1
    }
    ProgressItem {
        Layout.fillWidth: true
        title: qsTr("cataclysm.jar · 示例文件")
        state: qsTr("等待补齐")
        caption: qsTr("下载源：Bugg · 来源暂不可用，保留已下载进度")
        progress: 0.32
    }
    ActionButton {
        Layout.fillWidth: true
        text: qsTr("只重试未完成文件")
        compact: true
        onClicked: root.noticeRequested(qsTr("交互预览 · 下载服务尚未接入"))
    }
}
