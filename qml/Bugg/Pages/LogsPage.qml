pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Bugg.DesignSystem

Item {
    id: root
    property var runtime: null
    property real viewportHeight: 420
    readonly property var exportStatus: runtime ? runtime.diagnostics_status : ({})
    readonly property var journal: runtime ? runtime.debug_log : ({})
    property string selectedModule: ""
    property string selectedLevel: ""
    property string selectedLogger: ""
    property bool following: true
    property var selectedEntry: null
    implicitHeight: viewportHeight
    signal noticeRequested(string message)
    function refresh() {
        if (!visible)
            return;
        if (journal.busy) {
            debounce.restart();
            return;
        }
        if (runtime)
            runtime.refresh_debug_log(selectedModule, selectedLevel, search.text, selectedLogger);
    }
    Component.onCompleted: refresh()
    onVisibleChanged: if (visible)
        refresh()
    Timer {
        interval: 1500
        running: root.visible && root.following
        repeat: true
        onTriggered: root.refresh()
    }
    Timer {
        id: debounce
        interval: 300
        onTriggered: root.refresh()
    }
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 8
        spacing: 6
        RowLayout {
            Layout.fillWidth: true
            InputField {
                id: search
                Layout.fillWidth: true
                objectName: "debugLogSearch"
                placeholderText: qsTr("搜索日志、模组或错误")
                onTextChanged: debounce.restart()
            }
            ActionButton {
                objectName: "debugLogFollow"
                text: root.following ? qsTr("暂停") : qsTr("跟随")
                compact: true
                onClicked: {
                    root.following = !root.following;
                    if (root.following) {
                        events.positionViewAtEnd();
                        root.refresh();
                    }
                }
            }
            IconButton {
                objectName: "debugLogRefresh"
                iconName: "refresh"
                accessibleName: qsTr("刷新日志")
                enabled: !root.journal.busy
                onClicked: root.refresh()
            }
        }
        RowLayout {
            Layout.fillWidth: true
            SelectField {
                Layout.fillWidth: true
                Layout.preferredWidth: 90
                objectName: "debugLogModule"
                compact: true
                options: [
                    {
                        id: "",
                        name: qsTr("全部来源")
                    }
                ].concat((root.journal.modules || []).map(value => ({
                            id: value,
                            name: ({
                                    game: qsTr("游戏"),
                                    installer: qsTr("安装器"),
                                    download: qsTr("下载"),
                                    http: qsTr("网络")
                                })[value] || value
                        })))
                selection: root.selectedModule
                onChosen: id => {
                    root.selectedModule = id;
                    root.refresh();
                }
            }
            SelectField {
                Layout.fillWidth: true
                Layout.preferredWidth: 80
                objectName: "debugLogLevel"
                compact: true
                options: [
                    {
                        id: "",
                        name: qsTr("全部级别")
                    }
                ].concat(["TRACE", "DEBUG", "INFO", "WARN", "ERROR", "FATAL"].map(value => ({
                            id: value,
                            name: value
                        })))
                selection: root.selectedLevel
                onChosen: id => {
                    root.selectedLevel = id;
                    root.refresh();
                }
            }
            SelectField {
                Layout.fillWidth: true
                Layout.preferredWidth: 150
                objectName: "debugLogLogger"
                compact: true
                options: [
                    {
                        id: "",
                        name: qsTr("模组 / Tag")
                    }
                ].concat((root.journal.loggers || []).map(value => ({
                            id: value,
                            name: value
                        })))
                selection: root.selectedLogger
                onChosen: id => {
                    root.selectedLogger = id;
                    root.refresh();
                }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            UiText {
                Layout.preferredWidth: DesignTokens.comfortable ? 88 : 54
                text: qsTr("时间")
                font.pixelSize: 10
                color: DesignTokens.muted
            }
            UiText {
                Layout.preferredWidth: 39
                text: qsTr("级别")
                font.pixelSize: 10
                color: DesignTokens.muted
            }
            UiText {
                Layout.preferredWidth: DesignTokens.comfortable ? 125 : 65
                text: qsTr("模组 / Tag")
                font.pixelSize: 10
                color: DesignTokens.muted
            }
            UiText {
                Layout.fillWidth: true
                text: qsTr("消息")
                font.pixelSize: 10
                color: DesignTokens.muted
            }
        }
        Divider {
            Layout.fillWidth: true
        }
        ListView {
            id: events
            objectName: "debugLogEntries"
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 96
            clip: true
            spacing: 0
            model: root.journal.entries || []
            onCountChanged: if (root.following)
                positionViewAtEnd()
            onMovementStarted: root.following = false
            ScrollBar.vertical: ScrollBar {}
            UiText {
                anchors.centerIn: parent
                width: parent.width - 16
                horizontalAlignment: Text.AlignHCenter
                visible: events.count === 0
                text: root.journal.error || qsTr("暂无匹配日志，可调整筛选或等待新记录。")
                color: DesignTokens.muted
                wrapMode: Text.Wrap
            }
            delegate: LogRow {
                required property var modelData
                objectName: "debugLogRow"
                width: events.width - 12
                entry: modelData
                narrow: !DesignTokens.comfortable
                selected: root.selectedEntry === modelData
                onClicked: {
                    root.selectedEntry = modelData;
                    root.following = false;
                }
            }
        }
        Divider {
            Layout.fillWidth: true
        }
        UiText {
            Layout.fillWidth: true
            text: root.selectedEntry ? [root.selectedEntry.time, root.selectedEntry.level, root.selectedEntry.mod || root.selectedEntry.logger || root.selectedEntry.module, root.selectedEntry.thread].filter(Boolean).join(" · ") : qsTr("选择一条日志，查看并复制完整消息与堆栈")
            color: DesignTokens.muted
            font.pixelSize: 10
        }
        ScrollView {
            Layout.fillWidth: true
            Layout.preferredHeight: DesignTokens.comfortable ? 100 : 88
            visible: root.selectedEntry !== null
            clip: true
            TextAreaField {
                objectName: "debugLogDetail"
                width: parent.width
                readOnly: true
                flat: true
                padding: 2
                text: root.selectedEntry ? root.selectedEntry.message || "" : ""
                textFormat: Text.PlainText
                wrapMode: TextEdit.WrapAnywhere
                font.family: "Consolas, monospace"
                font.pixelSize: 11
            }
        }
        RowLayout {
            Layout.fillWidth: true
            UiText {
                Layout.fillWidth: true
                text: root.journal.busy ? qsTr("正在读取…") : qsTr("%1 条 · 最近 500 条 · %2").arg(events.count).arg(root.following ? qsTr("跟随") : qsTr("已暂停"))
                color: DesignTokens.muted
                font.pixelSize: 10
            }
            ActionButton {
                objectName: "exportDiagnosticsButton"
                text: root.exportStatus.busy ? qsTr("导出中…") : qsTr("导出日志")
                enabled: root.runtime !== null && !root.runtime.loading_instances && !root.exportStatus.busy
                iconName: "download"
                variant: "soft"
                compact: true
                onClicked: destination.open()
            }
        }
        UiText {
            Layout.fillWidth: true
            visible: !!root.exportStatus.path || !!root.exportStatus.error
            text: root.exportStatus.error || root.exportStatus.path || ""
            color: root.exportStatus.error ? DesignTokens.danger : DesignTokens.muted
            wrapMode: Text.WrapAnywhere
            elide: Text.ElideNone
        }
    }
    FilePicker {
        id: destination
        objectName: "diagnosticsFilePicker"
        saveMode: true
        title: qsTr("导出诊断日志")
        nameFilters: ["ZIP (*.zip)"]
        defaultSuffix: "zip"
        suggestedName: "Bugg-diagnostics-" + Qt.formatDateTime(new Date(), "yyyyMMdd-HHmmss") + ".zip"
        onFilesChosen: urls => {
            if (urls.length && root.runtime)
                root.runtime.export_diagnostics(urls[0]);
        }
    }
}
