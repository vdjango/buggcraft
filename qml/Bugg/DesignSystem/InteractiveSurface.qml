import QtQuick
import QtQuick.Templates as T

// 通用控件背景：调用方提供控制器/选中状态；悬停、按下、键盘焦点的绘制只维护在这里。
Rectangle {
    id: root
    required property T.Control control
    property bool selected: false
    property bool hoverFeedbackEnabled: true
    property bool animateFeedback: false
    property bool faded: false
    property real fadeOpacity: 0.15
    property color backdropTint: "#243D44"
    readonly property color shadeTint: backdropTint
    property color restingColor: "transparent"
    property color hoverColor: DesignTokens.surface
    property color selectedColor: DesignTokens.accentWash
    property color pressedColor: DesignTokens.surfaceHover
    readonly property bool controlDown: control instanceof T.AbstractButton ? (control as T.AbstractButton).down : control instanceof T.ComboBox ? (control as T.ComboBox).down : false
    radius: 8
    // 渐变保持实色起点，以表面 opacity 统一控制淡化，避免后端跳过低透明度填充。
    color: faded ? shadeTint : !control.enabled ? restingColor : selected ? selectedColor : controlDown ? pressedColor : (hoverFeedbackEnabled && control.hovered) || control.visualFocus ? hoverColor : restingColor
    opacity: faded ? fadeOpacity : 1
    gradient: faded ? sceneGradient : null
    Gradient {
        id: sceneGradient
        orientation: Gradient.Horizontal
        GradientStop {
            position: 0
            color: root.shadeTint
        }
        GradientStop {
            position: 0.6
            color: Qt.rgba(root.shadeTint.r, root.shadeTint.g, root.shadeTint.b, 0.5)
        }
        GradientStop {
            position: 1
            color: "transparent"
        }
    }
    Behavior on color {
        enabled: root.animateFeedback
        ColorAnimation {
            duration: DesignTokens.motionFast
            easing.type: Easing.OutCubic
        }
    }
}
