pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Shapes

Item {
    id: root
    implicitWidth: 96
    implicitHeight: 96
    Rectangle {
        anchors.centerIn: parent
        anchors.verticalCenterOffset: root.height / 3
        width: root.width * 0.625
        height: root.height * 0.1
        radius: height / 2
        color: "#0D110E"
        opacity: 0.1
    }
    Item {
        width: 96
        height: 96
        anchors.centerIn: parent
        scale: root.width / 96
        Shape {
            anchors.fill: parent
            antialiasing: true
            ShapePath {
                strokeWidth: 0
                fillColor: "#708A55"
                PathSvg {
                    path: "M48 10 L85 30 L48 51 L11 30 Z"
                }
            }
            ShapePath {
                strokeWidth: 0
                fillColor: "#8FA66B"
                PathSvg {
                    path: "M48 10 L61 17 L24 38 L11 30 Z M61 31 L73 24 L85 30 L73 37 Z"
                }
            }
            ShapePath {
                strokeWidth: 0
                fillColor: "#A8BC80"
                PathSvg {
                    path: "M24 23 L36 16 L48 23 L36 30 Z M48 23 L61 30 L48 37 L36 30 Z"
                }
            }
            ShapePath {
                strokeWidth: 0
                fillColor: "#4F6550"
                PathSvg {
                    path: "M11 30 L48 51 L48 85 L11 64 Z"
                }
            }
            ShapePath {
                strokeWidth: 0
                fillColor: "#344E3C"
                PathSvg {
                    path: "M48 51 L85 30 L85 64 L48 85 Z"
                }
            }
            ShapePath {
                strokeWidth: 0
                fillColor: "#667B50"
                PathSvg {
                    path: "M11 30 L48 51 L48 62 L36 55 L36 61 L24 54 L24 48 L11 41 Z"
                }
            }
            ShapePath {
                strokeWidth: 0
                fillColor: "#4F6942"
                PathSvg {
                    path: "M48 51 L85 30 L85 41 L73 48 L73 55 L61 62 L61 55 L48 62 Z"
                }
            }
            ShapePath {
                strokeWidth: 0
                fillColor: "#64745D"
                PathSvg {
                    path: "M18 51 L26 55 L26 61 L18 57 Z M34 67 L42 71 L42 77 L34 73 Z"
                }
            }
            ShapePath {
                strokeWidth: 0
                fillColor: "#425B47"
                PathSvg {
                    path: "M55 67 L63 63 L63 70 L55 74 Z M73 53 L80 49 L80 56 L73 60 Z"
                }
            }
        }
    }
}
