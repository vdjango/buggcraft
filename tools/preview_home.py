"""Development-only viewer for the same QML loaded by the C++ entry point."""

import argparse
import json
import os
from pathlib import Path
import sys
import time

os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
os.environ.setdefault("QML_DISABLE_DISK_CACHE", "1")

from PySide6.QtCore import QObject, QMetaObject, QTimer, QUrl, Q_ARG
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

from preview_desktop import PreviewDesktop


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture", type=Path)
    parser.add_argument("--tab", type=int, default=-1, choices=range(-1, 5))
    parser.add_argument("--record", type=Path)
    parser.add_argument("--record-dock", type=Path)
    parser.add_argument("--record-theme", type=Path)
    parser.add_argument("--page", default="")
    parser.add_argument("--launch-state", choices=["preparing", "running", "failed"])
    parser.add_argument("--gallery", type=Path)
    parser.add_argument("--edge", choices=["top", "left", "right"])
    parser.add_argument("--folded", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--theme", choices=["panel", "classic"], default="panel")
    options = parser.parse_args()
    if options.capture or options.record or options.record_dock or options.record_theme or options.smoke or options.gallery:
        os.environ.setdefault("QT_QUICK_BACKEND", "software")
    app = QGuiApplication(sys.argv[:1])
    QQuickStyle.setStyle("Basic")
    project = Path(__file__).resolve().parent.parent
    os.environ["PATH"] = str(project / "build") + os.pathsep + os.environ["PATH"]
    native_dll_path = os.add_dll_directory(str(project / "build")) if sys.platform == "win32" else None
    engine = QQmlApplicationEngine()
    desktop = PreviewDesktop()
    engine.setInitialProperties({"desktopEnvironment": desktop})
    engine.addImportPath(str(project / "build" / "qml"))
    engine.addImportPath(str(project / "qml"))
    messages = []
    engine.warnings.connect(lambda warnings: messages.extend(w.toString() for w in warnings))
    engine.load(QUrl.fromLocalFile(str(project / "qml" / "Main.qml")))
    if not engine.rootObjects():
        return 1
    window = engine.rootObjects()[0]
    dock = window.findChild(QObject, "edgeDock")
    controller = window.findChild(QObject, "windowController")
    deck = window.findChild(QObject, "toolContent")
    launch = window.findChild(QObject, "launchSession")
    identity = window.findChild(QObject, "identitySession")
    launch.setProperty("automatic", not options.launch_state)
    if options.theme == "classic":
        controller.selectTheme("classic")
    if options.launch_state:
        # Simulation requires an explicit development capture option.
        identity.setProperty("preview_enabled", True)
        launch.setProperty("preview_enabled", True)
        if options.theme != "classic":
            QTimer.singleShot(250, lambda: window.navigate(0))
        QMetaObject.invokeMethod(identity, "use_offline", Q_ARG(str, "PreviewPlayer"))
        QMetaObject.invokeMethod(launch, "start", Q_ARG(int, window.property("selectedInstance")))
        if options.launch_state == "running":
            for _ in range(4):
                QMetaObject.invokeMethod(launch, "advance")
        elif options.launch_state == "failed":
            QMetaObject.invokeMethod(launch, "fail", Q_ARG(str, "运行环境尚未准备完成，请重试或查看运行日志"))
        else:
            QMetaObject.invokeMethod(launch, "advance")
    recording_frames = []
    recording_times = []
    gallery_frames = []

    def place_at_edge():
        area = desktop.available_geometry(window)
        edge = options.edge or "top"
        if edge == "top":
            window.setPosition(area.x() + (area.width() - window.width()) // 2, area.y() + 12)
        elif edge == "left":
            window.setPosition(area.x() + 12, area.y() + 150)
        else:
            window.setPosition(area.x() + area.width() - window.width() - 12, area.y() + 150)
        dock.finishMove()
        if options.folded:
            QTimer.singleShot(300, lambda: dock.setFolded(True))

    if options.edge or options.folded or options.record_dock:
        QTimer.singleShot(100, place_at_edge)

    def finish_capture():
        if options.capture:
            options.capture.parent.mkdir(parents=True, exist_ok=True)
            if not window.grabWindow().save(str(options.capture)):
                print("Screenshot could not be saved.", file=sys.stderr)
                app.exit(1)
                return
        print(json.dumps({"qml_warnings": messages, "window": [window.width(), window.height()]}, ensure_ascii=False))
        app.exit(1 if messages else 0)

    if options.record or options.record_dock or options.record_theme:
        from PySide6.QtCore import QBuffer, QIODevice
        from PIL import Image
        import io

        def record_frame():
            buffer = QBuffer()
            buffer.open(QIODevice.WriteOnly)
            window.grabWindow().save(buffer, "PNG")
            frame = Image.open(io.BytesIO(bytes(buffer.data()))).convert("RGBA")
            if options.record_dock:
                canvas = Image.new("RGBA", (560, 350), "#ECECF1")
                edge = options.edge or "top"
                if edge == "top":
                    position = ((560 - frame.width) // 2, 0)
                else:
                    position = (0 if edge == "left" else 560 - frame.width, 34)
                canvas.alpha_composite(frame, position)
            else:
                canvas = Image.new("RGBA", (1040, 680), "#ECECF1")
                canvas.alpha_composite(frame, ((1040 - frame.width) // 2, 28))
            recording_frames.append(canvas.convert("RGB"))
            recording_times.append(time.monotonic())

        record_timer = QTimer()
        record_timer.setInterval(33)
        record_timer.timeout.connect(record_frame)
        QTimer.singleShot(200, record_timer.start)
        if options.record_theme:
            dock.setProperty("autoFoldEnabled", False)
            for timestamp, action in [
                (400, lambda: window.navigate(4)),
                (850, lambda: deck.openPage("appearance")),
                (1200, lambda: controller.selectTheme("classic")),
                (2300, lambda: window.navigate(0)),
                (3200, lambda: deck.openPage("instances")),
                (4050, lambda: controller.selectTheme("panel")),
                (4900, lambda: controller.selectTheme("classic")),
            ]:
                QTimer.singleShot(timestamp, action)
            QTimer.singleShot(5700, finish_capture)
        elif options.record_dock:
            dock.setProperty("autoFoldEnabled", False)
            for timestamp, folded in [(550, True), (1800, False), (3700, True), (5000, False)]:
                QTimer.singleShot(timestamp, lambda target=folded: dock.setFolded(target))
            QTimer.singleShot(2850, lambda: window.navigate(3))
            QTimer.singleShot(6500, finish_capture)
        else:
            for timestamp, tab in [(550, 0), (1900, 1), (3200, 3), (4600, -1)]:
                QTimer.singleShot(timestamp, lambda target=tab: window.navigate(target))
            QTimer.singleShot(5500, finish_capture)
    elif options.gallery:
        from PySide6.QtCore import QBuffer, QIODevice
        from PIL import Image
        import io

        routes = list(deck.property("routes").toVariant())
        if options.theme != "classic":
            controller.selectTheme("classic")

        def capture_page(index):
            if index == len(routes):
                finish_capture()
                return
            deck.openPage(routes[index])

            def grab():
                buffer = QBuffer()
                buffer.open(QIODevice.WriteOnly)
                window.grabWindow().save(buffer, "PNG")
                frame = Image.open(io.BytesIO(bytes(buffer.data()))).convert("RGBA")
                gallery_frames.append(frame)
                deck.goBack()
                capture_page(index + 1)

            QTimer.singleShot(250, grab)

        QTimer.singleShot(800, lambda: capture_page(0))
    elif options.smoke:
        for step, tab in enumerate([0, 1, 2, 3, 4, -1]):
            QTimer.singleShot(400 + step * 400, lambda target=tab: window.navigate(target))
        QTimer.singleShot(3000, finish_capture)
    else:
        if options.tab >= 0:
            QTimer.singleShot(250, lambda: window.navigate(options.tab) if window.property("activeTool") != options.tab else None)
        if options.page:
            if options.tab < 0 and options.theme != "classic":
                QTimer.singleShot(250, lambda: window.navigate(0))
            QTimer.singleShot(650, lambda: deck.openPage(options.page))
        if options.capture:
            QTimer.singleShot(2000 if options.folded else 1100, finish_capture)
    result = app.exec()
    if options.gallery and gallery_frames:
        from PIL import Image

        columns = 3
        tile_width, tile_height = 304, 264
        canvas = Image.new("RGBA", (columns * tile_width, ((len(gallery_frames) + columns - 1) // columns) * tile_height), "#ECECF1")
        for index, frame in enumerate(gallery_frames):
            frame.thumbnail((284, 244), Image.Resampling.LANCZOS)
            canvas.alpha_composite(frame, ((index % columns) * tile_width + 10, (index // columns) * tile_height + 10))
        options.gallery.parent.mkdir(parents=True, exist_ok=True)
        canvas.convert("RGB").save(options.gallery)
    recording_path = options.record_theme or options.record_dock or options.record
    if recording_path and recording_frames:
        recording_path.parent.mkdir(parents=True, exist_ok=True)
        recording_frames[0].save(
            recording_path,
            save_all=True,
            append_images=recording_frames[1:],
            duration=[
                max(20, round((recording_times[index + 1] - timestamp) * 1000))
                if index + 1 < len(recording_times)
                else 33
                for index, timestamp in enumerate(recording_times)
            ],
            loop=0,
            optimize=True,
        )
    return result


if __name__ == "__main__":
    raise SystemExit(main())
