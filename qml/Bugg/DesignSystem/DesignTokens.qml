pragma Singleton
import QtQuick

QtObject {
    property bool comfortable: false
    property string sizeClass: "panel"
    readonly property int densityStep: Math.max(0, ["panel", "small", "classic", "large"].indexOf(sizeClass))
    readonly property int controlHeight: 34 + densityStep * 4
    readonly property int iconButtonSize: 28 + densityStep * 2
    readonly property int rowHeight: 48 + densityStep * 4
    readonly property int detailedRowHeight: 56 + densityStep * 4
    readonly property int controlTextSize: 12 + densityStep
    property bool scenic: false
    property bool pageBackdrop: false
    property real pageSurfaceOpacity: 0.10
    property string pageTextColor: "light"
    // Presentation-only modal depth; all shared modals participate in one backdrop.
    property int modalCount: 0
    property real sceneSurfaceOpacity: 0.18
    readonly property url homeBackdrop: Qt.resolvedUrl("assets/home-siege-1.webp")
    readonly property var homeBackdrops: [homeBackdrop]
    readonly property color sceneBase: "#102338"
    readonly property color canvas: pageBackdrop ? Qt.rgba(1, 1, 1, pageSurfaceOpacity) : "#F7F8FA"
    readonly property color background: "#FDFCF9"
    readonly property color surface: pageBackdrop ? Qt.rgba(1, 1, 1, pageSurfaceOpacity) : scenic ? Qt.rgba(1, 1, 1, sceneSurfaceOpacity) : comfortable ? "#F0F2F5" : "#F3F1EC"
    readonly property color surfaceHover: pageBackdrop ? Qt.rgba(1, 1, 1, pageSurfaceOpacity) : scenic ? "#33FFFFFF" : comfortable ? "#E8EBF0" : "#EBE8E2"
    readonly property color elevated: pageBackdrop ? Qt.rgba(1, 1, 1, pageSurfaceOpacity) : "#FFFFFF"
    readonly property color floatingSurface: pageBackdrop ? Qt.rgba(1, 1, 1, pageSurfaceOpacity) : "#CCFFFFFF"
    readonly property color floatingHover: pageBackdrop ? Qt.rgba(1, 1, 1, pageSurfaceOpacity) : "#33FFFFFF"
    readonly property color floatingSelection: pageBackdrop ? Qt.rgba(1, 1, 1, pageSurfaceOpacity) : "#5CFFFFFF"
    readonly property color line: "#E8E5DE"
    readonly property color controlBorder: "#BEC2CB"
    readonly property color neutralText: "#34323B"
    readonly property color neutralMuted: "#6C6875"
    readonly property color neutralSurface: pageBackdrop ? Qt.rgba(1, 1, 1, pageSurfaceOpacity) : "#F4F5F7"
    readonly property color neutralHover: "#EBEDF0"
    readonly property color neutralAccent: "#7561C9"
    readonly property color neutralWash: "#EEEAFA"
    readonly property color text: scenic || (pageBackdrop && pageTextColor === "light") ? "#F7FAFF" : neutralText
    readonly property color muted: scenic || (pageBackdrop && pageTextColor === "light") ? "#E2EDF8" : neutralMuted
    readonly property color quiet: "#87828E"
    readonly property color accent: scenic || (pageBackdrop && pageTextColor === "light") ? "#CEE9FF" : neutralAccent
    readonly property color accentHover: scenic || (pageBackdrop && pageTextColor === "light") ? "#E6F4FF" : "#8270D5"
    readonly property color accentPressed: scenic || (pageBackdrop && pageTextColor === "light") ? "#B9DBF5" : "#6653B7"
    readonly property color accentInk: scenic || (pageBackdrop && pageTextColor === "light") ? "#1B3C55" : "#FFFFFF"
    readonly property color accentWash: scenic || (pageBackdrop && pageTextColor === "light") ? "#20FFFFFF" : neutralWash
    readonly property color shadow: "#34323B"
    readonly property color lilac: "#A08BCF"
    readonly property color danger: "#BA5149"
    readonly property color success: "#26834D"
    readonly property color warning: "#A46B16"
    readonly property string fontFamily: Qt.platform.os === "windows" ? "Microsoft YaHei UI" : "sans-serif"
    readonly property int radius: 12
    readonly property int motionFast: 120
}
