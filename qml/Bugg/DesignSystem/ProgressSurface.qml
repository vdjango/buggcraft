import QtQuick

// 通用进度表面。仅消费业务进度；wave 动画不推进业务，隐藏/完成即停止。
Item {
    id: root
    property bool active: false
    property real progress: -1
    property real cornerRadius: 18
    property bool fluid: false
    property color fillColor: DesignTokens.accent
    property color trackColor: "transparent"
    property real phase: 0
    readonly property real fraction: progress < 0 ? 0.25 + 0.45 * (0.5 + 0.5 * Math.sin(phase * 0.5)) : Math.max(0, Math.min(1, progress))
    implicitHeight: 4
    onFractionChanged: surface.requestPaint()
    onPhaseChanged: surface.requestPaint()
    onActiveChanged: surface.requestPaint()
    onFillColorChanged: surface.requestPaint()
    NumberAnimation {
        target: root
        property: "phase"
        from: 0
        to: Math.PI * 4
        duration: 3600
        loops: Animation.Infinite
        running: root.active && root.visible && (root.fluid || root.progress < 0)
    }
    Canvas {
        id: surface
        anchors.fill: parent
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
        onPaint: {
            const ctx = getContext("2d");
            ctx.reset();
            const w = width, h = height, r = Math.min(root.cornerRadius, h / 2, w / 2);
            ctx.beginPath();
            ctx.moveTo(r, 0);
            ctx.lineTo(w - r, 0);
            ctx.quadraticCurveTo(w, 0, w, r);
            ctx.lineTo(w, h - r);
            ctx.quadraticCurveTo(w, h, w - r, h);
            ctx.lineTo(r, h);
            ctx.quadraticCurveTo(0, h, 0, h - r);
            ctx.lineTo(0, r);
            ctx.quadraticCurveTo(0, 0, r, 0);
            ctx.closePath();
            ctx.clip();
            ctx.fillStyle = root.trackColor;
            ctx.fillRect(0, 0, w, h);
            if (!root.active)
                return;
            const front = w * root.fraction;
            ctx.fillStyle = root.fillColor;
            if (!root.fluid) {
                ctx.fillRect(0, 0, front, h);
                return;
            }
            // 横向水面与两层波纹共享一张画布，始终裁在工具条圆角内。
            for (let layer = 0; layer < 2; ++layer) {
                ctx.globalAlpha = layer === 0 ? 0.10 : 0.08;
                ctx.beginPath();
                ctx.moveTo(0, 0);
                ctx.lineTo(front, 0);
                for (let y = 0; y <= h + 4; y += 4)
                    ctx.lineTo(front + Math.sin(y / 11 + root.phase + layer * 1.7) * 5, y);
                ctx.lineTo(0, h);
                ctx.closePath();
                ctx.fill();
            }
            ctx.globalAlpha = 0.22;
            for (let i = 0; i < 4; ++i) {
                const position = (root.phase / (Math.PI * 4) + i / 4) % 1;
                ctx.beginPath();
                ctx.arc(front - 8 - position * 28, h * (1 - position), 1.5 + position, 0, Math.PI * 2);
                ctx.fill();
            }
        }
    }
}
