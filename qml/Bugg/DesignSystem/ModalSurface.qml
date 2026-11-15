import QtQuick
import QtQuick.Controls

// Shared modal frame. Callers own content, visibility and business actions.
Popup {
    id: root
    property bool registered: false
    readonly property real maximumDialogHeight: Math.max(0, (parent ? parent.height : 720) - 24)
    parent: Overlay.overlay
    anchors.centerIn: parent
    width: Math.min(420, parent ? parent.width - 24 : 386)
    padding: 16
    modal: true
    popupType: Popup.Item
    focus: true
    closePolicy: Popup.NoAutoClose
    dim: true
    onAboutToShow: {
        if (!registered) {
            registered = true;
            DesignTokens.modalCount++;
        }
    }
    onClosed: {
        if (registered) {
            registered = false;
            DesignTokens.modalCount = Math.max(0, DesignTokens.modalCount - 1);
        }
    }
    Component.onDestruction: {
        if (registered)
            DesignTokens.modalCount = Math.max(0, DesignTokens.modalCount - 1);
    }
    Overlay.modal: Rectangle {
        color: "#590E1724"
    }
    background: Surface {
        color: "#F5FFFFFF"
        padding: 0
        radius: 12
        borderColor: DesignTokens.line
        borderWidth: 1
    }
}
