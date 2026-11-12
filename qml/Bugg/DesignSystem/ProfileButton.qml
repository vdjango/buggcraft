pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

AbstractButton {
    id: root
    property string caption: ""
    property string initials: "?"
    // 主区域 clicked 进入管理；倒三角独立发 menuRequested，弹层状态由页面持有。
    property bool menuOpen: false
    signal menuRequested
    implicitWidth: 192
    implicitHeight: 54
    padding: 8
    hoverEnabled: true
    Accessible.role: Accessible.Button
    Accessible.name: text + (caption.length ? "，" + caption : "")
    background: InteractiveSurface {
        control: root
        radius: 12
    }
    contentItem: RowLayout {
        spacing: 12
        Avatar {
            initials: root.initials
            implicitWidth: 36
            implicitHeight: 36
        }
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 3
            UiText {
                Layout.fillWidth: true
                text: root.text
                font.pixelSize: 14
                font.weight: Font.DemiBold
            }
            UiText {
                Layout.fillWidth: true
                text: root.caption
                visible: text.length > 0
                font.pixelSize: 11
                color: DesignTokens.muted
            }
        }
        IconButton {
            objectName: "profileMenuButton"
            iconName: "down"
            rotation: root.menuOpen ? 180 : 0
            accessibleName: qsTr("快速切换游戏身份")
            implicitWidth: 26
            onClicked: root.menuRequested()
        }
    }
}
