pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import Bugg.DesignSystem
PageLayout {
    id: root
    property var service: null
    maximumWidth: 420
    NodeLogin { Layout.fillWidth: true; status: root.service ? root.service.status : ({}); onLoginRequested: origin => { if (root.service) root.service.login(origin); }; onLogoutRequested: { if (root.service) root.service.logout(); } }
}
