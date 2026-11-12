pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Shapes

Item {
    id: root
    property string name: "plus"
    property color color: DesignTokens.muted
    property real strokeWidth: 1.65
    readonly property string iconPath: {
        const paths = {
            home: "M3 10 L12 3 L21 10 M5 9 L5 21 L10 21 L10 15 L14 15 L14 21 L19 21 L19 9",
            library: "M4 4 L4 20 M9 4 L9 20 M14 4 L14 20 M18 5 L22 19",
            minecraft: "M3 7 L12 2 L21 7 L21 17 L12 22 L3 17 Z M3 7 L12 12 L21 7 M12 12 L12 22",
            neoforge: "M3 5 L21 5 L21 8 L15 12 L15 16 L19 19 L19 21 L5 21 L5 19 L9 16 L9 12 L3 9 Z",
            forge: "M3 5 L21 5 L21 8 L15 12 L15 16 L19 19 L19 21 L5 21 L5 19 L9 16 L9 12 L3 9 Z",
            fabric: "M5 5 L17 5 L20 8 L20 20 L8 20 L5 17 Z M5 5 L8 8 L20 8 M8 8 L8 20 M11 11 L17 11 M11 14 L17 14 M11 17 L17 17",
            quilt: "M3 3 L21 3 L21 21 L3 21 Z M3 12 L21 12 M12 3 L12 21 M3 3 L12 12 L21 3 M3 21 L12 12 L21 21",
            compass: "M21 12 A9 9 0 1 1 3 12 A9 9 0 1 1 21 12 M15.5 8.5 L13.5 13.5 L8.5 15.5 L10.5 10.5 Z",
            download: "M12 3 L12 15 M7 10 L12 15 L17 10 M4 16 L4 21 L20 21 L20 16",
            people: "M15 8 A3 3 0 1 1 9 8 A3 3 0 1 1 15 8 M5 21 L5 19 Q5 14 12 14 Q19 14 19 19 L19 21 M19 5 Q24 8 20 11 M21 15 Q24 17 23 21",
            settings: "M12 3 L14 6 L18 6 L18 10 L21 12 L18 14 L18 18 L14 18 L12 21 L10 18 L6 18 L6 14 L3 12 L6 10 L6 6 L10 6 Z M15 12 A3 3 0 1 1 9 12 A3 3 0 1 1 15 12",
            help: "M21 12 A9 9 0 1 1 3 12 A9 9 0 1 1 21 12 M9 9 Q9 6 12 6 Q16 6 15 10 Q14 12 12 12 L12 14 M12 17 L12 17.5",
            play: "M8 4 L20 12 L8 20 Z",
            stop: "M6 6 L18 6 L18 18 L6 18 Z",
            plus: "M12 4 L12 20 M4 12 L20 12",
            copy: "M8 8 L21 8 L21 21 L8 21 Z M16 4 L16 3 L3 3 L3 16 L4 16",
            arrow: "M4 12 L20 12 M14 6 L20 12 L14 18",
            chevron: "M8 5 L15 12 L8 19",
            down: "M6 9 L12 15 L18 9",
            check: "M4 12 L9 17 L20 6",
            close: "M5 5 L19 19 M19 5 L5 19",
            minimize: "M5 12 L19 12",
            collapse: "M5 5 L19 5 M8 14 L12 10 L16 14 M12 10 L12 20",
            maximize: "M5 5 L19 5 L19 19 L5 19 Z",
            more: "M5 12 L5.1 12 M12 12 L12.1 12 M19 12 L19.1 12",
            refresh: "M20 9 A8 8 0 1 0 20 15 M20 3 L20 9 L14 9",
            link: "M9 15 L15 9 M8 16 L6 18 Q2 20 2 15 Q2 13 5 10 L8 7 Q12 4 15 8 M9 16 Q12 20 16 17 L20 13 Q24 9 20 6 Q18 4 15 6",
            clock: "M21 12 A9 9 0 1 1 3 12 A9 9 0 1 1 21 12 M12 6 L12 12 L16 14",
            server: "M4 4 L20 4 L20 10 L4 10 Z M4 14 L20 14 L20 20 L4 20 Z M7 7 L8 7 M7 17 L8 17",
            shield: "M12 2 L20 6 L20 12 Q20 18 12 22 Q4 18 4 12 L4 6 Z M8 12 L11 15 L16 9",
            arrowDown: "M12 4 L12 20 M6 14 L12 20 L18 14",
            folder: "M3 7 L3 20 L21 20 L21 7 L12 7 L9 4 L3 4 Z",
            bell: "M5 17 L7 14 L7 9 Q7 4 12 4 Q17 4 17 9 L17 14 L19 17 Z M10 21 L14 21",
            chat: "M3 4 L21 4 L21 17 L10 17 L5 21 L5 17 L3 17 Z M7 8 L17 8 M7 12 L14 12",
            volume: "M3 9 L7 9 L12 5 L12 19 L7 15 L3 15 Z M16 8 Q20 12 16 16"
        };
        return paths[name] || paths.plus;
    }
    implicitWidth: 20
    implicitHeight: 20
    layer.enabled: true
    Shape {
        width: 24
        height: 24
        anchors.centerIn: parent
        scale: root.width / 24
        antialiasing: true
        ShapePath {
            strokeColor: root.color
            strokeWidth: root.strokeWidth
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap
            joinStyle: ShapePath.RoundJoin
            PathSvg {
                path: root.iconPath
            }
        }
    }
}
