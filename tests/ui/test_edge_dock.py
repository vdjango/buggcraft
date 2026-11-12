"""Exercise the production QML docking rules with controlled desktop facts."""

import os
import json
from pathlib import Path
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
os.environ.setdefault("QML_DISABLE_DISK_CACHE", "1")

from PySide6.QtCore import QObject, QPoint, QRect, QUrl, Qt, Signal, Slot, Property, QMetaObject, Q_ARG
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QImage, QWindow
from PySide6.QtQml import QQmlApplicationEngine, QQmlExpression
from PySide6.QtQuick import QQuickWindow
from PySide6.QtTest import QTest

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "tools"))
os.environ["PATH"] = str(PROJECT / "build") + os.pathsep + os.environ["PATH"]

NATIVE_DLL_PATH = os.add_dll_directory(str(PROJECT / "build")) if sys.platform == "win32" else None


class NativeModel:
    """Test port invoking the compiled C++ object; contains no model behavior."""

    def __init__(self, obj):
        self.obj = obj
        obj.setProperty("automatic", False)
        # Only automation explicitly enables the existing simulation driver.
        obj.setProperty("preview_enabled", True)

    @property
    def status(self):
        return self.obj.property("status")

    def __getattr__(self, method):
        return lambda *args: QMetaObject.invokeMethod(
            self.obj, method, *(Q_ARG(type(arg), arg) for arg in args)
        )


class ControlledDesktop(QObject):
    available_geometry_changed = Signal()

    def __init__(self):
        super().__init__()
        self.area = QRect(0, 40, 1280, 760)
        self.pointer_override = None

    @Slot(QWindow, result=QRect)
    def available_geometry(self, _window):
        return self.area

    @Slot(result=bool)
    def left_button_pressed(self):
        return False

    @Slot(QWindow, result=bool)
    def fullscreen_foreground(self, _window):
        return False

    @Slot(QWindow, result=bool)
    def pointer_inside(self, window):
        return self.pointer_override if self.pointer_override is not None else window.geometry().contains(QCursor.pos())


class NodeUiProbe(QObject):
    """Explicit UI-only port: snapshots and intent recording, no service behavior."""
    changed = Signal()
    room_joined = Signal()
    room_left = Signal()
    social_completed = Signal(str, str)
    host_required = Signal()
    room_command_completed = Signal(str)
    chat_sent = Signal()
    preparation_required = Signal()
    launch_requested = Signal(str, 'QVariantMap')

    def __init__(self):
        super().__init__()
        self.snapshot = {"state": "ready", "username": "TestUser", "account": "account-test",
                         "friendCode": "ABCD-EFGH-JKLM", "rooms": [], "friends": [], "requests": [], "nodeName": "Bugg"}
        self.calls = []

    @Property('QVariantMap', notify=changed)
    def status(self):
        return self.snapshot

    @Slot(str)
    @Slot()
    def refresh(self, query=""):
        self.calls.append(("refresh", query))

    @Slot(str)
    @Slot()
    def mark_notifications_read(self, category=""):
        self.calls.append(("read_notifications", category))

    @Slot(str, str, str, 'QVariantMap')
    def create_room(self, title, directory, player, options):
        self.calls.append(("create", title, directory, player, options))

    @Slot()
    def discover_worlds(self):
        self.calls.append(("discover",))

    @Slot(int)
    def connect_world(self, port):
        self.calls.append(("connect", port))

    @Slot(str)
    def join_room(self, invite):
        self.calls.append(("join", invite))

    @Slot(str)
    def join_listing(self, room):
        self.calls.append(("listing", room))

    @Slot()
    def leave_room(self):
        self.calls.append(("leave",))

    @Slot(result=bool)
    def copy_invite(self):
        self.calls.append(("copy",))
        return True

    @Slot(str, str, 'QVariantMap')
    def social(self, operation, target, fields):
        self.calls.append((operation, target, fields))

    @Slot(str)
    def invite_friend(self, account):
        self.calls.append(("invite_friend", account))

    @Slot()
    def cancel_invites(self):
        self.calls.append(("cancel_invites",))

    @Slot()
    def cancel_lookup(self):
        self.calls.append(("cancel_lookup",))

    @Slot(str, 'QVariantMap')
    def room_command(self, operation, fields):
        self.calls.append(("room_command", operation, fields))

    @Slot(str)
    def send_chat(self, text):
        self.calls.append(("send_chat", text))

    @Slot()
    @Slot(str)
    def sync_room(self, mode="fresh"):
        self.calls.append(("sync_room", mode))

    @Slot(str)
    def select_room_instance(self, instance_id):
        self.calls.append(("select_room_instance", instance_id))

    @Slot()
    def launch_room(self):
        self.calls.append(("launch_room",))

    @Slot(result=bool)
    @Slot(str, result=bool)
    def copy_friend_code(self, account=""):
        self.calls.append(("copy_friend_code", account))
        return True


class UpdateUiProbe(QObject):
    """Explicit update snapshots for rendering; native tests exercise real HTTP/files."""
    changed = Signal()
    update_available = Signal(str)

    def __init__(self):
        super().__init__()
        self.snapshot = {"state": "latest", "currentVersion": "2.0.1"}
        self.calls = []

    @Property('QVariantMap', notify=changed)
    def status(self):
        return self.snapshot

    @Slot()
    def check(self):
        self.calls.append("check")

    @Slot()
    def download(self):
        self.calls.append("download")

    @Slot()
    def install(self):
        self.calls.append("install")

    @Slot()
    def cancel(self):
        self.calls.append("cancel")


class LanguageUiCatalog(QObject):
    """Real display catalog exposed only as a UI fixture; no language switching logic."""

    @Property('QVariantList', constant=True)
    def options(self):
        catalog = json.loads((PROJECT / "assets/i18n/languages.json").read_text(encoding="utf-8"))
        return [{"id": code, "name": item["name"] + " · " + item["region"]}
                for code, item in catalog.items()
                if code in {"zh_cn", "en_us", "ar_sa", "de_de", "fr_fr", "he_il",
                            "ja_jp", "ru_ru", "vi_vn", "yi_de", "yo_ng", "zlm_arab"}]

    @Property(bool, constant=True)
    def right_to_left(self):
        return False

    @Slot('QStringList')
    def set_game_codes(self, _codes):
        pass


class EdgeDockTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.desktop = ControlledDesktop()
        self.engine = QQmlApplicationEngine()
        self.engine.addImportPath(str(PROJECT / "build" / "qml"))
        self.engine.addImportPath(str(PROJECT / "qml"))
        self.engine.setInitialProperties({"desktopEnvironment": self.desktop})
        self.warnings = []
        self.engine.warnings.connect(
            lambda warnings: self.warnings.extend(w.toString() for w in warnings)
        )
        self.engine.load(QUrl.fromLocalFile(str(PROJECT / "qml" / "Main.qml")))
        self.assertTrue(self.engine.rootObjects(), self.warnings)
        self.window = self.engine.rootObjects()[0]
        self.assertIsInstance(self.window, QQuickWindow)
        # 显式测试数据；生产 Main 只使用 GameRuntime 的磁盘扫描结果。
        self.window.setProperty("instances", [
            {"id": "siege", "name": "百日围城", "version": "1.21.1", "loader": "NeoForge"},
            {"id": "vanilla", "name": "原版生存", "version": "1.21.1", "loader": "Minecraft"},
            {"id": "forge", "name": "Forge 生存", "version": "1.20.1", "loader": "Forge"},
        ])
        self.launch = NativeModel(self.window.findChild(QObject, "launchSession"))
        self.identity = NativeModel(self.window.findChild(QObject, "identitySession"))
        self.dock = self.window.findChild(QObject, "edgeDock")
        self.window.findChild(QObject, "windowController").selectTheme("panel")
        self.window.navigate(-1)
        self.dock.setProperty("autoFoldEnabled", False)
        QTest.qWait(400)

    def tearDown(self):
        self.window.close()
        self.engine.deleteLater()
        self.app.processEvents()
        self.assertEqual(self.warnings, [])

    def release_at(self, x, y):
        self.window.setPosition(x, y)
        self.dock.finishMove()
        QTest.qWait(310)

    def visual_item(self, name):
        pending = [self.window.contentItem()]
        hidden = None
        while pending:
            item = pending.pop()
            if item.objectName() == name:
                if item.isVisible():
                    return item
                hidden = item
            pending.extend(item.childItems())
        return hidden

    def click_item(self, name, settle_ms=200):
        item = self.visual_item(name)
        if item is None or not item.isVisible():
            item = next((candidate for candidate in self.window.findChildren(QObject, name) if candidate.isVisible()), None)
        self.assertIsNotNone(item)
        point = item.mapToScene(QPoint(int(item.width() / 2), int(item.height() / 2)))
        QTest.mouseClick(self.window, Qt.LeftButton, Qt.NoModifier, point.toPoint())
        QTest.qWait(settle_ms)

    def hover_item(self, item):
        # Keep the OS cursor and synthetic Qt event consistent on frameless windows.
        point = item.mapToScene(QPoint(int(item.width() / 2), int(item.height() / 2))).toPoint()
        self.window.requestActivate()
        QCursor.setPos(self.window.mapToGlobal(QPoint(2, 2)))
        QTest.mouseMove(self.window, QPoint(2, 2))
        QTest.qWait(80)
        QCursor.setPos(self.window.mapToGlobal(point))
        QTest.mouseMove(self.window, point)
        QTest.qWait(180)

    def test_three_edges_and_corner(self):
        for x, y, edge, expected in [
            (19, 180, Qt.LeftEdge, (0, 180)),
            (851, 180, Qt.RightEdge, (870, 180)),
            (350, 60, Qt.TopEdge, (350, 40)),
            (13, 52, Qt.TopEdge | Qt.LeftEdge, (0, 40)),
        ]:
            with self.subTest(edge=edge):
                self.release_at(x, y)
                self.assertEqual(self.dock.property("attachment"), edge.value)
                self.assertEqual((self.window.x(), self.window.y()), expected)

    def test_four_sizes_and_nearest_edge_collapse(self):
        controller = self.window.findChild(QObject, "windowController")
        for theme, size in [("small", (800, 520)), ("classic", (960, 600)),
                            ("large", (1180, 730)), ("panel", (410, 148))]:
            with self.subTest(theme=theme):
                self.assertTrue(controller.selectTheme(theme))
                QTest.qWait(680)
                self.assertEqual((self.window.width(), self.window.height()), size)
        for position, edge, size in [((90, 200), Qt.LeftEdge, (44, 88)),
                                     ((800, 200), Qt.RightEdge, (44, 88)),
                                     ((350, 45), Qt.TopEdge, (88, 40))]:
            with self.subTest(position=position):
                controller.selectTheme("panel")
                QTest.qWait(500)
                self.window.setPosition(*position)
                controller.collapseToEdge(0)
                QTest.qWait(1150)
                self.assertEqual(self.dock.property("attachment"), edge.value)
                self.assertEqual((self.window.width(), self.window.height()), size)

    def test_running_collapse_hides_details_before_resizing(self):
        controller = self.window.findChild(QObject, "windowController")
        controller.selectTheme("classic")
        self.window.navigate(0)
        QTest.qWait(500)
        self.identity.use_offline("CollapsePlayer")
        self.launch.start(0)
        for _ in range(4):
            self.launch.advance()
        self.assertEqual(self.launch.status["state"], "running")
        self.window.setPosition(90, 200)
        controller.collapseToEdge(0)
        QTest.qWait(30)
        scroll = self.window.findChild(QObject, "pageScrollView")
        self.assertEqual(scroll.property("opacity"), 0)
        self.assertFalse(self.visual_item("windowBackdrop").property("visible"))
        self.assertEqual((self.window.width(), self.window.height()), (44, 88))
        self.assertFalse(self.dock.property("foldAnimating"))
        QTest.qWait(950)
        self.assertEqual(self.dock.property("attachment"), Qt.LeftEdge.value)
        self.assertEqual((self.window.width(), self.window.height()), (44, 88))
        self.assertEqual(self.launch.status["state"], "running")

    def test_page_collapse_button_commits_top_handle_without_panel_frame(self):
        controller = self.window.findChild(QObject, "windowController")
        controller.selectTheme("small")
        self.window.navigate(0)
        QTest.qWait(500)
        self.window.setPosition(70, 200)
        button = self.visual_item("collapseWindowButton")
        self.assertTrue(button.property("visible"))
        self.assertTrue(QMetaObject.invokeMethod(button, "clicked"))
        QTest.qWait(20)
        self.assertEqual(self.dock.property("attachment"), Qt.TopEdge.value)
        self.assertEqual((self.window.width(), self.window.height()), (88, 40))
        self.assertEqual(self.window.y(), self.desktop.area.y())
        self.assertFalse(self.dock.property("foldAnimating"))
        self.assertEqual(controller.property("theme"), "small")
        self.assertEqual(controller.property("layoutProgress"), 0)
        path = Path('D:/BuggBuild/version-audit-20261112/page-collapse-top.png')
        path.parent.mkdir(parents=True, exist_ok=True)
        self.assertTrue(self.window.grabWindow().save(str(path)))

    def test_no_snap_beyond_threshold_or_at_bottom(self):
        for x, y in [(29, 180), (841, 180), (350, 69), (350, 724)]:
            self.release_at(x, y)
            self.assertEqual(self.dock.property("attachment"), 0)
            self.assertEqual((self.window.x(), self.window.y()), (x, y))
        self.assertFalse(self.dock.property("dragging"))

    def test_right_edge_stays_fixed_during_morph(self):
        self.release_at(857, 180)
        for tool, width in [(1, 410), (3, 410), (-1, 410)]:
            self.window.navigate(tool)
            for _ in range(28):
                QTest.qWait(20)
                self.assertEqual(self.window.x() + self.window.width(), 1280)
            self.assertEqual(self.window.width(), width)

    def test_bottom_clearance_restores_on_collapse(self):
        self.release_at(18, 710)
        self.window.navigate(3)
        QTest.qWait(550)
        self.assertEqual(self.window.x(), 0)
        self.assertEqual(self.window.y() + self.window.height(), 800)
        self.window.navigate(-1)
        QTest.qWait(550)
        self.assertEqual((self.window.y(), self.window.height()), (710, 76))

    def test_negative_monitor_origin_and_changed_work_area(self):
        self.desktop.area = QRect(-1920, -1040, 1920, 1000)
        self.desktop.available_geometry_changed.emit()
        QTest.qWait(40)
        self.release_at(-423, -1020)
        self.assertEqual(
            self.dock.property("attachment"), (Qt.TopEdge | Qt.RightEdge).value
        )
        self.assertEqual((self.window.x(), self.window.y()), (-410, -1040))
        # A changed work area (taskbar / display reconnection) is applied live.
        self.desktop.area = QRect(40, 70, 1200, 650)
        self.desktop.available_geometry_changed.emit()
        QTest.qWait(60)
        self.assertEqual((self.window.x(), self.window.y()), (830, 70))

    def test_detaching_keeps_free_position_and_interrupts_snap(self):
        self.release_at(19, 180)
        self.release_at(300, 200)
        self.assertEqual(self.dock.property("attachment"), 0)
        self.window.navigate(1)
        QTest.qWait(550)
        self.assertEqual((self.window.x(), self.window.y()), (300, 200))
        self.window.setPosition(12, 180)
        self.dock.finishMove()
        QTest.qWait(30)
        self.window.setPosition(500, 220)
        self.dock.finishMove()
        QTest.qWait(310)
        self.assertEqual((self.window.x(), self.window.y()), (500, 220))
        self.assertEqual(self.dock.property("attachment"), 0)

    def test_folded_tab_on_each_edge_and_click_to_reopen(self):
        for x, y, expected in [
            (19, 180, (0, 174, 44, 88)),
            (851, 180, (1236, 174, 44, 88)),
            (350, 60, (511, 40, 88, 40)),
        ]:
            with self.subTest(expected=expected):
                self.release_at(x, y)
                self.assertTrue(self.dock.setFolded(True))
                QTest.qWait(1400)
                self.assertEqual(
                    (self.window.x(), self.window.y(), self.window.width(), self.window.height()),
                    expected,
                )
                QTest.mouseClick(
                    self.window, Qt.LeftButton, Qt.NoModifier,
                    QPoint(self.window.width() // 2, self.window.height() // 2),
                )
                QTest.qWait(1400)
                self.assertFalse(self.dock.property("folded"))
                self.assertEqual((self.window.width(), self.window.height()), (410, 76))

    def test_fold_preserves_tool_and_can_reverse_mid_animation(self):
        self.release_at(851, 180)
        self.window.navigate(1)
        QTest.qWait(550)
        search = self.window.findChild(QObject, "searchInput")
        self.assertIsNotNone(search)
        search.setProperty("text", "saved search")
        self.dock.setFolded(True)
        QTest.qWait(110)
        self.dock.setFolded(False)
        QTest.qWait(80)
        self.dock.setFolded(True)
        QTest.qWait(1400)
        self.assertEqual(self.window.property("activeTool"), 1)
        self.assertEqual((self.window.width(), self.window.height()), (44, 88))
        self.dock.setFolded(False)
        for _ in range(70):
            QTest.qWait(20)
            self.assertEqual(self.window.x() + self.window.width(), 1280)
        self.assertEqual((self.window.width(), self.window.height()), (410, 202))
        self.assertEqual(self.window.property("contentReveal"), 1)
        self.assertEqual(search.property("text"), "saved search")

    def test_auto_fold_repairs_missing_leave_and_ignores_input_focus(self):
        self.release_at(19, 180)
        # Keep the real cursor outside while this test supplies controlled hover facts.
        QTest.mouseMove(self.window, QPoint(self.window.width() + 80, self.window.height() + 80))
        QTest.qWait(40)
        self.dock.setPointerInside(True)
        self.desktop.pointer_override = True
        self.dock.setProperty("autoFoldEnabled", True)
        QTest.qWait(1000)
        self.assertFalse(self.dock.property("folded"))
        self.window.navigate(1)
        QTest.qWait(550)
        search = self.window.findChild(QObject, "searchInput")
        search.forceActiveFocus()
        self.assertTrue(search.property("activeFocus"))
        # No setPointerInside(false): emulate a missed leave after a native move.
        self.desktop.pointer_override = False
        QTest.qWait(1350)
        self.assertTrue(self.dock.property("folded"))
        self.dock.setProperty("autoFoldEnabled", False)

    def test_free_panel_cannot_fold(self):
        self.release_at(300, 200)
        self.assertFalse(self.dock.setFolded(True))
        self.assertFalse(self.dock.property("folded"))
        self.assertEqual((self.window.width(), self.window.height()), (410, 76))

    def test_repeated_leave_and_moving_between_edges_do_not_delay_fold(self):
        self.window.navigate(0)
        QTest.qWait(300)
        self.desktop.pointer_override = False
        self.dock.setProperty("autoFoldEnabled", True)
        captures = PROJECT / "build/ui-compact-review"
        captures.mkdir(exist_ok=True)
        for x, y, label in [(350, 40, "top"), (0, 180, "left"), (870, 180, "right")]:
            self.dock.setFolded(False)
            self.dock.setProperty("attachment", 0)
            QTest.qWait(300)
            self.dock.beginMove()
            self.dock.beginMove()  # Brand and body must not start two system moves.
            self.window.setPosition(x, y)
            self.dock.finishMove()
            for _ in range(12):
                self.dock.setPointerInside(False)
                QTest.qWait(60)
            self.assertTrue(self.dock.property("folded"), label)
            QTest.qWait(220)
            self.window.grabWindow().save(str(captures / f"auto-fold-{label}.png"))
        self.dock.setProperty("autoFoldEnabled", False)

    def test_language_options_align_and_density_scales_in_all_appearances(self):
        languages = LanguageUiCatalog()
        self.window.setProperty("languageService", languages)
        controller = self.window.findChild(QObject, "windowController")
        deck = self.window.findChild(QObject, "toolContent")
        captures = PROJECT / "build/ui-compact-review"
        captures.mkdir(exist_ok=True)
        heights = []
        for theme in ["panel", "small", "classic", "large"]:
            controller.selectTheme(theme)
            self.window.navigate(4)
            QTest.qWait(400)
            deck.openPage("language")
            QTest.qWait(220)
            control = self.visual_item("languageSelectorControl")
            heights.append(control.height())
            self.click_item("languageSelectorControl")
            popup = self.window.findChild(QObject, "languageSelectorPopup")
            options = popup.findChild(QObject, "versionOptionsList")
            options.positionViewAtEnd()
            QTest.qWait(150)
            # Native RTL names retain their glyph order but share the menu's left alignment.
            row = self.visual_item("languageSelectorOption_yi_de")
            self.window.grabWindow().save(str(captures / f"languages-{theme}.png"))
            self.assertIsNotNone(row)
            self.click_item("languageSelectorControl")
            deck.goBack()
        self.assertEqual(heights, sorted(set(heights)))

    def test_theme_switch_preserves_input_and_floating_window(self):
        node = NodeUiProbe()
        self.window.setProperty("multiplayerService", node)
        self.release_at(851, 180)
        self.window.navigate(1)
        QTest.qWait(550)
        controller = self.window.findChild(QObject, "windowController")
        search = self.window.findChild(QObject, "searchInput")
        search.setProperty("text", "saved search")
        self.assertFalse(controller.selectTheme("unknown"))
        self.assertTrue(controller.selectTheme("classic"))
        for _ in range(30):
            QTest.qWait(20)
            self.assertEqual(self.window.x() + self.window.width(), 1280)
            self.assertGreaterEqual(self.window.width(), 410)
            self.assertLessEqual(self.window.width(), 960)
        self.assertTrue(self.dock.property("dockingEnabled"))
        self.assertEqual((self.window.width(), self.window.height()), (960, 600))
        self.assertEqual(self.window.flags() & Qt.WindowType_Mask, Qt.Tool)
        self.assertTrue(self.window.flags() & Qt.WindowStaysOnTopHint)
        toolbar = self.window.findChild(QObject, "floatingToolBar")
        divider = self.window.findChild(QObject, "headerDivider")
        self.assertLess(toolbar.property("y"), 20)
        self.assertLess(toolbar.property("y") + toolbar.property("height"), divider.property("y"))
        self.assertIsNone(self.window.findChild(QObject, "menuSurface"))
        navigation = self.window.findChild(QObject, "mainNavigation")
        self.assertEqual(navigation.property("items").toVariant(), ["启动", "广场", "联机", "好友"])
        self.assertTrue(navigation.property("underline"))
        self.assertEqual(self.window.findChild(QObject, "toolContent").property("pageTitle"), "广场")
        self.assertEqual(toolbar.property("height"), 60)
        self.assertFalse(toolbar.property("showWindowControls"))
        controls = self.window.findChild(QObject, "pageWindowControls")
        self.assertTrue(controls.property("visible"))
        self.assertLess(controls.property("y"), 50)
        self.assertGreater(controls.property("x"), self.window.width() * 0.8)
        self.assertLess(controls.property("x") + controls.property("width"), self.window.width())
        self.assertLess(toolbar.property("x") + toolbar.property("width"), controls.property("x"))
        self.assertEqual(search.property("text"), "saved search")
        self.assertTrue(controller.selectTheme("panel"))
        QTest.qWait(600)
        self.assertEqual((self.window.width(), self.window.height()), (410, 202))
        self.assertEqual(self.window.x() + self.window.width(), 1280)
        self.assertEqual(self.window.flags() & Qt.WindowType_Mask, Qt.Tool)
        self.assertTrue(self.window.flags() & Qt.WindowStaysOnTopHint)
        self.assertEqual(search.property("text"), "saved search")
        self.assertTrue(self.dock.property("dockingEnabled"))
        self.assertTrue(toolbar.property("showWindowControls"))
        controller.selectTheme("classic")
        QTest.qWait(500)
        collapse = controls.findChild(QObject, "collapseWindowButton")
        point = collapse.mapToScene(QPoint(int(collapse.width() / 2), int(collapse.height() / 2)))
        QTest.mouseClick(self.window, Qt.LeftButton, Qt.NoModifier, point.toPoint())
        QTest.qWait(650)
        self.assertEqual(controller.property("theme"), "classic")
        self.assertTrue(controller.property("collapsed"))
        self.assertEqual((self.window.width(), self.window.height()), (410, 76))
        self.assertTrue(self.window.isVisible())
        controller.selectTheme("classic")
        QTest.qWait(500)
        close = controls.findChild(QObject, "closeWindowButton")
        point = close.mapToScene(QPoint(int(close.width() / 2), int(close.height() / 2)))
        QTest.mouseClick(self.window, Qt.LeftButton, Qt.NoModifier, point.toPoint())
        QTest.qWait(30)
        self.assertFalse(self.window.isVisible())

    def test_identity_options_and_subpage_collapse_restore(self):
        controller = self.window.findChild(QObject, "windowController")
        controller.selectTheme("classic")
        QTest.qWait(550)
        deck = self.window.findChild(QObject, "toolContent")
        deck.openPage("identity")
        QTest.qWait(200)
        toolbar = self.window.findChild(QObject, "floatingToolBar")
        header = self.window.findChild(QObject, "contextHeader")

        click = self.click_item

        pending = self.visual_item("thirdPartyLoginOption")
        self.assertEqual(pending.property("text"), "第三方登录（待更新）")
        self.assertFalse(pending.property("enabled"))
        click("thirdPartyLoginOption")
        self.assertEqual(deck.property("route"), "identity")
        click("microsoftLoginOption")
        self.assertEqual(deck.property("route"), "deviceAuth")
        deck.goBack()
        QTest.qWait(200)
        click("offlineLoginOption")
        self.assertEqual(deck.property("route"), "offlineIdentity")
        loader = deck.findChild(QObject, "pageLoader")
        original_page = loader.property("item")
        original_history = deck.property("history").toVariant()

        click("collapseWindowButton")
        QTest.qWait(450)
        self.assertEqual((self.window.width(), self.window.height()), (410, 76))
        self.assertTrue(self.window.isVisible())
        self.assertTrue(controller.property("collapsed"))
        self.assertEqual(controller.property("theme"), "classic")
        self.assertTrue(toolbar.property("visible"))
        self.assertTrue(toolbar.property("enabled"))
        self.assertFalse(header.property("visible"))
        self.assertFalse(header.property("enabled"))
        self.assertEqual(deck.property("route"), "offlineIdentity")
        self.assertEqual(deck.property("history").toVariant(), original_history)

        # Use the actual restored toolbar entry, not a programmatic theme reset.
        navigation = self.visual_item("mainNavigation")
        point = navigation.mapToScene(QPoint(29, int(navigation.height() / 2)))
        QTest.mouseClick(self.window, Qt.LeftButton, Qt.NoModifier, point.toPoint())
        QTest.qWait(650)
        self.assertFalse(controller.property("collapsed"))
        self.assertEqual((self.window.width(), self.window.height()), (960, 600))
        self.assertEqual(deck.property("route"), "offlineIdentity")
        self.assertEqual(loader.property("item"), original_page)
        self.assertEqual(deck.property("history").toVariant(), original_history)
        self.assertTrue(header.property("visible"))
        self.assertFalse(toolbar.property("enabled"))
        deck.goBack()
        QTest.qWait(200)
        skin = self.visual_item("identitySkinOption")
        self.assertEqual(skin.property("value"), "待更新")
        self.assertFalse(skin.property("enabled"))
        click("identitySkinOption")
        self.assertEqual(deck.property("route"), "identity")
        click("collapseWindowButton")
        QTest.qWait(450)
        # Choosing a different entry still clears the old nested navigation.
        self.window.navigate(3)
        QTest.qWait(600)
        self.assertEqual(deck.property("route"), "")
        self.assertFalse(deck.property("canGoBack"))
        self.assertEqual(controller.property("theme"), "classic")

    def test_settings_theme_choices_and_floating_page_navigation(self):
        node = NodeUiProbe()
        self.window.setProperty("multiplayerService", node)
        self.window.navigate(4)
        QTest.qWait(550)
        row = self.visual_item("appearanceSettingsRow")
        point = row.mapToScene(QPoint(int(row.width() / 2), int(row.height() / 2)))
        QTest.mouseClick(self.window, Qt.LeftButton, Qt.NoModifier, point.toPoint())
        QTest.qWait(450)
        self.click_item("themeSelectorControl")
        selector = self.window.findChild(QObject, "themeSelector")
        self.assertIsNotNone(selector)
        self.assertTrue(QMetaObject.invokeMethod(selector, "themeRequested", Q_ARG(str, "classic")))
        QTest.qWait(600)
        controller = self.window.findChild(QObject, "windowController")
        self.assertEqual(controller.property("theme"), "classic")
        for tool in [0, 1, 2, 3, 4]:
            if self.window.property("activeTool") != tool:
                self.window.navigate(tool)
            QTest.qWait(400)
            self.assertEqual(self.window.property("activeTool"), tool)
            self.assertEqual((self.window.width(), self.window.height()), (960, 600))
        self.window.navigate(0)
        QTest.qWait(400)
        account = self.window.findChild(QObject, "homeAccountButton")
        point = account.mapToScene(QPoint(int(account.width() / 2), int(account.height() / 2)))
        QTest.mouseClick(self.window, Qt.LeftButton, Qt.NoModifier, point.toPoint())
        QTest.qWait(200)
        deck = self.window.findChild(QObject, "toolContent")
        self.assertEqual(deck.property("route"), "identity")
        toolbar = self.window.findChild(QObject, "floatingToolBar")
        header = self.window.findChild(QObject, "contextHeader")
        self.assertFalse(toolbar.property("visible"))
        self.assertFalse(toolbar.property("enabled"))
        self.assertTrue(header.property("visible"))
        self.assertLess(header.property("y"), 20)
        deck.openPage("offlineIdentity")
        QTest.qWait(200)
        back = header.findChild(QObject, "subpageBackButton")
        point = back.mapToScene(QPoint(int(back.width() / 2), int(back.height() / 2)))
        QTest.mouseClick(self.window, Qt.LeftButton, Qt.NoModifier, point.toPoint())
        QTest.qWait(200)
        self.assertEqual(deck.property("route"), "identity")
        self.assertFalse(toolbar.property("visible"))
        QTest.mouseClick(self.window, Qt.LeftButton, Qt.NoModifier, point.toPoint())
        QTest.qWait(220)
        self.assertEqual(deck.property("route"), "")
        self.assertTrue(toolbar.property("visible"))
        self.assertTrue(toolbar.property("enabled"))
        self.assertFalse(header.property("visible"))
        summary = self.window.findChild(QObject, "instanceButton")
        point = summary.mapToScene(QPoint(int(summary.width() / 2), int(summary.height() / 2)))
        QTest.mouseClick(self.window, Qt.LeftButton, Qt.NoModifier, point.toPoint())
        QTest.qWait(250)
        instance = self.visual_item("manageInstance2")
        point = instance.mapToScene(QPoint(int(instance.width() / 2), int(instance.height() / 2)))
        QTest.mouseClick(self.window, Qt.LeftButton, Qt.NoModifier, point.toPoint())
        QTest.qWait(30)
        self.assertEqual(self.window.property("selectedInstance"), 2)
        self.assertEqual(self.window.findChild(QObject, "toolContent").property("route"), "")
        self.assertIsNone(self.window.findChild(QObject, "manageInstancesButton"))
        launch = self.window.findChild(QObject, "launchButton")
        self.identity.use_offline("TestPlayer")
        point = launch.mapToScene(QPoint(int(launch.width() / 2), int(launch.height() / 2)))
        QTest.mouseClick(self.window, Qt.LeftButton, Qt.NoModifier, point.toPoint())
        QTest.qWait(200)
        self.assertEqual(self.window.findChild(QObject, "toolContent").property("route"), "")
        self.assertEqual(self.launch.status["state"], "preparing")
        self.assertFalse(self.visual_item("instanceButton").property("enabled"))
        self.window.navigate(4)
        QTest.qWait(400)
        self.window.findChild(QObject, "toolContent").openPage("appearance")
        QTest.qWait(250)
        selector = self.window.findChild(QObject, "themeSelector")
        self.assertIsNotNone(selector)
        self.assertTrue(QMetaObject.invokeMethod(selector, "themeRequested", Q_ARG(str, "panel")))
        QTest.qWait(600)
        self.assertEqual(controller.property("theme"), "panel")
        self.assertEqual(self.window.width(), 410)

    def test_toolbar_alignment_and_neutral_fold(self):
        controller = self.window.findChild(QObject, "windowController")
        for theme in ["panel", "classic"]:
            controller.selectTheme(theme)
            self.window.navigate(0)
            QTest.qWait(600)
            controls = [next(item for item in self.window.findChildren(QObject, name) if item.isVisible())
                        for name in ["settingsButton", "closeWindowButton"]]
            centers = [item.mapToScene(QPoint(int(item.width() / 2), int(item.height() / 2))).y()
                       for item in controls]
            self.assertLessEqual(abs(centers[0] - centers[1]), 1)
        self.release_at(170, 48)
        self.dock.setFolded(True)
        QTest.qWait(300)
        self.assertEqual((self.window.width(), self.window.height()), (88, 40))
        backdrop = self.visual_item("windowBackdrop")
        self.assertEqual(backdrop.property("opacity"), 0)
        self.assertFalse(backdrop.isVisible())
        handle = self.visual_item("dockHandle")
        point = handle.mapToScene(QPoint(int(handle.width() / 2), int(handle.height() / 2))).toPoint()
        QTest.mouseMove(self.window, point)
        QTest.qWait(160)
        self.assertTrue(handle.property("hovered"))
        self.assertGreater(handle.property("background").property("color").alpha(), 0)
        self.click_item("dockHandle")
        QTest.qWait(350)
        self.assertEqual((self.window.width(), self.window.height()), (960, 600))
        self.assertEqual(self.window.property("activeTool"), 0)
        self.assertTrue(backdrop.isVisible())
        controller.setProperty("collapsed", True)
        self.window.navigate(-1)
        QTest.qWait(600)
        self.assertFalse(backdrop.isVisible())
        self.assertEqual((self.window.width(), self.window.height()), (410, 76))

    def test_plain_friend_list_and_game_search(self):
        controller = self.window.findChild(QObject, "windowController")
        controller.selectTheme("classic")
        self.window.navigate(3)
        QTest.qWait(600)
        self.assertIsNotNone(self.visual_item("nodeLogin"))
        self.assertIsNone(self.visual_item("friendRow0"))
        self.assertIsNone(self.visual_item("friendDetailName"))
        deck = self.window.findChild(QObject, "toolContent")
        self.assertFalse(deck.property("showPageHeader"))
        deck.setProperty("friends", [{"name": "TestFriend", "online": True}])
        QTest.qWait(100)
        self.assertIsNone(self.visual_item("friendRow0"))
        self.assertEqual(len(self.app.topLevelWindows()), 1)
        self.window.navigate(0)
        QTest.qWait(400)
        self.click_item("instanceButton")
        search = self.visual_item("instanceSearchField")
        search.setProperty("text", "forge")
        self.assertTrue(QMetaObject.invokeMethod(search, "textEdited"))
        QTest.qWait(60)
        self.assertTrue(self.visual_item("manageInstance0").isVisible())
        self.assertIsNone(self.visual_item("manageInstance1"))
        self.assertTrue(self.visual_item("manageInstance2").isVisible())
        search.setProperty("text", "NO_MATCH")
        self.assertTrue(QMetaObject.invokeMethod(search, "textEdited"))
        QTest.qWait(50)
        self.assertIsNone(self.visual_item("manageInstance0"))
        search.setProperty("text", "1.20")
        self.assertTrue(QMetaObject.invokeMethod(search, "textEdited"))
        QTest.qWait(50)
        self.click_item("manageInstance2")
        self.assertEqual(self.window.property("selectedInstance"), 2)
        self.assertEqual(self.window.findChild(QObject, "toolContent").property("route"), "")

    def test_compact_home_and_navigation_shape_transition(self):
        self.window.navigate(0)
        QTest.qWait(500)
        instance = self.visual_item("instanceButton")
        launch = self.visual_item("launchButton")
        self.assertEqual((self.window.width(), self.window.height()), (410, 148))
        self.assertLess(instance.x() + instance.width(), launch.x())
        self.assertAlmostEqual(instance.y() + instance.height() / 2,
                               launch.y() + launch.height() / 2, delta=1)
        self.assertFalse(self.visual_item("homeAccountButton").isVisible())
        # 压缩内容不丢失实际失败恢复操作。
        self.identity.use_offline("PanelPlayer")
        self.launch.obj.setProperty("preview_enabled", False)
        self.click_item("launchButton")
        self.assertEqual(self.launch.status["state"], "failed")
        self.click_item("launchSecondaryButton")
        self.assertEqual(self.launch.status["state"], "idle")
        controller = self.window.findChild(QObject, "windowController")
        controller.selectTheme("classic")
        QTest.qWait(600)
        self.click_item("collapseWindowButton", settle_ms=0)
        for _ in range(25):
            QTest.qWait(16)
            marker = self.visual_item("navigationSelection")
            nav = marker.parentItem()
            self.assertGreaterEqual(marker.y(), 0)
            self.assertLessEqual(marker.y() + marker.height(), nav.height() + 1)
        self.assertEqual((self.window.width(), self.window.height()), (410, 76))

    def test_background_selection_rotation_and_pause(self):
        with tempfile.TemporaryDirectory(prefix="bugg-backgrounds-") as directory:
            urls = []
            for index, color in enumerate(["#BF3030", "#30AF50"]):
                path = Path(directory) / f"scene-{index}.png"
                image = QImage(128, 80, QImage.Format_ARGB32)
                image.fill(QColor(color))
                self.assertTrue(image.save(str(path)))
                urls.append(QUrl.fromLocalFile(str(path)).toString())
            controller = self.window.findChild(QObject, "windowController")
            controller.selectTheme("classic")
            self.window.navigate(4)
            QTest.qWait(600)
            deck = self.window.findChild(QObject, "toolContent")
            deck.openPage("appearance")
            QTest.qWait(200)
            picker = self.window.findChild(QObject, "backgroundFilePicker")
            picker.filesChosen.emit(urls)
            QTest.qWait(650)
            store = self.window.findChild(QObject, "pageStateStore")
            self.assertEqual(store.property("values")["appearance.backgrounds"], urls)
            backdrop = self.visual_item("windowBackdrop")
            timer = self.window.findChild(QObject, "backdropRotationTimer")
            self.assertFalse(timer.property("running"))
            deck.goBack()
            self.window.navigate(0)
            QTest.qWait(450)
            self.assertTrue(timer.property("running"))
            backdrop.setProperty("interval", 600)
            initial_source = backdrop.property("currentSource")
            for _ in range(25):
                QTest.qWait(60)
                if backdrop.property("currentSource") != initial_source:
                    break
            self.assertNotEqual(backdrop.property("currentSource"), initial_source)
            # 真实画面随来源切换，而非仅修改页码。
            QTest.qWait(60)
            sample = backdrop.mapToScene(QPoint(180, 180)).toPoint()
            pixel = self.window.grabWindow().pixelColor(sample)
            self.assertGreater(pixel.green(), pixel.red())
            self.window.navigate(3)
            QTest.qWait(500)
            self.assertFalse(timer.property("running"))
            paused_source = backdrop.property("currentSource")
            QTest.qWait(750)
            self.assertEqual(backdrop.property("currentSource"), paused_source)
            self.window.navigate(4)
            QTest.qWait(350)
            deck.openPage("appearance")
            QTest.qWait(200)
            self.assertIn("2", self.visual_item("backgroundPickerRow").property("value"))
            self.click_item("resetBackgroundButton")
            QTest.qWait(200)
            self.assertEqual(store.property("values")["appearance.backgrounds"], [])
            self.assertFalse(timer.property("running"))
            QTest.qWait(500)
            self.assertIn("siege-", backdrop.property("currentSource").toString())

    def test_background_errors_skip_and_keep_current_image(self):
        with tempfile.TemporaryDirectory(prefix="bugg-bad-background-") as directory:
            path = Path(directory) / "valid.png"
            image = QImage(128, 80, QImage.Format_ARGB32)
            image.fill(QColor("#3050A0"))
            self.assertTrue(image.save(str(path)))
            valid = QUrl.fromLocalFile(str(path)).toString()
            missing = QUrl.fromLocalFile(str(Path(directory) / "missing.png")).toString()
            controller = self.window.findChild(QObject, "windowController")
            controller.selectTheme("classic")
            self.window.navigate(0)
            QTest.qWait(600)
            deck = self.window.findChild(QObject, "toolContent")
            backdrop = self.visual_item("windowBackdrop")
            try:
                deck.draftEdited.emit("appearance.backgrounds", [missing, valid])
                for _ in range(50):
                    QTest.qWait(60)
                    if backdrop.property("currentSource").toString() == valid:
                        break
                self.assertEqual(backdrop.property("currentSource").toString(), valid)
                deck.draftEdited.emit("appearance.backgrounds", [missing, missing + "2"])
                QTest.qWait(600)
                self.assertEqual(backdrop.property("pendingIndex"), -1)
                self.assertEqual(backdrop.property("currentSource").toString(), valid)
            finally:
                # 本测试故意制造图片加载失败；仅放行对应资源报告。
                self.warnings[:] = [message for message in self.warnings
                                    if "missing.png" not in message]

    def test_quick_identity_menu_and_no_instance_hover(self):
        controller = self.window.findChild(QObject, "windowController")
        controller.selectTheme("classic")
        self.identity.use_offline("FirstPlayer")
        self.identity.use_offline("SecondPlayer")
        self.window.navigate(0)
        QTest.qWait(600)
        deck = self.window.findChild(QObject, "toolContent")
        self.click_item("profileMenuButton")
        self.assertEqual(deck.property("route"), "")
        captures = PROJECT / "build" / "ui-room-review"
        captures.mkdir(exist_ok=True)
        self.window.grabWindow().save(str(captures / "identity-menu-classic.png"))
        self.click_item("profileChoice_offline:FirstPlayer")
        self.assertEqual(self.identity.status["name"], "FirstPlayer")
        self.assertEqual(deck.property("route"), "")
        self.click_item("homeAccountButton")
        self.assertEqual(deck.property("route"), "identity")
        deck.goBack()
        QTest.qWait(200)
        instance = self.visual_item("instanceButton")
        QTest.mouseMove(self.window, QPoint(2, 2))
        QTest.qWait(80)
        background = instance.property("background")
        resting_color = background.property("color")
        point = instance.mapToScene(QPoint(int(instance.width() / 2), int(instance.height() / 2))).toPoint()
        QTest.mouseMove(self.window, point)
        QTest.qWait(160)
        self.assertTrue(background.isVisible())
        self.assertEqual(background.property("color"), resting_color)
        self.click_item("profileMenuButton")
        popup = self.window.findChild(QObject, "profileMenu")
        self.assertTrue(popup.property("opened"))
        controller.setProperty("collapsed", True)
        self.window.navigate(-1)
        QTest.qWait(600)
        self.assertFalse(popup.property("opened"))
        controller.selectTheme("classic")
        QTest.qWait(600)
        self.launch.start(0)
        QTest.qWait(160)
        self.assertFalse(self.visual_item("homeAccountButton").isEnabled())
        deck.identitySelected.emit("offline:SecondPlayer")
        self.assertEqual(self.identity.status["name"], "FirstPlayer")

    def test_home_shortcut_direct_identity_and_stable_game_rows(self):
        controller = self.window.findChild(QObject, "windowController")
        controller.selectTheme("classic")
        QTest.qWait(600)
        self.window.navigate(0)
        QTest.qWait(400)
        deck = self.window.findChild(QObject, "toolContent")
        self.click_item("profileMenuButton")
        self.assertEqual(deck.property("route"), "identity")
        self.assertIsNone(self.visual_item("profileChoice_offline:FirstPlayer"))
        self.click_item("subpageHomeButton")
        self.assertEqual(deck.property("route"), "")
        self.click_item("instanceButton")
        row = self.visual_item("manageInstance1Row")
        background = row.property("background")
        before = background.property("color")
        point = row.mapToScene(QPoint(int(row.width() / 2), int(row.height() / 2))).toPoint()
        QTest.mouseMove(self.window, point)
        QTest.qWait(180)
        self.assertTrue(row.property("hovered"))
        hovered_color = background.property("color")
        QTest.qWait(180)
        self.assertEqual(background.property("color"), hovered_color)
        for theme in ["classic", "panel"]:
            controller.selectTheme(theme)
            self.window.navigate(4)
            QTest.qWait(600)
            deck.openPage("instances")
            deck.openPage("install")
            QTest.qWait(200)
            self.click_item("subpageHomeButton", 500)
            self.assertEqual(deck.property("route"), "")
            self.assertFalse(deck.property("canGoBack"))
            self.assertEqual(self.window.property("activeTool"), 0)
            self.assertFalse(controller.property("collapsed"))
            self.assertEqual(self.window.width(), 960 if theme == "classic" else 410)

    def test_install_selectors_search_virtualize_and_emit(self):
        controller = self.window.findChild(QObject, "windowController")
        controller.selectTheme("classic")
        self.window.navigate(0)
        QTest.qWait(600)
        deck = self.window.findChild(QObject, "toolContent")
        deck.openPage("install")
        QTest.qWait(200)
        # Explicit renderer fixture; native catalog rules are tested in catalog_test.cpp.
        snapshot = {"games": [{"id": f"1.21.{i}", "name": f"1.21.{i}", "caption": ""}
                              for i in range(500)], "loaders": [], "game": "1.21.499",
                    "loader": "vanilla", "instanceName": "1.21.499", "ready": True}
        deck.setProperty("installCatalog", snapshot)
        chosen = []
        deck.gameVersionSelected.connect(chosen.append)
        QTest.qWait(80)
        control = self.visual_item("minecraftVersionFieldControl")
        self.assertEqual(control.property("displayText"), "1.21.499")
        # Two fields share the same hover feedback, rather than per-page handlers.
        background = control.property("background")
        QTest.mouseMove(self.window, QPoint(2, 2))
        QTest.qWait(160)
        rest = background.property("color")
        self.hover_item(control)
        self.assertTrue(control.property("hovered"))
        self.assertNotEqual(background.property("color"), rest)
        self.click_item("minecraftVersionFieldControl")
        QTest.qWait(100)
        popup = self.window.findChild(QObject, "minecraftVersionFieldPopup")
        self.assertTrue(popup.property("opened"))
        options = popup.findChild(QObject, "versionOptionsList")
        self.assertEqual(options.property("count"), 500)
        # Hundreds of options are a ListView, not hundreds of eagerly created cards.
        self.assertLess(len(options.property("contentItem").childItems()), 30)
        # ComboBox opens near the selected last row; scroll before testing the first.
        options.setProperty("contentY", 0)
        QTest.qWait(100)
        row = self.visual_item("minecraftVersionFieldOption_1.21.0")
        self.assertIsNotNone(row)
        row_background = row.property("background")
        self.assertFalse(row_background.property("animateFeedback"))
        rest = row_background.property("color")
        self.hover_item(row)
        self.assertTrue(row.property("hovered"))
        self.assertNotEqual(row_background.property("color"), rest)
        # Background status must not recreate the list or jump its scroll position.
        options.setProperty("contentY", 220)
        snapshot.update(refreshing=True, loaderSource="BUGG")
        deck.setProperty("installCatalog", snapshot)
        QTest.qWait(60)
        self.assertTrue(popup.property("opened"))
        self.assertEqual(options.property("contentY"), 220)
        search = popup.findChild(QObject, "versionSearchField")
        search.setProperty("text", "1.21.287")
        QTest.qWait(100)
        QTest.keyClick(self.window, Qt.Key_Return)
        QTest.qWait(80)
        self.assertEqual(chosen, ["1.21.287"])
        self.assertFalse(popup.property("opened"))

        for theme in ["classic", "panel"]:
            controller.selectTheme(theme)
            QTest.qWait(500)
            snapshot.update(loader="fabric", loaderSource="BMCLAPI",
                            loaders=[{"id": "0.20.1", "name": "0.20.1"}],
                            loaderVersion="0.20.1", instanceName="1.21.499-fabric-0.20.1")
            deck.setProperty("installCatalog", snapshot)
            QTest.qWait(100)
            self.assertIsNone(self.visual_item("loaderCatalogSource"))
            name = self.visual_item("installInstanceName")
            self.assertFalse(name.isVisible())
            self.click_item("editInstallNameButton")
            self.assertTrue(name.isVisible())
            self.click_item("editInstallNameButton")
            self.click_item("loaderVersionFieldControl")
            self.assertTrue(self.window.findChild(QObject, "loaderVersionFieldPopup").property("opened"))
            self.click_item("loaderVersionFieldOption_0.20.1")
            self.assertEqual(self.window.width(), 960 if theme == "classic" else 410)

    def test_toolbar_tasks_and_current_game_management(self):
        controller = self.window.findChild(QObject, "windowController")
        controller.selectTheme("classic")
        self.window.navigate(0)
        QTest.qWait(600)
        deck = self.window.findChild(QObject, "toolContent")
        for theme in ["classic", "panel"]:
            controller.selectTheme(theme)
            QTest.qWait(500)
            tasks = self.visual_item("downloadTasksButton")
            settings = self.visual_item("settingsButton")
            self.assertTrue(tasks.isVisible())
            self.assertTrue(settings.isVisible())
            task_point = tasks.mapToScene(QPoint(int(tasks.width()), 0))
            settings_point = settings.mapToScene(QPoint(0, 0))
            self.assertLessEqual(task_point.x(), settings_point.x())
            self.click_item("downloadTasksButton")
            self.assertEqual(deck.property("route"), "tasks")
            self.assertTrue(self.visual_item("contextHeader").isVisible())
            deck.goHome()
            QTest.qWait(250)
            self.click_item("instanceButton")
            self.click_item("manageInstancesButton")
            self.assertEqual(deck.property("route"), "instance")
            self.assertEqual(deck.property("pageTitle"), "百日围城")
            self.assertFalse(any(button.isVisible() for button in self.window.findChildren(QObject, "startGameButton")))
            self.assertEqual(self.window.width(), 960 if theme == "classic" else 410)
            deck.goHome()
            QTest.qWait(250)

    def test_translation_settings_and_compact_node_login(self):
        languages = LanguageUiCatalog()
        self.window.setProperty("languageService", languages)
        node = NodeUiProbe()
        node.snapshot = {"state": "signedOut"}
        self.window.setProperty("multiplayerService", node)
        controller = self.window.findChild(QObject, "windowController")
        deck = self.window.findChild(QObject, "toolContent")
        captures = PROJECT / "build/resource-ui-review"
        captures.mkdir(exist_ok=True)
        for theme in ["panel", "classic"]:
            deck.draftEdited.emit("multiplayer.custom", False)
            controller.selectTheme(theme)
            self.window.navigate(2)
            QTest.qWait(500)
            self.assertIsNone(self.visual_item("customMultiplayerServiceOption"))
            self.window.grabWindow().save(str(captures / f"node-login-{theme}.png"))
            self.click_item("nodeServiceSettingsButton")
            self.assertEqual(deck.property("route"), "multiplayerSettings")
            QTest.qWait(220)
            self.window.grabWindow().save(str(captures / f"node-settings-default-{theme}.png"))
            self.click_item("customMultiplayerServiceOption")
            QTest.qWait(100)
            self.assertTrue(self.visual_item("multiplayerServiceOriginField").isVisible())
            self.window.grabWindow().save(str(captures / f"node-settings-custom-{theme}.png"))
            deck.goBack()
            node.snapshot = {"state": "authorizing", "verificationUrl": "https://test.example/account/access"}
            node.changed.emit()
            QTest.qWait(160)
            self.window.grabWindow().save(str(captures / f"node-login-waiting-{theme}.png"))
            node.snapshot = {"state": "signedOut", "error": "授权已失效，请重新登录。"}
            node.changed.emit()
            QTest.qWait(120)
            self.window.grabWindow().save(str(captures / f"node-login-error-{theme}.png"))
            node.snapshot = {"state": "signedOut", "authorized": True, "error": "账号已授权，暂时没有可用的联机节点，请重试连接。"}
            node.changed.emit()
            QTest.qWait(120)
            self.window.grabWindow().save(str(captures / f"node-login-retry-{theme}.png"))
            node.snapshot = {"state": "signedOut"}
            node.changed.emit()
            self.window.navigate(4)
            QTest.qWait(250)
            self.window.grabWindow().save(str(captures / f"settings-{theme}.png"))
            last = self.visual_item("updateSettingsRow")
            last_bottom = last.mapToScene(QPoint(0, int(last.height()))).y()
            self.assertLess(last_bottom, self.window.height() - 8)
            deck.openPage("language")
            QTest.qWait(220)
            self.assertTrue(self.visual_item("contentTranslationOption").property("checked"))
            self.window.grabWindow().save(str(captures / f"language-translation-{theme}.png"))
            deck.goHome()
            QTest.qWait(150)

    def test_update_page_states_use_native_service_intents(self):
        service = UpdateUiProbe()
        self.window.setProperty("updateService", service)
        controller = self.window.findChild(QObject, "windowController")
        deck = self.window.findChild(QObject, "toolContent")
        captures = PROJECT / "build/resource-ui-review"
        captures.mkdir(exist_ok=True)
        states = {
            "latest": {}, "checking": {},
            "error": {"error": "暂时无法连接更新服务，请稍后重试。"},
            "available": {"version": "2.0.2", "automaticPackage": True, "notes": "修复联机授权后的连接，并优化资源译文显示。"},
            "downloading": {"progress": .45, "detail": "正在下载更新包 · 12.4 MiB / 27.5 MiB"},
            "ready": {"version": "2.0.2", "notes": "更新已通过完整性校验。"},
        }
        for theme in ["panel", "small", "classic", "large"]:
            controller.selectTheme(theme)
            self.window.navigate(4)
            QTest.qWait(300)
            deck.openPage("update")
            for state, fields in states.items():
                service.snapshot = {"state": state, "currentVersion": "2.0.1", **fields}
                service.changed.emit()
                QTest.qWait(130)
                self.window.grabWindow().save(str(captures / f"update-{state}-{theme}.png"))
                if state in ["available", "ready"]:
                    self.click_item("installLauncherUpdateButton")
                if state == "available":
                    deck.goBack()
                    QTest.qWait(100)
                    self.window.grabWindow().save(str(captures / f"settings-update-{theme}.png"))
                    deck.openPage("update")
            deck.goHome()
        self.assertEqual(service.calls, ["download", "install"] * 4)

    def test_task_history_control_emits_only_and_keeps_active_rows(self):
        controller = self.window.findChild(QObject, "windowController")
        deck = self.window.findChild(QObject, "toolContent")
        captures = PROJECT / "build/ui-compact-review"
        captures.mkdir(exist_ok=True)
        fixtures = [
            {"id": "active", "name": "Install game", "kind": "install", "state": "running", "progress": .4},
            {"id": "waiting", "name": "Import modpack", "kind": "import", "state": "queued"},
            {"id": "finished", "name": "Export modpack", "kind": "export", "state": "done"},
        ]
        for theme in ["panel", "classic"]:
            controller.selectTheme(theme)
            self.window.navigate(0)
            QTest.qWait(450)
            deck.setProperty("tasks", fixtures)
            deck.openPage("tasks")
            QTest.qWait(250)
            page = deck.findChild(QObject, "pageLoader").property("item")
            requests = []
            page.clearRequested.connect(lambda: requests.append(True))
            self.assertTrue(self.visual_item("clearTaskHistoryButton").isEnabled())
            self.window.grabWindow().save(str(captures / f"tasks-history-{theme}.png"))
            self.click_item("clearTaskHistoryButton")
            self.assertEqual(requests, [True])
            # Production clear/persist semantics are covered by RuntimeTest;
            # this explicit fixture only checks presentation after its snapshot.
            deck.setProperty("tasks", fixtures[:2])
            QTest.qWait(100)
            self.assertFalse(self.visual_item("clearTaskHistoryButton").isEnabled())
            self.window.grabWindow().save(str(captures / f"tasks-active-{theme}.png"))
            deck.setProperty("tasks", [])
            QTest.qWait(100)
            self.window.grabWindow().save(str(captures / f"tasks-empty-{theme}.png"))
            deck.goHome()

    def test_toolbar_reuses_real_activity_surface_and_hides_square_in_panel(self):
        node = NodeUiProbe()
        self.window.setProperty("multiplayerService", node)
        controller = self.window.findChild(QObject, "windowController")
        for theme, ids in [("classic", [0, 1, 2, 3]), ("panel", [0, 2, 3])]:
            controller.selectTheme(theme)
            self.window.navigate(0)
            QTest.qWait(550)
            toolbar = self.window.findChild(QObject, "floatingToolBar")
            navigation = self.window.findChild(QObject, "mainNavigation")
            self.assertEqual(navigation.property("toolIds").toVariant(), ids)
            surface = self.window.findChild(QObject, "toolbarActivity")
            toolbar.setProperty("activity", {"active": True, "progress": 0.4})
            QTest.qWait(100)
            self.assertTrue(surface.property("active"))
            self.assertAlmostEqual(surface.property("fraction"), 0.4)
            phase = surface.property("phase")
            QTest.qWait(100)
            self.assertNotEqual(phase, surface.property("phase"))
            toolbar.setProperty("activity", {"active": False, "progress": 1})
            QTest.qWait(50)
            phase = surface.property("phase")
            QTest.qWait(100)
            self.assertFalse(surface.property("active"))
            self.assertEqual(phase, surface.property("phase"))

    def test_source_priority_reuses_controls(self):
        controller = self.window.findChild(QObject, "windowController")
        controller.selectTheme("classic")
        self.window.navigate(4)
        QTest.qWait(600)
        deck = self.window.findChild(QObject, "toolContent")
        for theme in ["classic", "panel"]:
            controller.selectTheme(theme)
            QTest.qWait(500)
            self.click_item("downloadsSettingsRow")
            self.click_item("downloadSourcesRow")
            self.assertFalse(self.visual_item("sourceUp_BUGG").isEnabled())
            self.assertFalse(self.visual_item("sourceDown_官方").isEnabled())
            self.click_item("sourceUp_BMCLAPI")
            self.assertFalse(self.visual_item("sourceUp_BMCLAPI").isEnabled())
            deck.goBack()
            QTest.qWait(100)
            self.assertEqual(self.visual_item("downloadSourcesRow").property("value"), "BMCLAPI 优先")
            self.click_item("downloadSourcesRow")
            self.click_item("sourceUp_BUGG")
            deck.goBack()
            QTest.qWait(100)
            self.assertEqual(self.visual_item("downloadSourcesRow").property("value"), "BUGG 优先")
            self.assertEqual(self.window.width(), 960 if theme == "classic" else 410)
            deck.goBack()
            QTest.qWait(100)

    def test_settings_memory_reuses_one_editor_without_save(self):
        controller = self.window.findChild(QObject, "windowController")
        self.window.navigate(4)
        QTest.qWait(500)
        deck = self.window.findChild(QObject, "toolContent")
        for theme in ["classic", "panel"]:
            controller.selectTheme(theme)
            QTest.qWait(500)
            deck.openPage("gameSettings")
            QTest.qWait(250)
            page = deck.findChild(QObject, "pageLoader").property("item")
            self.assertEqual(page.objectName(), "gameSettingsPage")
            page.setProperty("environment", {"maximumMemoryMB": 8192, "totalMB": 16384, "availableMB": 10240})
            page.setProperty("configuration", {"automatic": False, "memoryMB": 3072})
            QTest.qWait(100)
            slider = self.visual_item("memorySlider")
            self.assertTrue(slider.isVisible())
            self.assertTrue(slider.isEnabled())
            self.assertEqual(slider.property("value"), 3072)
            edits = []
            page.settingEdited.connect(lambda key, value: edits.append((key, value)))
            self.click_item("automaticMemoryOption")
            self.assertIn(("automatic", True), edits)
            page.setProperty("configuration", {"automatic": True, "memoryMB": 3072})
            QTest.qWait(80)
            self.assertFalse(slider.isEnabled())
            self.assertFalse(self.visual_item("memoryValueField").isVisible())
            self.assertFalse(any(item.property("text") == "保存设置" for item in page.findChildren(QObject)))
            deck.goBack()
            QTest.qWait(100)

    def test_dropdowns_fit_overlay_and_instances_only_scroll_inside_list(self):
        controller = self.window.findChild(QObject, "windowController")
        deck = self.window.findChild(QObject, "toolContent")
        captures = PROJECT / "build" / "ui-detail-review"
        captures.mkdir(exist_ok=True)
        for theme in ["classic", "panel"]:
            controller.selectTheme(theme)
            self.window.navigate(4)
            QTest.qWait(500)
            deck.openPage("general")
            QTest.qWait(300)
            self.click_item("afterLaunchSelectorControl")
            popup = self.window.findChild(QObject, "afterLaunchSelectorPopup")
            self.assertTrue(popup.property("opened"))
            self.assertGreaterEqual(popup.property("y"), 0)
            self.assertLessEqual(popup.property("y") + popup.property("height"),
                                 self.window.height())
            options = popup.findChild(QObject, "versionOptionsList")
            self.assertGreaterEqual(options.property("height"), options.property("contentHeight"))
            self.assertFalse(popup.findChild(QObject, "versionSearchField").isVisible())
            self.window.grabWindow().save(str(captures / f"dropdown-{theme}.png"))
            self.click_item("afterLaunchSelectorOption_keep")
            self.assertFalse(popup.property("opened"))
            deck.goHome()
            QTest.qWait(350)
            self.window.setProperty("instances", [
                {"id": str(i), "name": f"Game {i}", "version": "1.21.1", "loader": "NeoForge"}
                for i in range(40)])
            deck.openPage("selectInstance")
            QTest.qWait(350)
            viewport = self.visual_item("instancesViewport")
            footer = self.visual_item("instancesFooter")
            outer = self.window.findChild(QObject, "pageScrollView").property("contentItem")
            footer_y = footer.mapToScene(QPoint(0, 0)).y()
            self.assertLessEqual(footer_y + footer.height(), self.window.height())
            viewport.setProperty("contentY", 900)
            QTest.qWait(100)
            self.assertEqual(footer.mapToScene(QPoint(0, 0)).y(), footer_y)
            self.assertEqual(outer.property("contentY"), 0)
            self.assertLessEqual(outer.property("contentHeight"), outer.property("height"))
            self.window.grabWindow().save(str(captures / f"instances-{theme}.png"))
            deck.goHome()
            deck.openPage("exportPack")
            QTest.qWait(150)
            picker = self.window.findChild(QObject, "packExportFilePicker")
            self.assertTrue(picker.property("saveMode"))
            # Qt FileDialog.SaveFile permits a new file; no pre-created target is needed.
            mode = QQmlExpression(self.engine.rootContext(), picker, "fileMode === 2")
            self.assertTrue(mode.evaluate()[0])
            self.assertTrue(picker.property("suggestedName").endswith(".buggpack"))
            self.window.grabWindow().save(str(captures / f"export-{theme}.png"))
            deck.goHome()

    def test_home_waits_for_real_instances_before_install_offer(self):
        controller = self.window.findChild(QObject, "windowController")
        controller.selectTheme("classic")
        self.window.navigate(0)
        QTest.qWait(600)
        deck = self.window.findChild(QObject, "toolContent")
        deck.setProperty("loadingInstances", True)
        self.window.setProperty("instances", [])
        QTest.qWait(100)
        self.assertEqual(self.visual_item("launchButton").property("text"), "正在加载…")
        self.assertFalse(self.visual_item("launchButton").isEnabled())
        self.window.setProperty("instances", [{"id": "real", "name": "Real", "version": "1.21.1", "loader": "Minecraft"}])
        deck.setProperty("loadingInstances", False)
        QTest.qWait(100)
        self.assertEqual(self.visual_item("launchButton").property("text"), "选择账号")
        self.assertTrue(self.visual_item("launchButton").isEnabled())
        self.click_item("launchButton")
        self.assertEqual(deck.property("route"), "identity")

    def test_page_drafts_survive_loader_recreation(self):
        controller = self.window.findChild(QObject, "windowController")
        controller.selectTheme("classic")
        self.window.navigate(1)
        QTest.qWait(600)
        search = self.visual_item("searchInput")
        search.setProperty("text", "cataclysm")
        search.textEdited.emit()
        self.window.navigate(3)
        QTest.qWait(400)
        self.window.navigate(1)
        QTest.qWait(400)
        self.assertEqual(self.visual_item("searchInput").property("text"), "cataclysm")
        deck = self.window.findChild(QObject, "toolContent")
        deck.openPage("offlineIdentity")
        QTest.qWait(200)
        name = self.visual_item("offlineNameField")
        name.setProperty("text", "DraftPlayer")
        name.textEdited.emit("DraftPlayer")
        deck.goBack()
        deck.openPage("offlineIdentity")
        QTest.qWait(200)
        self.assertEqual(self.visual_item("offlineNameField").property("text"), "DraftPlayer")
        self.assertFalse(self.identity.status["ready"])

    def test_default_ui_hides_unconnected_service_fixtures(self):
        self.identity.obj.setProperty("preview_enabled", False)
        self.launch.obj.setProperty("preview_enabled", False)
        controller = self.window.findChild(QObject, "windowController")
        controller.selectTheme("classic")
        self.window.navigate(0)
        QTest.qWait(600)
        deck = self.window.findChild(QObject, "toolContent")
        deck.openPage("deviceAuth")
        QTest.qWait(200)
        self.assertTrue(self.visual_item("microsoftAuthButton").isEnabled())
        self.assertEqual(self.visual_item("microsoftAuthButton").property("text"), "登录微软账号")
        for route in ["taskFiles", "nodes", "catalog", "logs"]:
            deck.goBack()
            deck.openPage(route)
            QTest.qWait(200)
            self.assertIsNotNone(self.visual_item("serviceUnavailable"), route)
            self.assertIsNone(self.visual_item("cancelTaskButton"), route)
        for route in ["room", "sync"]:
            deck.goBack()
            deck.openPage(route)
            QTest.qWait(150)
            self.assertFalse(any(button.isVisible() and button.isEnabled() for name in
                ["roomLaunchButton", "syncRoomButton"] for button in self.window.findChildren(QObject, name)))
        self.assertFalse(deck.property("previewEnabled"))

    def test_settings_logout_and_window_cleanup(self):
        controller = self.window.findChild(QObject, "windowController")
        controller.selectTheme("classic")
        self.identity.use_offline("LocalPlayer")
        self.identity.begin_microsoft()
        self.identity.complete_microsoft()
        self.identity.finish_microsoft()
        self.window.navigate(4)
        QTest.qWait(600)
        self.click_item("accountSettingsRow")
        self.click_item("logoutMicrosoftButton")
        self.assertEqual(self.identity.status["kind"], "offline")
        self.assertEqual(self.identity.status["name"], "LocalPlayer")
        self.assertEqual(self.identity.status["microsoftName"], "")
        self.assertFalse(self.visual_item("logoutMicrosoftButton").isVisible())
        self.identity.begin_microsoft()
        self.identity.complete_microsoft()
        self.identity.finish_microsoft()
        self.launch.start(0)
        QTest.qWait(30)
        self.assertFalse(self.visual_item("logoutMicrosoftButton").isEnabled())
        self.identity.logout_microsoft()  # Direct model manipulation only drives shutdown setup.
        self.identity.begin_microsoft()
        self.identity.complete_microsoft()
        self.window.close()
        self.assertEqual(self.launch.status["state"], "idle")
        self.assertEqual(self.identity.status["authState"], "idle")
        self.identity.finish_microsoft()
        self.launch.advance()
        self.assertEqual(self.identity.status["kind"], "offline")
        self.assertEqual(self.launch.status["state"], "idle")

    def test_home_background_has_no_white_corner_flash(self):
        controller = self.window.findChild(QObject, "windowController")
        controller.selectTheme("classic")
        QTest.qWait(600)
        self.window.navigate(0)
        QTest.qWait(450)
        backdrop = self.visual_item("windowBackdrop")
        corners = [
            backdrop.mapToScene(QPoint(x, y)).toPoint()
            for x in (5, int(backdrop.width()) - 6)
            for y in (4, int(backdrop.height()) - 5)
        ]
        for tool in (1, 0, 4, 0):
            self.window.navigate(tool)
            fading_frames = 0
            for _ in range(24):
                QTest.qWait(16)
                # 180 ms 动画可能合并首帧；35% 背景时同步底色仍应明显低于白色。
                if 0.35 < backdrop.property("opacity") < 0.99:
                    frame = self.window.grabWindow()
                    for point in corners:
                        pixel = frame.pixelColor(point)
                        self.assertGreater(pixel.alpha(), 200)
                        self.assertLess(pixel.red(), 200, "Background still visible but corner flashed white")
                    fading_frames += 1
            self.assertGreater(fading_frames, 0)
            frame = self.window.grabWindow()
            for point in corners:
                if tool == 0:
                    self.assertLess(frame.pixelColor(point).red(), 120)
                else:
                    self.assertGreater(frame.pixelColor(point).red(), 245)

    def test_identity_selection_and_simulated_microsoft_flow(self):
        controller = self.window.findChild(QObject, "windowController")
        controller.selectTheme("classic")
        QTest.qWait(550)
        deck = self.window.findChild(QObject, "toolContent")
        deck.openPage("identity")
        QTest.qWait(200)

        click = self.click_item

        summary = self.visual_item("identitySummary")
        avatar = self.visual_item("identityAvatar")
        self.assertAlmostEqual(avatar.x() + avatar.width() / 2, summary.width() / 2, delta=1)
        self.assertAlmostEqual(self.visual_item("identityName").width(), summary.width(), delta=1)
        click("offlineLoginOption")
        field = self.visual_item("offlineNameField")
        save = self.visual_item("saveOfflineIdentityButton")
        for invalid in ["", "ab", "bad name", "name-with-dash", "a" * 17]:
            field.setProperty("text", invalid)
            self.assertFalse(save.property("enabled"))
        field.setProperty("text", "Player_123")
        self.assertTrue(save.property("enabled"))
        click("saveOfflineIdentityButton")
        self.assertEqual(deck.property("route"), "")
        self.assertEqual(self.visual_item("homeAccountButton").property("text"), "Player_123")
        click("homeAccountButton")
        self.assertEqual(self.visual_item("identityName").property("text"), "Player_123")
        self.assertTrue(self.visual_item("offlineLoginOption").property("selected"))
        click("offlineLoginOption")
        field = self.visual_item("offlineNameField")
        self.assertEqual(field.property("text"), "Player_123")
        field.setProperty("text", "Discarded")
        deck.goBack()
        QTest.qWait(200)
        self.assertEqual(self.identity.status["name"], "Player_123")
        deck.goBack()
        QTest.qWait(200)
        account = self.visual_item("homeAccountButton")
        self.assertEqual(account.property("text"), "Player_123")
        self.assertEqual(account.property("caption"), "离线身份")

        click("homeAccountButton")
        click("microsoftLoginOption")
        click("microsoftAuthButton")
        self.assertEqual(self.identity.status["authState"], "waiting")
        self.assertEqual(self.visual_item("microsoftDeviceCode").property("text"), "BUGG-DEMO")
        controller.selectTheme("panel")
        QTest.qWait(500)
        self.assertEqual(self.identity.status["authState"], "waiting")
        click("cancelMicrosoftAuthButton")
        self.assertEqual(deck.property("route"), "identity")
        self.assertEqual(self.identity.status["name"], "Player_123")
        click("microsoftLoginOption")
        click("microsoftAuthButton")
        click("microsoftAuthButton")
        self.assertEqual(self.identity.status["authState"], "authorizing")
        self.assertFalse(self.visual_item("microsoftAuthButton").property("enabled"))
        deck.goBack()
        self.identity.finish_microsoft()  # Late authorization cannot replace the old identity.
        QTest.qWait(200)
        self.assertEqual(self.identity.status["name"], "Player_123")

        click("microsoftLoginOption")
        click("microsoftAuthButton")
        click("microsoftAuthButton")
        self.identity.finish_microsoft()
        QTest.qWait(200)
        self.assertEqual(deck.property("route"), "")
        self.assertEqual(self.identity.status["name"], "BuggPlayer")
        controller.selectTheme("classic")
        QTest.qWait(500)
        account = self.visual_item("homeAccountButton")
        self.assertEqual(account.property("text"), "BuggPlayer")
        self.assertIn("模拟", account.property("caption"))
        click("homeAccountButton")
        self.assertTrue(self.visual_item("microsoftLoginOption").property("selected"))
        deck.goBack()
        self.window.navigate(4)
        QTest.qWait(400)
        deck.openPage("account")
        QTest.qWait(200)
        self.assertIn("BuggPlayer", self.visual_item("accountIdentityRow").property("caption"))
        click("accountIdentityRow")
        click("offlineLoginOption")
        self.visual_item("offlineNameField").setProperty("text", "SettingsPlayer")
        click("saveOfflineIdentityButton")
        self.assertEqual(deck.property("route"), "account")
        self.assertIn("SettingsPlayer", self.visual_item("accountIdentityRow").property("caption"))
        click("accountIdentityRow")
        self.assertIn("BuggPlayer", self.visual_item("microsoftLoginOption").property("caption"))
        click("microsoftLoginOption")
        self.assertEqual(deck.property("route"), "account")
        self.assertEqual(self.identity.status["kind"], "microsoft")
        self.assertEqual(self.identity.status["authState"], "idle")
        self.assertEqual(self.identity.status["code"], "")
        self.assertIsNone(self.visual_item("microsoftAuthButton"))
        self.assertIn("BuggPlayer", self.visual_item("accountIdentityRow").property("caption"))
        click("accountIdentityRow")
        click("offlineLoginOption")
        self.assertEqual(self.visual_item("offlineNameField").property("text"), "SettingsPlayer")
        click("saveOfflineIdentityButton")
        self.assertEqual(deck.property("route"), "account")
        self.launch.start(0)
        deck.offlineIdentityRequested.emit("Blocked")
        self.assertEqual(self.identity.status["name"], "SettingsPlayer")
        self.launch.cancel()

    def test_launch_stays_inline_and_restores_controls(self):
        controller = self.window.findChild(QObject, "windowController")
        controller.selectTheme("classic")
        QTest.qWait(600)
        deck = self.window.findChild(QObject, "toolContent")

        click = self.click_item

        def assert_inline(state):
            self.assertEqual(deck.property("route"), "")
            self.assertFalse(deck.property("canGoBack"))
            self.assertEqual(self.launch.status["state"], state)
            self.assertEqual(self.window.width(), 960 if controller.property("theme") == "classic" else 410)

        self.assertFalse(self.launch.obj.property("can_start"))
        self.assertEqual(self.visual_item("launchButton").property("text"), "选择账号")
        click("launchButton")
        self.assertEqual(deck.property("route"), "identity")
        self.assertEqual(self.launch.status["state"], "idle")
        deck.goBack()
        self.launch.start(0)  # The service also blocks an invocation bypassing the button.
        QTest.qWait(200)
        self.assertEqual(deck.property("route"), "identity")
        self.launch.advance()
        self.assertEqual(self.launch.status["state"], "idle")
        click("offlineLoginOption")
        self.visual_item("offlineNameField").setProperty("text", "LaunchPlayer")
        click("saveOfflineIdentityButton")
        self.assertEqual(deck.property("route"), "")
        self.assertFalse(deck.property("canGoBack"))
        self.assertTrue(self.launch.obj.property("can_start"))
        self.assertEqual(self.launch.status["state"], "idle")
        click("launchButton")
        assert_inline("preparing")
        self.assertEqual(self.visual_item("launchButton").property("text"), "取消启动")
        self.assertFalse(self.visual_item("instanceButton").property("visible"))
        self.assertFalse(self.visual_item("instanceButton").property("enabled"))
        self.assertFalse(self.visual_item("homeAccountButton").property("enabled"))
        # An accidental second request cannot change the captured instance.
        self.launch.start(1)
        deck.selected.emit(1)
        self.assertEqual(self.window.property("selectedInstance"), 0)
        self.assertEqual(self.launch.status["instanceName"], self.window.property("instances")[0]["name"])

        click("launchButton")
        assert_inline("idle")
        self.launch.advance()  # A late preparation event must not restart the game.
        self.assertEqual(self.launch.status["state"], "idle")
        self.assertTrue(self.visual_item("instanceButton").property("enabled"))
        self.assertTrue(self.visual_item("homeAccountButton").property("enabled"))

        click("launchButton")
        self.launch.advance()
        expected_progress = self.launch.status["progress"]
        self.window.navigate(3)
        QTest.qWait(400)
        controller.selectTheme("panel")
        QTest.qWait(550)
        self.window.navigate(0)
        QTest.qWait(450)
        assert_inline("preparing")
        self.assertEqual(self.visual_item("homeLaunchProgress").property("progress"), expected_progress)
        controller.selectTheme("classic")
        QTest.qWait(550)
        for _ in range(3):
            self.launch.advance()
        QTest.qWait(200)
        assert_inline("running")
        self.assertEqual(self.visual_item("launchButton").property("text"), "停止游戏")
        self.assertFalse(self.visual_item("homeLaunchProgress").property("showBar"))
        click("launchSecondaryButton")
        self.assertEqual(deck.property("route"), "logs")
        deck.goBack()
        QTest.qWait(200)
        assert_inline("running")
        click("launchButton")
        assert_inline("stopping")
        self.assertFalse(self.visual_item("launchButton").property("enabled"))
        self.launch.advance()
        QTest.qWait(200)
        assert_inline("idle")
        self.assertTrue(self.visual_item("instanceButton").property("enabled"))

        click("launchButton")
        self.launch.fail("Test: Java unavailable")
        QTest.qWait(200)
        assert_inline("failed")
        self.assertEqual(self.visual_item("homeLaunchProgress").property("caption"), "Test: Java unavailable")
        click("launchButton")
        assert_inline("preparing")
        self.launch.fail("Test: process creation failed")
        QTest.qWait(200)
        click("launchSecondaryButton")
        assert_inline("idle")
        self.assertTrue(self.visual_item("homeAccountButton").property("visible"))
        # A game exiting on its own follows the same restore path as stopping.
        click("launchButton")
        for _ in range(4):
            self.launch.advance()
        self.launch.finish()
        QTest.qWait(200)
        assert_inline("idle")
        self.assertEqual(self.visual_item("launchButton").property("text"), "启动游戏")

    def test_home_backdrop_gradient_survives_software_rendering(self):
        controller = self.window.findChild(QObject, "windowController")
        deck = self.window.findChild(QObject, "toolContent")
        controller.selectTheme("classic")
        self.window.navigate(0)
        QTest.qWait(600)
        captures = PROJECT / "build" / "ui-compact-review"
        captures.mkdir(exist_ok=True)
        # Compare empty padding at both ends: a QML Gradient object alone did not
        # catch the software backend skipping a transparent Rectangle entirely.
        def difference(x):
            changes = []
            for dy in range(-3, 4):
                for dx in range(-3, 4):
                    point = origin + QPoint(x + dx, int(summary.height() / 2) + dy)
                    first, second = shaded.pixelColor(point), bare.pixelColor(point)
                    changes.append(sum(abs(a - b) for a, b in zip(first.getRgb()[:3], second.getRgb()[:3])))
            return sum(changes) / len(changes)
        for index in range(1, 2):
            source = QUrl.fromLocalFile(str(PROJECT / f"qml/Bugg/DesignSystem/assets/home-siege-{index}.webp")).toString()
            deck.draftEdited.emit("appearance.backgrounds", [source])
            self.window.navigate(4)
            QTest.qWait(250)
            self.window.navigate(0)
            QTest.qWait(1000)
            summary = self.visual_item("instanceButton")
            self.assertTrue(summary.property("frosted"))
            self.assertAlmostEqual(summary.property("fadeOpacity"), .2)
            origin = summary.mapToScene(QPoint(0, 0)).toPoint()
            shaded = self.window.grabWindow()
            backend = os.environ.get("QT_QUICK_BACKEND") or "rhi"
            shaded.save(str(captures / f"home-gradient-{index}-{backend}.png"))
            summary.setProperty("frosted", False)
            QTest.qWait(50)
            bare = self.window.grabWindow()
            left, right = difference(10), difference(int(summary.width()) - 10)
            self.assertGreater(left, 1)
            self.assertLess(left, 50)
            self.assertLess(right, left * 0.2)
            (captures / f"home-gradient-{index}-{backend}.json").write_text(json.dumps({
                "graphicsApi": self.window.rendererInterface().graphicsApi().name,
                "fadeOpacity": summary.property("fadeOpacity"),
                "leftPixelDifference": left,
                "rightPixelDifference": right,
            }, indent=2), encoding="utf-8")
            summary.setProperty("frosted", True)

    def test_page_headers_game_settings_and_java_selection(self):
        controller = self.window.findChild(QObject, "windowController")
        deck = self.window.findChild(QObject, "toolContent")
        captures = PROJECT / "build" / "ui-room-polish"
        captures.mkdir(exist_ok=True)
        for theme in ["classic", "panel"]:
            controller.selectTheme(theme)
            if self.window.property("activeTool") != 0:
                self.window.navigate(0)
            QTest.qWait(500)
            for route in ["gameSettings", "java", "exportPack"]:
                deck.openPage(route)
                QTest.qWait(300)
                header = self.visual_item("contextHeader")
                self.assertTrue(header.isVisible())
                title = self.visual_item("subpageTitle")
                center = header.mapToScene(QPoint(0, int(header.height() / 2))).y()
                self.assertAlmostEqual(title.mapToScene(QPoint(0, int(title.height() / 2))).y(), center, delta=1)
                for name in ["subpageBackButton", "subpageHomeButton", "windowCollapseButton", "windowCloseButton"]:
                    button = self.visual_item(name)
                    if button and button.isVisible():
                        self.assertAlmostEqual(button.mapToScene(QPoint(0, int(button.height() / 2))).y(), center, delta=1)
                page = deck.findChild(QObject, "pageLoader").property("item")
                if route == "gameSettings":
                    page.setProperty("environment", {"maximumMemoryMB": 8192, "totalMB": 16384, "availableMB": 10240})
                    page.setProperty("configuration", {"fullscreen": True, "automatic": True})
                    QTest.qWait(100)
                    display = self.visual_item("displayModeSelector")
                    self.assertEqual(display.property("selection"), "fullscreen")
                    self.assertIsNone(self.visual_item("fullscreenOption"))
                    self.assertIsNone(self.visual_item("resolutionSelector"))
                    self.window.grabWindow().save(str(captures / f"game-fullscreen-{theme}.png"))
                    page.setProperty("configuration", {"fullscreen": False, "automatic": False, "memoryMB": 4096})
                    QTest.qWait(100)
                    edits = []
                    page.settingEdited.connect(lambda key, value: edits.append((key, value)))
                    display.chosen.emit("fullscreen")
                    self.assertIn(("fullscreen", True), edits)
                    edits.clear()
                    self.click_item("displayModeSelectorControl")
                    QTest.qWait(120)
                    self.window.grabWindow().save(str(captures / f"game-display-options-{theme}.png"))
                    self.click_item("displayModeSelectorOption_1600x900")
                    self.assertEqual(edits, [("resolution", "1600x900"), ("fullscreen", False)])
                if route == "java":
                    page.setProperty("javaEntries", [{"id": "C:/Java21/bin/java.exe", "name": "Java 21", "caption": "C:/Java21/bin/java.exe"},
                                                     {"id": "C:/Java25/bin/java.exe", "name": "Java 25", "caption": "C:/Java25/bin/java.exe"}])
                    page.setProperty("selection", "C:/Java25/bin/java.exe")
                    QTest.qWait(100)
                    automatic = self.visual_item("automaticJavaRow")
                    self.assertFalse(automatic.property("selected"))
                    self.assertEqual(automatic.property("iconName"), "")
                QTest.qWait(100)
                self.window.grabWindow().save(str(captures / f"{route}-{theme}.png"))
                deck.goHome()
                QTest.qWait(150)

    def test_room_cache_progress_states(self):
        node = NodeUiProbe()
        self.window.setProperty("multiplayerService", node)
        deck = self.window.findChild(QObject, "toolContent")
        deck.setProperty("previewEnabled", False)
        controller = self.window.findChild(QObject, "windowController")
        captures = PROJECT / "build" / "ui-room-cache"
        captures.mkdir(exist_ok=True)
        node.snapshot["room"] = {"id": "cache-room", "session": "native-session", "role": "host",
            "title": "朋友的世界", "availability": "waiting", "connectionMode": "local",
            "game": {"version": "1.21.1", "loader": "neoforge"}, "allowSharing": True,
            "isManager": True, "members": [{"id": "self", "name": "TestUser", "online": True}]}
        states = [
            ("planning", "等待源站", "连接加速缓存服务", True, -1),
            ("pending", "等待源站", "已缓存 0 / 12 · 公开源 8 · 待处理 4\n源站正在准备下载加速", True, -1),
            ("uploading", "上传中", "已缓存 2 / 12 · 公开源 8 · 待处理 2\nmods/example.jar · 2.4 MiB / 8.0 MiB", True, .3),
            ("ready", "已就绪", "已缓存 4 / 12 · 公开源 8 · 待处理 0\n已缓存：mods/imfast-NEOFORGE-1.21.1-1.0.3.jar、resourcepacks/example.zip 等 4 个文件", False, -1),
            ("redirect", "已就绪", "已缓存 0 / 12 · 公开源 12 · 待处理 0\n公开源可直接下载，无需上传", False, -1),
            ("empty", "无需缓存", "没有需要缓存的模组或资源文件", False, -1),
            ("unavailable", "未连接", "节点未配置加速缓存服务", False, -1),
        ]
        for theme in ["classic", "panel"]:
            controller.selectTheme(theme)
            node.changed.emit()
            self.window.navigate(2)
            QTest.qWait(500)
            deck.openPage("room")
            QTest.qWait(250)
            self.click_item("nav102")
            for state, label, detail, active, progress in states:
                node.snapshot["cacheProgress"] = dict(state=state, label=label, detail=detail,
                                                       active=active, progress=progress)
                node.changed.emit()
                QTest.qWait(180)
                row = self.visual_item("roomCacheProgress")
                self.assertIsNotNone(row, (theme, deck.property("route"), self.window.property("activeTool")))
                self.assertTrue(row.isVisible())
                self.assertEqual(row.property("caption"), detail)
                self.assertEqual(row.property("showBar"), active)
                footer = self.visual_item("roomLaunchButton")
                self.assertLessEqual(footer.mapToScene(QPoint(0, int(footer.height()))).y(),
                                     row.mapToScene(QPoint(0, 0)).y())
                self.assertLess(footer.mapToScene(QPoint(0, int(footer.height()))).y(), self.window.height())
                self.window.grabWindow().save(str(captures / f"cache-{state}-{theme}.png"))
            node.snapshot["room"]["allowSharing"] = False
            node.changed.emit()
            QTest.qWait(100)
            self.assertFalse(self.visual_item("roomCacheProgress").isVisible())
            node.snapshot["room"]["allowSharing"] = True
            deck.goHome()

    def test_room_home_chat_sync_and_expired_login_routes(self):
        node = NodeUiProbe()
        self.window.setProperty("multiplayerService", node)
        deck = self.window.findChild(QObject, "toolContent")
        deck.setProperty("previewEnabled", False)
        controller = self.window.findChild(QObject, "windowController")
        captures = PROJECT / "build" / "ui-room-review"
        captures.mkdir(exist_ok=True)
        for theme in ["classic", "panel"]:
            controller.selectTheme(theme)
            for role, mode in [("host", "local"), ("client", "p2p"), ("client", "relay")]:
                node.snapshot["room"] = {"id": "room", "session": "native-session", "role": role,
                    "title": "朋友的世界", "availability": "ready", "connectionMode": mode, "state": "online",
                    "memberCount": 3, "latencyMs": 38 if role == "client" else 0,
                    "address": "127.0.0.1:25565", "game": {"version": "1.21.1", "loader": "neoforge"},
                    "isManager": role == "host", "allowSharing": True,
                    "lobby": {"self_id": "self", "manager_id": "self" if role == "host" else "other"},
                    "members": [{"id": "self", "name": "TestUser", "online": True, "state": "ready"}]}
                node.snapshot["messages"] = [{"id": "1", "sender": "Alex", "text": "世界已经开放，可以进来了。"},
                                              {"id": "2", "sender": "TestUser", "text": "好的，马上进入。"}]
                node.changed.emit()
                deck.openToolPage(2, "room")
                QTest.qWait(450)
                if not self.visual_item("roomChatInput").isVisible():
                    self.click_item("nav100")
                self.assertIsNone(self.visual_item("roomAddressField"))
                self.assertFalse(self.visual_item("roomMembersViewport").isVisible())
                editor = self.visual_item("roomChatInput")
                send = self.visual_item("roomChatSendButton")
                self.assertGreaterEqual(self.window.height() - editor.mapToScene(QPoint(0, int(editor.height()))).y(), 20)
                self.assertAlmostEqual(editor.mapToScene(QPoint(0, int(editor.height() / 2))).y(), send.mapToScene(QPoint(0, int(send.height() / 2))).y(), delta=1)
                self.window.grabWindow().save(str(captures / f"room-chat-{mode}-{theme}.png"))
                if role == "host":
                    previous = node.snapshot["messages"]
                    node.snapshot["messages"] = []
                    node.changed.emit()
                    QTest.qWait(120)
                    self.window.grabWindow().save(str(captures / f"room-chat-empty-{theme}.png"))
                    node.snapshot["chatError"] = "消息发送失败，请重试。"
                    deck.draftEdited.emit("rooms.chat.room", "保留的输入")
                    node.changed.emit()
                    QTest.qWait(150)
                    self.assertEqual(self.visual_item("roomChatInput").property("text"), "保留的输入")
                    self.window.grabWindow().save(str(captures / f"room-chat-error-{theme}.png"))
                    node.snapshot.pop("chatError")
                    node.snapshot["messages"] = [{"id": str(i), "sender": "Alex", "text": "房间消息需要正确换行。" * 12} for i in range(30)]
                    deck.draftEdited.emit("rooms.chat.room", "")
                    node.changed.emit()
                    QTest.qWait(150)
                    viewport = self.visual_item("roomChatViewport")
                    footer = self.visual_item("roomChatInput")
                    footer_y = footer.mapToScene(QPoint(0, 0)).y()
                    viewport.setProperty("contentY", 180)
                    QTest.qWait(100)
                    self.assertEqual(footer.mapToScene(QPoint(0, 0)).y(), footer_y)
                    self.assertFalse(self.visual_item("roomMembersViewport").isVisible())
                    self.window.grabWindow().save(str(captures / f"room-chat-long-{theme}.png"))
                    node.snapshot["messages"] = previous
                    node.changed.emit()
                    QTest.qWait(100)
                self.click_item("subpageBackButton")
                self.assertEqual(self.window.property("activeTool"), 0)
                self.assertEqual(deck.property("route"), "")
                QTest.qWait(350)
                self.window.grabWindow().save(str(captures / f"home-room-{mode}-{theme}.png"))
                row = self.visual_item("homeRoomSummary")
                if theme == "classic":
                    self.assertTrue(row.isVisible())
                    self.assertIn("3 人", row.property("caption"))
                    self.assertIn({"local": "本地世界", "p2p": "直连", "relay": "中转"}[mode], row.property("caption"))
                    if role == "client": self.assertIn("38 ms", row.property("caption"))
                    self.click_item("homeRoomSummary")
                else:
                    self.assertFalse(row.isVisible())
                    self.assertLess(self.window.height(), 180)
                    self.window.navigate(2)
                    QTest.qWait(250)
                    self.click_item("currentRoomRow")
                self.assertEqual(deck.property("route"), "room")
                editor = self.visual_item("roomChatInput")
                self.hover_item(editor)
                QTest.mouseClick(self.window, Qt.LeftButton, Qt.NoModifier, editor.mapToScene(QPoint(25, 20)).toPoint())
                editor.setProperty("text", "Hello room")
                QMetaObject.invokeMethod(editor, "textEdited")
                QTest.qWait(100)
                self.click_item("roomChatSendButton")
                self.assertIn(("send_chat", "Hello room"), node.calls)
                node.chat_sent.emit()
                QTest.qWait(100)
                self.assertEqual(self.visual_item("roomChatInput").property("text"), "")
                if role == "client":
                    node.snapshot["room"]["syncName"] = "1.21.1-neoforge-room"
                    node.snapshot["room"]["candidateId"] = "vanilla"
                    node.snapshot["room"]["compatibility"] = "加载器不同 · 模组内容不同"
                    node.changed.emit()
                    self.click_item("roomLaunchButton")
                    self.assertIn(("launch_room",), node.calls)
                    node.preparation_required.emit()
                    QTest.qWait(250)
                    self.assertEqual(deck.property("route"), "room")
                    self.assertTrue(self.visual_item("roomLocalInstanceField").isVisible())
                    self.assertFalse(self.visual_item("roomChatInput").isVisible())
                    self.assertEqual(self.visual_item("roomLaunchButton").property("text"), "同步安装")
                    self.window.grabWindow().save(str(captures / f"room-sync-{theme}.png"))
                    self.click_item("syncRoomButton")
                    self.assertIn(("sync_room", "fresh"), node.calls)
                    for state in ["running", "failed"]:
                        node.snapshot["room"]["syncState"] = state
                        node.changed.emit()
                        deck.setProperty("tasks", [{"id": "room-task", "kind": "room",
                            "name": "1.21.1-neoforge-room", "state": state, "progress": 0.42,
                            "detail": "正在同步模组 · 8 / 19" if state == "running" else "连接已断开，可以重试。"}])
                        QTest.qWait(180)
                        self.assertFalse(self.visual_item("syncRoomButton").isVisible())
                        self.assertNotEqual(self.visual_item("roomLaunchButton").property("text"), "启动游戏")
                        self.window.grabWindow().save(str(captures / f"room-sync-{state}-{theme}.png"))
                    deck.setProperty("tasks", [])
                    node.snapshot["room"]["instanceId"] = "siege"
                    node.snapshot["room"]["candidateId"] = "siege"
                    node.snapshot["room"]["syncState"] = "ready"
                    node.snapshot["room"]["compatibility"] = ""
                    node.changed.emit()
                    QTest.qWait(150)
                    self.assertEqual(self.visual_item("roomLaunchButton").property("text"), "启动游戏")
                    self.assertFalse(self.visual_item("syncRoomButton").isVisible())
                    self.assertFalse(self.visual_item("supplementRoomButton").isVisible())
                    self.window.grabWindow().save(str(captures / f"room-sync-ready-{theme}.png"))
                    self.click_item("nav100")
            node.snapshot.pop("room")
            node.snapshot["state"] = "signedOut"
            node.snapshot["authorizationExpired"] = True
            node.snapshot["error"] = "节点授权已失效，请重新登录"
            node.changed.emit()
            self.window.navigate(3)
            node.changed.emit()
            QTest.qWait(350)
            self.assertEqual(self.window.property("activeTool"), 2)
            self.window.grabWindow().save(str(captures / f"node-expired-{theme}.png"))
            node.snapshot["state"] = "ready"
            node.snapshot.pop("error")
            node.changed.emit()

    def test_existing_world_selection_and_retry_in_all_sizes(self):
        node = NodeUiProbe()  # Explicit discovery snapshots and command recorder only.
        self.window.setProperty("multiplayerService", node)
        deck = self.window.findChild(QObject, "toolContent")
        controller = self.window.findChild(QObject, "windowController")
        captures = PROJECT / "build/ui-existing-world"
        captures.mkdir(exist_ok=True)
        for theme in ["panel", "small", "classic", "large"]:
            controller.selectTheme(theme)
            self.window.navigate(2)
            QTest.qWait(250)
            deck.openPage("createRoom")
            QTest.qWait(250)
            page = self.window.findChild(QObject, "pageLoader").property("item")
            page.edited.emit("existingWorld", False)
            page.edited.emit("port", "obsolete-port")
            QTest.qWait(100)
            self.click_item("roomExistingWorldOption")
            self.assertEqual(node.calls[-1][0], "discover")
            node.snapshot.update(worldsLoading=True, worlds=[])
            node.changed.emit()
            QTest.qWait(150)
            confirm = self.visual_item("confirmCreateRoomButton")
            field = self.visual_item("roomWorldField")
            self.assertFalse(confirm.isEnabled())
            self.assertTrue(field.property("busy"))
            self.window.grabWindow().save(str(captures / f"scanning-{theme}.png"))
            node.snapshot.update(worldsLoading=False, worlds=[
                {"port": 51724, "motd": "已经开放的生存世界", "version": "NeoForge 1.21.1"}])
            node.changed.emit()
            QTest.qWait(150)
            self.assertEqual(field.property("selection"), "51724")
            self.assertTrue(confirm.isEnabled())
            self.assertLessEqual(confirm.mapToScene(QPoint(0, int(confirm.height()))).y(), self.window.height() - 8)
            self.window.grabWindow().save(str(captures / f"selected-{theme}.png"))
            outer = self.window.findChild(QObject, "pageScrollView").property("contentItem")
            outer.setProperty("contentY", max(0, outer.property("contentHeight") - outer.height()))
            QTest.qWait(100)
            self.click_item("confirmCreateRoomButton")
            call = next(call for call in reversed(node.calls) if call[0] == "create")
            self.assertEqual(call[4]["port"], 51724)
            self.assertEqual(deck.property("route"), "createRoom")
            node.snapshot["error"] = "世界已关闭，请重新查找。"
            node.changed.emit()
            QTest.qWait(100)
            outer.setProperty("contentY", max(0, outer.property("contentHeight") - outer.height()))
            QTest.qWait(100)
            self.assertLessEqual(confirm.mapToScene(QPoint(0, int(confirm.height()))).y(), self.window.height() - 8)
            self.window.grabWindow().save(str(captures / f"retry-{theme}.png"))
            node.snapshot.pop("error")
            node.snapshot["worlds"].append({"port": 51725, "motd": "另一个世界", "version": "1.21.1"})
            node.changed.emit()
            QTest.qWait(100)
            self.assertEqual(field.property("selection"), "")
            self.assertFalse(confirm.isEnabled())
            outer.setProperty("contentY", 0)
            QTest.qWait(100)
            self.window.grabWindow().save(str(captures / f"multiple-{theme}.png"))
            field.chosen.emit("51725")
            QTest.qWait(100)
            self.assertTrue(confirm.isEnabled())
            node.snapshot["worlds"] = []
            node.changed.emit()
            QTest.qWait(100)
            self.assertEqual(field.property("selection"), "")
            self.assertFalse(confirm.isEnabled())
            self.window.grabWindow().save(str(captures / f"empty-{theme}.png"))
            node.snapshot["worlds"] = [{"port": 51725, "version": "1.21.1"}, {"port": 51726, "version": "1.21.1"}]
            node.changed.emit()
            QTest.qWait(100)
            self.assertEqual(field.property("selection"), "51725")
            deck.goBack()
            QTest.qWait(150)
            before = len([call for call in node.calls if call[0] == "discover"])
            deck.openPage("createRoom")
            QTest.qWait(150)
            self.assertEqual(len([call for call in node.calls if call[0] == "discover"]), before + 1)
            deck.goBack()
            node.snapshot["worlds"] = []
            node.changed.emit()
            QTest.qWait(100)
        self.window.setProperty("multiplayerService", None)

    def test_room_creation_and_friends_reuse_shared_routes_and_lists(self):
        node = NodeUiProbe()
        self.window.setProperty("multiplayerService", node)
        deck = self.window.findChild(QObject, "toolContent")
        controller = self.window.findChild(QObject, "windowController")
        captures = PROJECT / "build" / "ui-room-review"
        captures.mkdir(exist_ok=True)
        for theme in ["classic", "panel"]:
            controller.selectTheme(theme)
            if self.window.property("activeTool") != 2:
                self.window.navigate(2)
            QTest.qWait(550)
            search = self.visual_item("roomSearchField")
            if theme == "panel":
                self.assertTrue(search.isVisible())
                self.assertLess(self.window.height(), 340)
                create = self.visual_item("createRoomButton")
                self.assertLessEqual(create.mapToScene(QPoint(int(create.width()), 0)).x(), self.window.width() - 20)
            self.window.grabWindow().save(str(captures / f"rooms-empty-{theme}.png"))
            self.assertFalse(deck.property("showPageHeader"))
            self.assertIsNone(self.visual_item("roomInviteField"))
            self.click_item("openJoinRoomButton")
            QTest.qWait(250)
            self.window.grabWindow().save(str(captures / f"join-room-{theme}.png"))
            node.snapshot["roomBusy"] = True
            node.snapshot["roomOperation"] = "join"
            node.changed.emit()
            QTest.qWait(150)
            self.assertTrue(self.visual_item("roomJoinProgress").isVisible())
            self.assertTrue(self.visual_item("joiningRoomPage").isVisible())
            self.assertFalse(self.visual_item("roomInviteField").isVisible())
            self.window.grabWindow().save(str(captures / f"join-room-waiting-{theme}.png"))
            node.snapshot["roomBusy"] = False
            node.snapshot["error"] = "邀请已过期，请房主重新分享。"
            node.changed.emit()
            QTest.qWait(100)
            self.window.grabWindow().save(str(captures / f"join-room-error-{theme}.png"))
            node.snapshot.pop("error")
            node.changed.emit()
            deck.goBack()
            QTest.qWait(250)
            self.click_item("createRoomButton")
            self.assertEqual(deck.property("route"), "createRoom")
            self.assertTrue(self.visual_item("roomInstanceField").isVisible())
            self.window.grabWindow().save(str(captures / f"create-room-{theme}.png"))
            self.click_item("confirmCreateRoomButton")
            self.assertTrue(node.calls[-1][-1]["public"])
            self.assertTrue(node.calls[-1][-1]["requireInvite"])
            self.assertEqual(deck.property("route"), "createRoom")  # Command alone is not success.
            call = next(call for call in reversed(node.calls) if call[0] == "create")
            self.assertEqual(call[4]["instanceId"], "siege")
            self.assertTrue(call[4]["public"])
            self.assertTrue(call[4]["requireInvite"])
            self.assertEqual(call[4]["port"], 0)
            node.snapshot["room"] = {"id": "room", "role": "host", "instanceId": "siege",
                                      "title": "朋友的世界", "availability": "waiting", "invite": "test-only",
                                      "game": {"version": "1.21.1", "loader": "neoforge"},
                                      "isManager": True, "isProvider": True,
                                      "lobby": {"self_id": "self", "manager_id": "self", "provider_id": "self"},
                                      "members": [{"id": "self", "name": "TestUser", "state": "ready", "online": True}]}
            node.changed.emit()
            node.room_joined.emit()
            QTest.qWait(250)
            self.assertEqual(deck.property("route"), "room")
            self.assertEqual(self.visual_item("roomMembersViewport").property("count"), 1)
            self.click_item("nav101")
            self.assertFalse(self.visual_item("roomChatInput").isVisible())
            self.window.grabWindow().save(str(captures / f"room-{theme}.png"))
            connection = self.visual_item("subpageTitle")
            self.assertIn("对局域网开放", connection.property("caption"))
            waiting_color = connection.property("captionColor")
            node.snapshot["room"]["title"] = "朋友们的百日围城联机房间 · 断墙之夜 · 一起建造新的世界"
            node.changed.emit()
            QTest.qWait(100)
            self.window.grabWindow().save(str(captures / f"room-long-title-{theme}.png"))
            self.assertLess(connection.mapToScene(QPoint(int(connection.width()), 0)).x(), self.visual_item("subpageActionButton").mapToScene(QPoint(0, 0)).x())
            node.snapshot["room"]["title"] = "朋友的世界"
            node.snapshot["room"]["availability"] = "ready"
            node.changed.emit()
            QTest.qWait(100)
            self.assertIn("本地世界已连接", connection.property("caption"))
            self.assertNotEqual(connection.property("captionColor"), waiting_color)
            self.window.grabWindow().save(str(captures / f"room-connected-{theme}.png"))
            node.snapshot["room"]["availability"] = "waiting"
            node.changed.emit()
            node.snapshot["room"]["members"] += [{"id": f"member-{index}", "name": f"Player{index}", "state": "ready", "online": True} for index in range(1, 9)]
            node.changed.emit()
            QTest.qWait(150)
            self.window.grabWindow().save(str(captures / f"room-members-{theme}.png"))
            self.click_item("roomMemberActions_member-1")
            self.window.grabWindow().save(str(captures / f"room-member-actions-{theme}.png"))
            self.click_item("profileChoice_owner_offer")
            self.assertIn(("room_command", "owner_offer", {"member": "member-1"}), node.calls)
            viewport = self.visual_item("roomMembersViewport")
            self.assertEqual(viewport.property("count"), 9)
            button_before = self.visual_item("roomLaunchButton").mapToScene(QPoint(0, 0)).y()
            viewport.setProperty("contentY", 110)
            QTest.qWait(100)
            self.assertEqual(self.visual_item("roomLaunchButton").mapToScene(QPoint(0, 0)).y(), button_before)
            node.snapshot["room"]["members"] = node.snapshot["room"]["members"][:1]
            node.changed.emit()
            launch_button = self.visual_item("roomLaunchButton")
            self.assertLess(launch_button.mapToScene(QPoint(0, int(launch_button.height()))).y(), self.window.height() - 10)
            self.click_item("subpageActionButton")
            QTest.qWait(250)
            self.window.grabWindow().save(str(captures / f"room-settings-{theme}.png"))
            self.click_item("saveRoomSettingsButton")
            self.assertTrue(any(call[:2] == ("room_command", "configure") for call in node.calls))
            node.room_command_completed.emit("configure")
            QTest.qWait(250)
            self.assertEqual(deck.property("route"), "room")
            if not self.identity.status.get("ready"):
                self.click_item("roomLaunchButton")
                node.launch_requested.emit("siege", {})
                self.assertEqual(deck.property("route"), "identity")
                self.identity.use_offline("NativeHost")
                QTest.qWait(180)
                self.assertEqual(deck.property("route"), "room")
            self.click_item("roomLaunchButton")
            node.launch_requested.emit("siege", {})
            self.assertEqual(self.launch.status["state"], "preparing")
            QTest.qWait(180)
            self.window.grabWindow().save(str(captures / f"room-starting-{theme}.png"))
            self.click_item("roomLaunchButton")
            self.assertEqual(self.launch.status["state"], "idle")
            self.click_item("closeWindowButton")
            self.assertIn(("leave",), node.calls)
            node.snapshot.pop("room")
            node.changed.emit()
            node.room_left.emit()
            QTest.qWait(200)
            self.assertEqual(deck.property("route"), "")
            self.window.navigate(3)
            node.snapshot["friends"] = [{"account": "a", "username": "Alex", "online": True},
                                         {"account": "b", "username": "Steve", "online": False}]
            node.snapshot["requests"] = [{"account": "c", "username": "Sam", "incoming": True, "id": "request"}]
            node.snapshot["invitations"] = [{"account": "a", "username": "Alex", "room": "other-room", "id": "invitation"}]
            node.snapshot["joinRequests"] = [{"account": "c", "username": "Sam", "room": "hosted-room", "id": "join-request", "incoming": True, "status": "pending"}]
            node.snapshot["notifications"] = [dict(node.snapshot[key][0], notificationKind=kind, receivedAt=100 + index)
                                                for index, (key, kind) in enumerate([("requests", "requests"), ("invitations", "invitations"), ("joinRequests", "joins")])]
            node.snapshot["notifications"].reverse()
            node.snapshot["notificationCount"] = 3
            node.snapshot["notificationAt"] = 103
            node.snapshot.update(roomNotificationCount=2, roomNotificationAt=103,
                                 friendRequestCount=1, friendRequestAt=100)
            deck.draftEdited.emit("friends.selected", "a")
            node.changed.emit()
            QTest.qWait(250)
            self.window.grabWindow().save(str(captures / f"friends-{theme}.png"))
            self.assertEqual(self.visual_item("friendsViewport").property("count"), 4)
            if theme == "panel":
                self.assertLess(self.window.height(), 420)
                self.assertTrue(self.visual_item("friendSearchField").isVisible())
            if theme == "classic":
                self.assertTrue(self.visual_item("friendSearchField").isVisible())
                self.assertTrue(self.visual_item("friendDetails").isVisible())
                listing = self.visual_item("friendsViewport")
                details = self.visual_item("friendDetails")
                self.assertLessEqual(listing.mapToScene(QPoint(0, 0)).x(), 40)
                self.assertLessEqual(details.mapToScene(QPoint(0, 0)).x() - listing.mapToScene(QPoint(int(listing.width()), 0)).x(), 26)
                self.assertEqual(self.visual_item("friendDetailName").property("text"), "Alex")
                primary = self.visual_item("friendPrimary_a")
                profile = self.visual_item("friendDetailName")
                self.assertGreater(primary.mapToScene(QPoint(0, 0)).x(), profile.mapToScene(QPoint(0, 0)).x())
                self.assertTrue(self.visual_item("friendConversation").isVisible())
                self.assertFalse(self.visual_item("roomChatInput").property("enabled"))
                self.click_item("friendRow_b")
                self.assertEqual(self.visual_item("friendDetailName").property("text"), "Steve")
                self.click_item("friendRow_a")
            else:
                self.assertFalse(self.visual_item("friendDetails").isVisible())
                self.click_item("friendRow_a")
                self.assertEqual(deck.property("route"), "friendConversation")
                self.assertTrue(self.visual_item("friendConversation").isVisible())
                self.window.grabWindow().save(str(captures / "friend-conversation-panel.png"))
                deck.goBack()
                QTest.qWait(150)
            friends = node.snapshot["friends"]
            friends[0]["room"] = {"id": "friend-room", "title": "朋友的世界", "availability": "ready",
                                  "can_request": True, "game": {"version": "1.21.1", "loader": "NeoForge"}}
            node.changed.emit()
            QTest.qWait(100)
            self.window.grabWindow().save(str(captures / f"friends-room-{theme}.png"))
            self.assertEqual(self.visual_item("friendPrimary_a").property("text"), "申请加入")
            friends[0].pop("room")
            node.snapshot["friends"] = []
            node.changed.emit()
            QTest.qWait(100)
            self.assertEqual(self.visual_item("friendsViewport").property("count"), 2)
            self.window.grabWindow().save(str(captures / f"friends-empty-{theme}.png"))
            node.snapshot["friends"] = friends
            node.snapshot["error"] = "好友列表刷新失败，请重试。"
            node.changed.emit()
            QTest.qWait(350)
            notice = self.visual_item("friendStatusNotice")
            self.assertLessEqual(notice.mapToScene(QPoint(0, int(notice.height()))).y(), self.window.height() - 16)
            self.window.grabWindow().save(str(captures / f"friends-error-{theme}.png"))
            node.snapshot.pop("error")
            node.changed.emit()
            self.click_item("friendMore_a")
            self.window.grabWindow().save(str(captures / f"friend-actions-{theme}.png"))
            self.click_item("profileChoice_copy")
            self.assertIn(("copy_friend_code", "a"), node.calls)
            deck.openToolPage(2, "inviteFriends")
            QTest.qWait(300)
            self.window.grabWindow().save(str(captures / f"invite-friends-{theme}.png"))
            deck.goBack()
            if self.window.property("activeTool") != 3:
                self.window.navigate(3)
            QTest.qWait(300)
            self.assertIsNone(self.visual_item("friendRequestsTabButton"))
            service_row = self.visual_item("friendRow_bugg-notifications")
            first_friend = self.visual_item("friendRow_a")
            self.assertLess(service_row.mapToScene(QPoint(0, 0)).y(), first_friend.mapToScene(QPoint(0, 0)).y())
            friends[1]["receivedAt"] = 104
            node.snapshot["friends"] = friends
            node.changed.emit()
            QTest.qWait(100)
            self.assertLess(self.visual_item("friendRow_b").mapToScene(QPoint(0, 0)).y(), self.visual_item("friendRow_bugg-notifications").mapToScene(QPoint(0, 0)).y())
            node.snapshot["notificationAt"] = 105
            node.snapshot["roomNotificationAt"] = 105
            node.changed.emit()
            QTest.qWait(100)
            self.assertLess(self.visual_item("friendRow_bugg-notifications").mapToScene(QPoint(0, 0)).y(), self.visual_item("friendRow_b").mapToScene(QPoint(0, 0)).y())
            self.click_item("friendRow_bugg-notifications")
            self.assertIn(("read_notifications", "rooms"), node.calls)
            node.snapshot["notificationCount"] = 0
            node.changed.emit()
            self.assertEqual(node.snapshot["notificationCount"], 0)
            self.assertEqual(deck.property("route"), "notifications" if theme == "panel" else "")
            notifications = self.visual_item("friendsViewport" if theme == "panel" else "friendNotificationViewport")
            self.assertEqual(notifications.property("count"), 2)
            self.window.grabWindow().save(str(captures / f"friend-notifications-{theme}.png"))
            self.click_item("friendPrimary_invitations_a")
            self.assertIn(("join", "a", {"ref": "invitation"}), node.calls)
            self.click_item("friendPrimary_joins_c")
            self.assertIn(("accept_join", "c", {"ref": "join-request", "room": "hosted-room"}), node.calls)
            if theme == "panel":
                deck.goBack()
                QTest.qWait(120)
            self.click_item("friendRow_bugg-friend-requests")
            self.assertIn(("read_notifications", "requests"), node.calls)
            notifications = self.visual_item("friendsViewport" if theme == "panel" else "friendNotificationViewport")
            self.assertEqual(notifications.property("count"), 1)
            self.window.grabWindow().save(str(captures / f"friend-requests-{theme}.png"))
            self.click_item("friendPrimary_requests_c")
            self.assertIn(("accept", "c", {"ref": "request"}), node.calls)
            for key in ["requests", "invitations", "joinRequests"]:
                node.snapshot[key] = []
            node.snapshot["notifications"] = []
            node.changed.emit()
            QTest.qWait(100)
            self.window.grabWindow().save(str(captures / f"friend-notifications-empty-{theme}.png"))
            self.assertEqual(notifications.property("count"), 0)
            if theme == "panel":
                deck.goBack()
            else:
                self.click_item("friendRow_a")
            QTest.qWait(200)
            self.click_item("addFriendButton")
            QTest.qWait(250)
            self.window.grabWindow().save(str(captures / f"add-friend-{theme}.png"))
            node.snapshot["error"] = "未找到账号，请核对好友码或用户名。"
            node.changed.emit()
            QTest.qWait(100)
            self.window.grabWindow().save(str(captures / f"add-friend-error-{theme}.png"))
            node.snapshot.pop("error")
            node.changed.emit()
            deck.goBack()
            QTest.qWait(200)
            self.click_item("friendPrimary_a")
            self.assertIn(("invite_friend", "a"), node.calls)
            node.host_required.emit()
            QTest.qWait(250)
            self.assertEqual(deck.property("route"), "createRoom")
            deck.goBack()
        self.window.setProperty("multiplayerService", None)

    def test_public_invite_rooms_and_joining_page_in_all_sizes(self):
        node = NodeUiProbe()
        self.window.setProperty("multiplayerService", node)
        controller = self.window.findChild(QObject, "windowController")
        deck = self.window.findChild(QObject, "toolContent")
        captures = PROJECT / "build/ui-room-review"
        captures.mkdir(exist_ok=True)
        for theme in ["panel", "small", "classic", "large"]:
            controller.selectTheme(theme)
            self.window.navigate(2)
            node.snapshot["rooms"] = [
                {"id": "protected", "title": "朋友的世界", "require_invite": True,
                 "availability": "ready", "game": {"version": "1.21.1", "loader": "NeoForge"}},
                {"id": "open", "title": "一起冒险", "require_invite": False,
                 "availability": "ready", "game": {"version": "1.21.1", "loader": "Fabric"}}]
            node.changed.emit()
            QTest.qWait(400)
            protected = self.visual_item("roomListing_protected")
            self.assertEqual(protected.property("value"), "需要邀请")
            self.assertIn("需要邀请", protected.property("caption"))
            self.window.grabWindow().save(str(captures / f"public-invite-rooms-{theme}.png"))
            self.click_item("roomListing_protected")
            self.assertEqual(deck.property("route"), "joinRoom")
            self.assertFalse(any(call[0] == "listing" and call[1] == "protected" for call in node.calls))
            deck.goBack()
            QTest.qWait(100)
            # Public-list and notification joins share the service state; the
            # waiting page is independent of the route that initiated joining.
            node.snapshot.update(roomBusy=True, roomOperation="join")
            node.changed.emit()
            QTest.qWait(200)
            self.assertTrue(self.visual_item("joiningRoomPage").isVisible())
            self.assertTrue(deck.property("canGoBack"))
            self.assertFalse(self.visual_item("roomSearchField").isVisible())
            self.window.grabWindow().save(str(captures / f"joining-full-page-{theme}.png"))
            self.click_item("cancelRoomJoinButton")
            self.assertEqual(node.calls[-1], ("leave",))
            node.snapshot["roomBusy"] = False
            node.changed.emit()
            QTest.qWait(100)
            self.assertTrue(self.visual_item("roomSearchField").isVisible())

    def test_room_directory_unknown_policy_is_not_free_join(self):
        node = NodeUiProbe()
        self.window.setProperty("multiplayerService", node)
        controller = self.window.findChild(QObject, "windowController")
        captures = PROJECT / "build/ui-room-directory-review"
        captures.mkdir(exist_ok=True)
        for theme in ["panel", "small", "classic", "large"]:
            controller.selectTheme(theme)
            self.window.navigate(2)
            node.snapshot.update(rooms=[
                {"id": "unknown", "title": "旧房间", "availability": "unknown"},
                {"id": "open", "title": "一起冒险", "public": True, "require_invite": False,
                 "availability": "waiting", "game": {"version": "1.21.1", "loader": "Fabric"}},
                {"id": "protected", "title": "朋友的世界", "public": True, "require_invite": True,
                 "availability": "ready", "game": {"version": "1.21.1", "loader": "NeoForge"}}])
            node.snapshot.pop("error", None)
            node.changed.emit()
            QTest.qWait(400)
            unknown = self.visual_item("roomListing_unknown")
            self.assertFalse(unknown.isEnabled())
            self.assertNotIn("自由加入", unknown.property("caption"))
            self.assertEqual(unknown.property("value"), "状态未知")
            self.assertEqual(self.visual_item("roomListing_open").property("value"), "准备中")
            self.window.grabWindow().save(str(captures / f"policy-{theme}.png"))
            node.snapshot.update(rooms=[], error="房间已失效或尚未发布，已从大厅移除。请让房主重新创建或发送邀请。")
            node.changed.emit()
            QTest.qWait(200)
            self.window.grabWindow().save(str(captures / f"expired-{theme}.png"))
            node.snapshot.pop("error", None)
            node.snapshot["loading"] = True
            node.changed.emit()
            QTest.qWait(100)
            self.window.grabWindow().save(str(captures / f"loading-{theme}.png"))
            node.snapshot["loading"] = False

    def test_social_footers_use_available_space_in_all_sizes(self):
        node = NodeUiProbe()
        node.snapshot.update(nodeName="Buggcraft 上海节点", latency=23)
        self.window.setProperty("multiplayerService", node)
        controller = self.window.findChild(QObject, "windowController")
        deck = self.window.findChild(QObject, "toolContent")
        captures = PROJECT / "build/ui-footer-review"
        captures.mkdir(exist_ok=True)
        geometry = []
        for theme in ["panel", "small", "classic", "large"]:
            with self.subTest(theme=theme):
                node.snapshot["friends"] = [{"account": "a", "username": "Alex", "online": True},
                                            {"account": "b", "username": "Steve", "online": False}]
                node.snapshot["rooms"] = []
                node.snapshot.pop("error", None)
                controller.selectTheme(theme)
                self.window.navigate(3)
                node.changed.emit()
                QTest.qWait(650)
                code = self.visual_item("ownFriendCodeButton")
                listing = self.visual_item("friendsViewport")
                sidebar = self.visual_item("friendSidebar")
                code_bottom = code.mapToScene(QPoint(0, int(code.height()))).y()
                self.window.grabWindow().save(str(captures / f"friends-{theme}.png"))
                self.assertGreater(code_bottom, 100)
                self.assertLessEqual(code_bottom, self.window.height() - 10)
                self.assertEqual(listing.width(), code.width())
                self.assertLessEqual(abs(listing.mapToScene(QPoint(0, 0)).x() - code.mapToScene(QPoint(0, 0)).x()), 1)
                if theme != "panel":
                    details = self.visual_item("friendDetails")
                    self.assertLessEqual(self.window.height() - code_bottom, 32)
                    self.assertLessEqual(abs(code_bottom - details.mapToScene(QPoint(0, int(details.height()))).y()), 1)
                row = self.visual_item("friendRow_a")
                content = row.property("contentItem")
                text_column = next(item for item in content.childItems()
                                   if any(child.property("text") == "Alex" for child in item.childItems()))
                row_middle = row.mapToScene(QPoint(0, int(row.height() / 2))).y()
                text_middle = text_column.mapToScene(QPoint(0, int(text_column.height() / 2))).y()
                self.assertLessEqual(abs(row_middle - text_middle), 1)
                geometry.append({"theme": theme, "windowHeight": self.window.height(),
                                 "friendCodeBottom": code_bottom, "sidebarHeight": sidebar.height(),
                                 "friendRowCenter": row_middle, "friendTextCenter": text_middle})
                node.snapshot["friends"] = [{"account": f"p{index}", "username": f"Player{index}", "online": False}
                                            for index in range(20)]
                node.changed.emit()
                QTest.qWait(150)
                footer_before_scroll = code.mapToScene(QPoint(0, 0)).y()
                listing.setProperty("contentY", 120)
                QTest.qWait(100)
                self.assertEqual(code.mapToScene(QPoint(0, 0)).y(), footer_before_scroll)
                self.window.grabWindow().save(str(captures / f"friends-scrolled-{theme}.png"))
                node.snapshot["friends"] = []
                node.changed.emit()
                QTest.qWait(150)
                self.window.grabWindow().save(str(captures / f"friends-empty-{theme}.png"))
                if theme != "panel":
                    self.assertEqual(code.mapToScene(QPoint(0, 0)).y(), footer_before_scroll)
                self.window.navigate(2)
                QTest.qWait(350)
                footer = self.visual_item("nodeStatusFooter")
                footer_bottom = footer.mapToScene(QPoint(0, int(footer.height()))).y()
                self.window.grabWindow().save(str(captures / f"rooms-empty-{theme}.png"))
                self.assertLessEqual(footer_bottom, self.window.height() - 10)
                self.assertLessEqual(self.window.height() - footer_bottom, 42)
                if theme == "panel":
                    self.assertLess(self.window.height(), 340)
                node.snapshot["rooms"] = [{"id": str(index), "title": f"朋友的世界 {index}",
                                           "availability": "ready", "game": {"version": "1.21.1", "loader": "NeoForge"}}
                                          for index in range(10)]
                node.changed.emit()
                QTest.qWait(200)
                viewport = self.visual_item("roomsViewport")
                footer_before_scroll = footer.mapToScene(QPoint(0, 0)).y()
                viewport.setProperty("contentY", 90)
                QTest.qWait(100)
                self.assertEqual(footer.mapToScene(QPoint(0, 0)).y(), footer_before_scroll)
                self.window.grabWindow().save(str(captures / f"rooms-full-{theme}.png"))
                node.snapshot["error"] = "网络暂时不可用，稍后自动重试。"
                node.changed.emit()
                QTest.qWait(200)
                self.window.grabWindow().save(str(captures / f"rooms-error-{theme}.png"))
                self.assertLessEqual(footer.mapToScene(QPoint(0, int(footer.height()))).y(), self.window.height() - 10)
                node.snapshot.pop("error", None)
                node.snapshot["loading"] = True
                node.snapshot["rooms"] = []
                node.changed.emit()
                QTest.qWait(200)
                self.window.grabWindow().save(str(captures / f"rooms-loading-{theme}.png"))
                self.assertLessEqual(footer.mapToScene(QPoint(0, int(footer.height()))).y(), self.window.height() - 10)
                node.snapshot.pop("loading", None)
        (captures / "geometry.json").write_text(json.dumps(geometry, ensure_ascii=False, indent=2), encoding="utf-8")
        self.window.setProperty("multiplayerService", None)

    def test_compact_rooms_pagination_and_surface_drag(self):
        node = NodeUiProbe()
        self.window.setProperty("multiplayerService", node)
        controller = self.window.findChild(QObject, "windowController")
        deck = self.window.findChild(QObject, "toolContent")
        captures = PROJECT / "build" / "ui-compact-review"
        captures.mkdir(exist_ok=True)
        self.window.navigate(2)
        node.snapshot["rooms"] = [{"id": str(index), "title": "朋友的世界 " + str(index), "availability": "ready",
                                    "game": {"version": "1.21.1", "loader": "NeoForge"}} for index in range(10)]
        node.changed.emit()
        QTest.qWait(450)
        viewport = self.visual_item("roomsViewport")
        self.assertTrue(self.visual_item("roomSearchField").isVisible())
        self.assertEqual(viewport.property("count"), 3)
        height = self.window.height()
        self.assertLess(height, 420)
        self.window.grabWindow().save(str(captures / "rooms-first-panel.png"))
        for page in range(1, 4):
            self.click_item("nextPageButton")
            self.assertEqual(self.visual_item("roomPagination").property("currentPage"), page)
            self.assertEqual(self.window.height(), height)
        self.assertEqual(viewport.property("count"), 1)
        self.assertFalse(self.visual_item("nextPageButton").property("enabled"))
        self.window.grabWindow().save(str(captures / "rooms-last-panel.png"))
        self.click_item("roomListing_9")
        self.assertIn(("listing", "9"), node.calls)
        node.snapshot["rooms"] = node.snapshot["rooms"][:1]
        node.changed.emit()
        QTest.qWait(150)
        self.assertEqual(self.visual_item("roomPagination").property("currentPage"), 0)
        self.assertFalse(self.visual_item("roomPagination").isVisible())
        self.assertEqual(viewport.property("count"), 1)
        self.window.grabWindow().save(str(captures / "rooms-shrunk-panel.png"))
        controller.selectTheme("classic")
        QTest.qWait(550)
        self.assertTrue(self.visual_item("roomSearchField").isVisible())
        self.assertEqual(viewport.property("count"), 1)
        self.window.grabWindow().save(str(captures / "rooms-classic.png"))
        self.window.navigate(3)
        QTest.qWait(300)
        self.window.setPosition(160, 100)
        # 空白正文也交给已有 EdgeDock，输入控件仍独占其鼠标事件。
        point = QPoint(700, 410)
        QTest.mousePress(self.window, Qt.LeftButton, Qt.NoModifier, point)
        QTest.mouseMove(self.window, point + QPoint(40, 30))
        self.assertTrue(self.dock.property("dragging"))
        QTest.mouseRelease(self.window, Qt.LeftButton, Qt.NoModifier, point + QPoint(40, 30))
        self.dock.finishMove()
        editor = self.visual_item("friendSearchField")
        point = editor.mapToScene(QPoint(25, 20)).toPoint()
        editor.setProperty("text", "Selecting text")
        QTest.mousePress(self.window, Qt.LeftButton, Qt.NoModifier, point)
        QTest.mouseMove(self.window, point + QPoint(50, 0))
        self.assertFalse(self.dock.property("dragging"))
        QTest.mouseRelease(self.window, Qt.LeftButton, Qt.NoModifier, point)
        self.click_item("downloadTasksButton")
        self.assertEqual(deck.property("pageTitle"), "任务")
        deck.goBack()
        deck.openPage("gameSettings")
        QTest.qWait(250)
        page = self.visual_item("gameSettingsPage")
        page.setProperty("configuration", {"automatic": False, "memoryMB": 1024})
        page.setProperty("environment", {"maximumMemoryMB": 8192})
        QTest.qWait(100)
        slider = self.visual_item("memorySlider")
        point = slider.mapToScene(QPoint(int(slider.width() * 0.2), int(slider.height() / 2))).toPoint()
        QTest.mousePress(self.window, Qt.LeftButton, Qt.NoModifier, point)
        QTest.mouseMove(self.window, point + QPoint(80, 0))
        self.assertFalse(self.dock.property("dragging"))
        QTest.mouseRelease(self.window, Qt.LeftButton, Qt.NoModifier, point + QPoint(80, 0))
        self.window.setProperty("multiplayerService", None)

    def test_all_subpages_load_and_return_in_both_layouts(self):
        self.window.navigate(0)
        QTest.qWait(400)
        deck = self.window.findChild(QObject, "toolContent")
        controller = self.window.findChild(QObject, "windowController")
        routes = list(deck.property("routes").toVariant())
        self.assertGreaterEqual(len(routes), 23)
        self.assertFalse(deck.openPage("unknown"))
        for theme in ["panel", "classic"]:
            controller.selectTheme(theme)
            QTest.qWait(500)
            for route in routes:
                with self.subTest(theme=theme, route=route):
                    self.assertTrue(deck.openPage(route))
                    QTest.qWait(35)
                    loader = deck.findChild(QObject, "pageLoader")
                    self.assertIsNotNone(loader.property("item"))
                    self.assertGreater(deck.property("implicitHeight"), 40)
                    self.assertTrue(deck.property("canGoBack"))
                    self.assertFalse(self.window.findChild(QObject, "floatingToolBar").property("enabled"))
                    self.assertTrue(self.window.findChild(QObject, "contextHeader").property("enabled"))
                    self.assertEqual(self.window.width(), 410 if theme == "panel" else 960)
                    deck.goBack()
                    QTest.qWait(20)
                    self.assertFalse(deck.property("canGoBack"))
                    self.assertEqual(deck.property("route"), "")

    def test_instance_navigation_conflict_and_source_reorder(self):
        self.window.navigate(0)
        QTest.qWait(500)
        summary = self.window.findChild(QObject, "instanceButton")
        point = summary.mapToScene(QPoint(int(summary.width() / 2), int(summary.height() / 2)))
        QTest.mouseClick(self.window, Qt.LeftButton, Qt.NoModifier, point.toPoint())
        QTest.qWait(250)
        button = self.window.findChild(QObject, "manageInstancesButton")
        point = button.mapToScene(QPoint(int(button.width() / 2), int(button.height() / 2)))
        QTest.mouseClick(self.window, Qt.LeftButton, Qt.NoModifier, point.toPoint())
        QTest.qWait(400)
        deck = self.window.findChild(QObject, "toolContent")
        self.assertEqual(deck.property("route"), "instance")
        deck.goBack()
        QTest.qWait(200)
        deck.openPage("instances")
        QTest.qWait(200)
        option = self.visual_item("manageInstance1")
        point = option.mapToScene(QPoint(int(option.width() / 2), int(option.height() / 2)))
        QTest.mouseClick(self.window, Qt.LeftButton, Qt.NoModifier, point.toPoint())
        QTest.qWait(400)
        self.assertEqual(deck.property("route"), "instance")
        self.assertEqual(self.window.property("selectedInstance"), 1)
        deck.beginInstall(self.window.property("instances")[1]["name"])
        QTest.qWait(200)
        self.assertEqual(deck.property("route"), "conflict")
        self.assertEqual(len(deck.property("history").toVariant()), 4)
        deck.goBack()
        self.assertEqual(deck.property("route"), "instance")
        deck.openPage("tasks")
        QTest.qWait(400)
        self.assertIsNone(self.visual_item("cancelTaskButton"))
        self.assertEqual(deck.findChild(QObject, "pageLoader").property("item").property("tasks").toVariant(), [])
        deck.goBack()
        deck.openPage("tasks")
        self.assertEqual(deck.findChild(QObject, "pageLoader").property("item").property("tasks").toVariant(), [])
        self.window.navigate(4)
        QTest.qWait(400)
        self.assertEqual(deck.property("route"), "")
        self.assertFalse(deck.property("canGoBack"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
