import QtQuick
import QtQuick.Layouts
import Bugg.DesignSystem

// Read-only bridge observations; UI never infers NAT guarantees from counts.
ColumnLayout {
    id: root
    property var profile: ({})
    property bool own: false
    property bool compact: false
    readonly property bool stale: profile.observed_at > 0 && Date.now() / 1000 - profile.observed_at > 600
    spacing: 3
    UiText {
        Layout.fillWidth: true
        horizontalAlignment: root.compact ? Text.AlignRight : Text.AlignLeft
        readonly property var labels: ({
                "unknown": qsTr("直连条件待检测"),
                "udp-reachable": qsTr("可以尝试直连"),
                "mapping-stable-observed": qsTr("直连条件较好"),
                "mapping-dependent-observed": qsTr("直连较困难，可自动中转")
            })
        text: (root.compact ? "" : root.own ? qsTr("我的网络 · ") : qsTr("对方网络 · ")) + (labels[root.profile.type || "unknown"] || labels.unknown) + (root.stale ? qsTr("（历史参考）") : root.compact ? qsTr("（参考）") : "")
        color: DesignTokens.muted
        font.pixelSize: 11
        wrapMode: Text.Wrap
    }
    UiText {
        Layout.fillWidth: true
        visible: !root.compact
        text: root.profile.direct_successes !== undefined ? qsTr("连接记录：直连 %1 · 中转 %2（仅供参考）").arg(root.profile.direct_successes).arg(root.profile.relay_successes || 0) : qsTr("暂无连接记录")
        color: DesignTokens.muted
        font.pixelSize: 11
        wrapMode: Text.Wrap
    }
}
