import QtQuick
import QtQuick.Controls

// 所有长列表共用有界滚动，页脚由调用者放在 viewport 外。
ListView {
    clip: true
    spacing: 6
    boundsBehavior: Flickable.StopAtBounds
    flickableDirection: Flickable.VerticalFlick
    interactive: contentHeight > height
    ScrollBar.vertical: ScrollBar {
        policy: ScrollBar.AsNeeded
    }
}
