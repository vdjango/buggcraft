pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import Bugg.DesignSystem

PageLayout {
    id: root
    property var service: null
    property var status: service ? service.status : ({})
    property real viewportHeight: 460
    property string queryText: ""
    property string inviteText: ""
    property string loginOrigin: ""
    property int pageIndex: 0
    readonly property bool ready: status.state === "ready"
    readonly property var rooms: status.rooms || []
    signal edited(string key, var value)
    signal openRequested(string route)
    maximumWidth: 1040
    minimumHeight: DesignTokens.comfortable || !ready ? viewportHeight : 0
    centered: !ready
    spacing: 12
    Component.onCompleted: {
        if (service && ready)
            service.refresh(queryText);
    }
    NodeLogin {
        Layout.alignment: Qt.AlignHCenter
        Layout.fillWidth: true
        Layout.maximumWidth: 360
        visible: !root.ready
        status: root.status
        onLoginRequested: {
            if (root.service)
                root.service.login(root.loginOrigin);
        }
        onSettingsRequested: root.openRequested("multiplayerSettings")
        onLogoutRequested: {
            if (root.service)
                root.service.logout();
        }
    }
    ColumnLayout {
        visible: root.ready
        Layout.fillWidth: true
        Layout.preferredHeight: DesignTokens.comfortable ? Math.max(0, root.viewportHeight - root.verticalPadding * 2) : -1
        spacing: root.spacing
        GridLayout {
            visible: root.ready
            Layout.fillWidth: true
            columns: DesignTokens.comfortable ? 3 : 2
            columnSpacing: 6
            rowSpacing: 8
            InputField {
                objectName: "roomSearchField"
                visible: true
                Layout.fillWidth: true
                Layout.columnSpan: DesignTokens.comfortable ? 1 : 2
                Layout.minimumWidth: 0
                Layout.preferredWidth: DesignTokens.comfortable ? 0 : Math.max(0, root.width - 40)
                placeholderText: qsTr("搜索房间")
                leadingIcon: "compass"
                text: root.queryText
                onTextEdited: root.edited("query", text)
                onAccepted: root.service.refresh(text)
            }
            ActionButton {
                objectName: "openJoinRoomButton"
                Layout.fillWidth: !DesignTokens.comfortable
                text: qsTr("加入房间")
                variant: "soft"
                compact: true
                enabled: !root.status.roomBusy && !root.status.room
                onClicked: root.openRequested("joinRoom")
            }
            ActionButton {
                objectName: "createRoomButton"
                Layout.fillWidth: !DesignTokens.comfortable
                text: qsTr("创建房间")
                compact: true
                enabled: !root.status.roomBusy && !root.status.room
                onClicked: root.openRequested("createRoom")
            }
        }
        ListRow {
            objectName: "currentRoomRow"
            visible: root.ready && !!root.status.room
            Layout.fillWidth: true
            selected: true
            text: (root.status.room || {}).title || qsTr("当前房间")
            compact: !DesignTokens.comfortable
            caption: (root.status.room || {}).availability === "ready" ? qsTr("世界已开放") : qsTr("等待开放世界")
            value: qsTr("返回房间")
            iconName: "people"
            onClicked: root.openRequested("room")
        }
        ListViewport {
            objectName: "roomsViewport"
            visible: root.ready
            Layout.fillWidth: true
            Layout.fillHeight: DesignTokens.comfortable
            Layout.minimumHeight: DesignTokens.comfortable ? 80 : 0
            Layout.preferredHeight: DesignTokens.comfortable ? 120 : root.rooms.length ? Math.min(3, root.rooms.length) * (DesignTokens.rowHeight + 6) - 6 : 96
            model: DesignTokens.comfortable ? root.rooms : root.rooms.slice(pages.currentPage * pages.pageSize, (pages.currentPage + 1) * pages.pageSize)
            delegate: ListRow {
                required property var modelData
                objectName: "roomListing_" + modelData.id
                width: ListView.view.width
                compact: !DesignTokens.comfortable
                text: modelData.title || modelData.id
                caption: [modelData.node_name || modelData.node_region, typeof modelData.node_latency_ms === "number" ? qsTr("到节点 %1 ms").arg(Math.round(modelData.node_latency_ms)) : qsTr("到节点待测"), (modelData.game || {}).version, (modelData.game || {}).loader, modelData.require_invite === true ? qsTr("公开 · 需要邀请") : modelData.require_invite === false ? qsTr("公开 · 自由加入") : qsTr("房间信息未同步")].filter(Boolean).join(" · ")
                value: modelData.require_invite === true ? qsTr("需要邀请") : modelData.availability === "ready" ? qsTr("加入") : modelData.availability === "waiting" ? qsTr("准备中") : qsTr("状态未知")
                iconName: "people"
                enabled: !root.status.roomBusy && !root.status.room && typeof modelData.require_invite === "boolean"
                onClicked: {
                    if (modelData.require_invite)
                        root.openRequested("joinRoom");
                    else
                        root.service.join_listing(modelData.id);
                }
            }
            EmptyState {
                anchors.centerIn: parent
                width: Math.min(280, parent.width - 24)
                visible: parent.count === 0
                title: root.status.loading ? qsTr("正在获取房间…") : qsTr("暂无公开房间")
                caption: root.status.loading ? "" : qsTr("创建房间，或通过邀请加入朋友。")
            }
        }
        Pagination {
            id: pages
            objectName: "roomPagination"
            Layout.alignment: Qt.AlignHCenter
            visible: root.ready && !DesignTokens.comfortable && pageCount > 1
            itemCount: root.rooms.length
            pageIndex: root.pageIndex
            onChosen: index => root.edited("page", index)
        }
        NoticeBanner {
            Layout.fillWidth: true
            visible: root.ready && !!root.status.error
            text: root.status.error || ""
            color: DesignTokens.danger
        }
        UiText {
            objectName: "nodeStatusFooter"
            Layout.fillWidth: true
            visible: root.ready
            text: [root.status.nodeName || qsTr("联机节点"), root.status.latency >= 0 ? Math.round(root.status.latency) + " ms" : ""].filter(Boolean).join(" · ")
            font.pixelSize: 11
            color: DesignTokens.muted
        }
    }
}
