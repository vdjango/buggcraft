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
    readonly property url homeBackdrop: Qt.resolvedUrl("assets/home-siege-1.webp")
    readonly property var homeBackdrops: [homeBackdrop]
    readonly property color sceneBase: "#102338"
    readonly property color canvas: "#F7F8FA"
    readonly property color background: "#FDFCF9"
    readonly property color surface: scenic ? "#22FFFFFF" : comfortable ? "#F0F2F5" : "#F3F1EC"
    readonly property color surfaceHover: scenic ? "#33FFFFFF" : comfortable ? "#E8EBF0" : "#EBE8E2"
    readonly property color elevated: "#FFFFFF"
    readonly property color floatingSurface: "#CCFFFFFF"
    readonly property color floatingHover: "#33FFFFFF"
    readonly property color floatingSelection: "#5CFFFFFF"
    readonly property color line: "#E8E5DE"
    readonly property color controlBorder: "#BEC2CB"
    readonly property color neutralText: "#34323B"
    readonly property color neutralMuted: "#6C6875"
    readonly property color neutralSurface: "#F4F5F7"
    readonly property color neutralHover: "#EBEDF0"
    readonly property color neutralAccent: "#7561C9"
    readonly property color neutralWash: "#EEEAFA"
    readonly property color text: scenic ? "#F7FAFF" : neutralText
    readonly property color muted: scenic ? "#C9D6E4" : neutralMuted
    readonly property color quiet: "#87828E"
    readonly property color accent: scenic ? "#CEE9FF" : neutralAccent
    readonly property color accentHover: scenic ? "#E6F4FF" : "#8270D5"
    readonly property color accentPressed: scenic ? "#B9DBF5" : "#6653B7"
    readonly property color accentInk: scenic ? "#1B3C55" : "#FFFFFF"
    readonly property color accentWash: scenic ? "#20FFFFFF" : neutralWash
    readonly property color shadow: "#34323B"
    readonly property color lilac: "#A08BCF"
    readonly property color danger: "#BA5149"
    readonly property color success: "#26834D"
    readonly property color warning: "#A46B16"
    readonly property string fontFamily: Qt.platform.os === "windows" ? "Microsoft YaHei UI" : "sans-serif"
    readonly property int radius: 12
    readonly property int motionFast: 120
}
