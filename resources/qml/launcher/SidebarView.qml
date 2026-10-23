import QtQuick

Sidebar {
    id: root
    property var state: navigation.view
    entries: state.entries
    currentIndex: state.currentIndex
    resourceBase: state.resources
    Connections { target: navigation; function onChanged() { root.state = navigation.view } }
    onActivated: index => navigation.activate(index)
}
