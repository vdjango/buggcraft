import QtQuick
import QtQuick.Layouts
import Bugg.DesignSystem

PageLayout {
    id: root
    property var service: null
    property var runtime: null
    readonly property var status: service ? service.status : ({})
    signal noticeRequested(string message)
    spacing: 16
    maximumWidth: 700
    SelectField {
        objectName: "launcherUpdateChannel"
        Layout.fillWidth: true
        label: qsTr("更新渠道")
        selection: root.runtime ? root.runtime.preferences.updateChannel || "beta" : root.status.channel || "beta"
        enabled: !!root.runtime && !["downloading", "ready"].includes(root.status.state)
        options: [
            {
                id: "beta",
                name: qsTr("开发版")
            },
            {
                id: "stable",
                name: qsTr("稳定版")
            }
        ]
        onChosen: value => root.runtime.set_preference("updateChannel", value)
    }
    UiText {
        Layout.fillWidth: true
        text: qsTr("开发版接收最新改进，也接收稳定版更新；稳定版仅接收正式更新。")
        font.pixelSize: 12
        color: DesignTokens.muted
        wrapMode: Text.Wrap
    }
    Surface {
        Layout.fillWidth: true
        implicitHeight: productGroup.implicitHeight + 40
        padding: 20
        ColumnLayout {
            id: productGroup
            anchors.fill: parent
            spacing: 20
            RowLayout {
                Layout.fillWidth: true
                spacing: 12
                Avatar {
                    initials: "B"
                    implicitWidth: 48
                    implicitHeight: 48
                }
                PageHeader {
                    Layout.fillWidth: true
                    title: "Bugg"
                    caption: qsTr("和朋友一起开玩。")
                    titleSize: 24
                }
            }
            LoadingIndicator {
                visible: root.status.state === "checking"
                text: qsTr("正在检查更新…")
            }
            UiText {
                Layout.fillWidth: true
                visible: root.status.state === "available" && root.status.automaticPackage === false
                text: qsTr("此版本尚未提供原生整包，请到下载站查看。")
                font.pixelSize: 12
                color: DesignTokens.muted
                wrapMode: Text.Wrap
            }
            ProgressItem {
                Layout.fillWidth: true
                visible: root.status.state === "downloading"
                title: qsTr("启动器更新")
                progress: root.status.progress === undefined ? -1 : root.status.progress
                caption: root.status.detail || ""
            }
            RowLayout {
                Layout.fillWidth: true
                UiText {
                    objectName: "launcherUpdateStatus"
                    Layout.fillWidth: true
                    visible: root.status.state !== "checking"
                    text: root.status.state === "latest" ? qsTr("已是最新版本") : root.status.state === "available" ? qsTr("发现新版本 %1").arg(root.status.version) : root.status.state === "ready" ? qsTr("更新已下载，重启即可安装") : root.status.state === "error" ? root.status.error || qsTr("检查更新失败，请重试") : root.status.state === "downloading" ? qsTr("正在下载并校验更新") : qsTr("启动时自动检查更新")
                    color: root.status.state === "error" ? DesignTokens.danger : DesignTokens.text
                    wrapMode: Text.Wrap
                }
                ActionButton {
                    objectName: "checkLauncherUpdateButton"
                    text: qsTr("检查更新")
                    compact: true
                    variant: "soft"
                    enabled: !!root.service && !["checking", "downloading", "ready"].includes(root.status.state)
                    onClicked: root.service.check()
                }
                ActionButton {
                    objectName: "installLauncherUpdateButton"
                    visible: ["available", "ready"].includes(root.status.state)
                    text: root.status.state === "ready" ? qsTr("重启并安装") : root.status.automaticPackage ? qsTr("下载更新") : qsTr("前往下载站")
                    compact: true
                    onClicked: {
                        if (root.status.state === "ready")
                            root.service.install();
                        else if (root.status.automaticPackage)
                            root.service.download();
                        else
                            Qt.openUrlExternally("https://download.bugg.icu");
                    }
                }
                ActionButton {
                    visible: root.status.state === "downloading"
                    text: qsTr("取消")
                    variant: "ghost"
                    compact: true
                    onClicked: root.service.cancel()
                }
            }
            UiText {
                Layout.fillWidth: true
                visible: !!root.status.notes && ["available", "ready"].includes(root.status.state)
                text: root.status.notes || ""
                wrapMode: Text.Wrap
                maximumLineCount: 8
                font.pixelSize: 12
                color: DesignTokens.muted
            }
        }
    }
    SettingRow {
        Layout.fillWidth: true
        text: qsTr("官方网站")
        value: "bugg.icu"
        onClicked: Qt.openUrlExternally("https://bugg.icu")
    }
    SettingRow {
        Layout.fillWidth: true
        text: qsTr("微信入群")
        value: "junsi223"
        onClicked: root.noticeRequested(qsTr("微信：junsi223"))
    }
    SettingRow {
        Layout.fillWidth: true
        text: qsTr("QQ 群")
        value: "849362477"
        onClicked: root.noticeRequested(qsTr("QQ 群：849362477"))
    }
}
