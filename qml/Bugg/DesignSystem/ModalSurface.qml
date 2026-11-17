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
    // The native window includes transparent margins around its rounded frame.
    // A full-window dimmer paints those margins black on macOS and Windows.
    // Keep the modal input barrier, without extending an effect outside the UI.
    dim: false
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
    background: Surface {
        color: "#F5FFFFFF"
        padding: 0
        radius: 12
        borderColor: DesignTokens.line
        borderWidth: 1
    }
}
