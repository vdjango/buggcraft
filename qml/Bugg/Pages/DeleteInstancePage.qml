import QtQuick
import QtQuick.Layouts
import Bugg.DesignSystem

PageLayout {
    id: root
    required property string instanceName
    property bool permanent: true
    signal deleteRequested(bool permanent)
    PageHeader {
        Layout.fillWidth: true
        title: root.instanceName
        caption: qsTr("请选择如何处理这个实例。")
        titleSize: 16
    }
    ChoiceCard {
        Layout.fillWidth: true
        text: qsTr("永久删除本地文件")
        caption: qsTr("删除实例文件夹，无法恢复")
        iconName: "folder"
        selected: root.permanent
        onClicked: root.permanent = true
    }
    ChoiceCard {
        Layout.fillWidth: true
        text: qsTr("仅从列表移除")
        caption: qsTr("保留本地所有文件")
        iconName: "library"
        selected: !root.permanent
        onClicked: root.permanent = false
    }
    NoticeBanner {
        Layout.fillWidth: true
        text: root.permanent ? qsTr("将永久删除该实例的本地文件，包括存档、模组和设置。") : qsTr("本地文件会保留，可重新添加。")
        color: root.permanent ? DesignTokens.danger : DesignTokens.muted
    }
    ActionButton {
        Layout.fillWidth: true
        text: root.permanent ? qsTr("确认永久删除") : qsTr("确认移除记录")
        variant: root.permanent ? "danger" : "primary"
        compact: true
        onClicked: root.deleteRequested(root.permanent)
    }
}
