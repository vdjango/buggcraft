"""In-place first-run coach that spotlights existing launcher controls."""
from PySide6.QtCore import QEvent, QObject, Property, QRectF, QTimer, Qt, QVariantAnimation, Signal, Slot
from PySide6.QtGui import QColor, QFontMetricsF, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QWidget


class _Spotlight(QWidget):
    def __init__(self, owner, parent):
        super().__init__(parent)
        self.owner = owner
        self.target = QRectF()
        self.card_rect = QRectF()
        self.body_rect = QRectF()
        self.body_height = 0
        self.glow = 0.0
        self.animation = QVariantAnimation(self)
        self.animation.setDuration(1400)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.setLoopCount(-1)
        self.animation.valueChanged.connect(self._set_glow)
        self.animation.start()
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setFocusPolicy(Qt.NoFocus)
        self.show()
        self.raise_()

    @Slot(float)
    def _set_glow(self, value):
        self.glow = value
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)

    def paintEvent(self, event):
        if not self.owner.visible:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        holes = [] if self.target.isEmpty() else [self.target.adjusted(-7, -7, 7, 7)]
        popup = self.owner._popup_rect(self)
        if not popup.isEmpty():
            holes.append(popup.adjusted(-5, -5, 5, 5))
        mask = QPainterPath()
        mask.addRect(QRectF(self.rect()))
        clear = QPainterPath()
        for hole in holes:
            part = QPainterPath()
            part.addRoundedRect(hole, 6, 6)
            clear = clear.united(part)
        mask = mask.subtracted(clear)
        painter.fillPath(mask, QColor(10, 9, 15, 178))
        pulse = 0 if self.owner.demoStep == "multiplayer-normal" else self.glow
        painter.setPen(QPen(QColor(157, 131, 255, 170 + round(80 * pulse)), 2))
        painter.setBrush(Qt.NoBrush)
        for hole in holes:
            painter.drawRoundedRect(hole, 6, 6)

        step = self.owner.current_step()
        font = self.font()
        font.setPixelSize(12)
        width = min(390, self.width() - 32)
        metrics = QFontMetricsF(font)
        self.body_height = metrics.boundingRect(QRectF(0, 0, width - 36, 2000),
                                                Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap,
                                                step["body"]).height()
        focus_terms = self._focus_terms(step)
        focus_height = 28 if focus_terms else 0
        height = self.body_height + focus_height + (124 if step.get("key_next") else 112)
        if holes:
            bounds = holes[0]
            for hole in holes[1:]:
                bounds = bounds.united(hole)
        else:
            # A QML delegate can be briefly unavailable while the room page
            # changes. Keep a centered, keyboard-operable prompt during that
            # gap instead of hiding the coach altogether.
            bounds = QRectF(self.rect().center().x(), self.rect().center().y(), 1, 1)
        x = min(max(16, bounds.left()), max(16, self.width() - width - 16))
        candidates = [QRectF(x, bounds.bottom() + 14, width, height),
                      QRectF(x, bounds.top() - height - 14, width, height),
                      QRectF(bounds.left() - width - 14, max(12, bounds.top()), width, height),
                      QRectF(bounds.right() + 14, max(12, bounds.top()), width, height)]
        canvas = QRectF(self.rect()).adjusted(12, 12, -12, -12)
        for candidate in candidates:
            candidate.moveLeft(min(max(canvas.left(), candidate.left()), canvas.right() - width))
            candidate.moveTop(min(max(canvas.top(), candidate.top()), canvas.bottom() - height))
        def covered_area(rect):
            return sum(rect.intersected(hole).width() * rect.intersected(hole).height()
                       for hole in holes if rect.intersects(hole))
        box = min(candidates, key=covered_area)
        self.card_rect = box
        self.body_rect = QRectF(box.left() + 18, box.top() + 72 + focus_height,
                                width - 36, self.body_height + 1)

        # Match the launcher surfaces: a quiet violet panel, a thin accent
        # rail, and a clear hierarchy that makes the action unambiguous.
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 82))
        painter.drawRoundedRect(box.translated(0, 4), 10, 10)
        painter.setBrush(QColor("#211d2b"))
        painter.drawRoundedRect(box, 10, 10)
        painter.setPen(QPen(QColor("#5a4c78"), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(box, 10, 10)
        painter.setPen(QPen(QColor("#9b7cff"), 3))
        painter.drawLine(box.left() + 12, box.top() + 1, box.left() + width * 0.32, box.top() + 1)

        font.setBold(False)
        font.setPixelSize(11)
        painter.setFont(font)
        painter.setPen(QColor("#b8a9d9"))
        section = "设置" if step["window"] == "launcher" else "联机房间"
        painter.drawText(QRectF(box.left() + 18, box.top() + 12, width - 118, 18),
                         Qt.AlignLeft | Qt.AlignVCenter, f"首次使用  /  {section}")
        painter.setPen(QColor("#d9ccff"))
        painter.drawText(QRectF(box.right() - 82, box.top() + 12, 64, 18),
                         Qt.AlignRight | Qt.AlignVCenter,
                         f"{self.owner.index + 1:02d} / {len(self.owner.steps):02d}")
        title_font = self.font()
        title_font.setPixelSize(16)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(QColor("#f4f0ff"))
        painter.drawText(QRectF(box.left() + 18, box.top() + 32, width - 36, 28),
                         Qt.AlignLeft | Qt.AlignVCenter, step["title"])
        painter.setPen(QPen(QColor("#3b334c"), 1))
        painter.drawLine(box.left() + 18, box.top() + 64, box.right() - 18, box.top() + 64)
        painter.setPen(QColor("#8f849f"))
        font.setPixelSize(11)
        font.setBold(False)
        painter.setFont(font)
        painter.drawText(QRectF(box.right() - 72, box.top() + 34, 54, 22),
                         Qt.AlignRight | Qt.AlignVCenter, "Esc 跳过")

        if focus_terms:
            chip_x = box.left() + 18
            chip_y = box.top() + 72
            for term in focus_terms:
                chip_font = self.font()
                chip_font.setPixelSize(10)
                painter.setFont(chip_font)
                chip_width = QFontMetricsF(chip_font).horizontalAdvance(term) + 18
                chip = QRectF(chip_x, chip_y, chip_width, 22)
                painter.setBrush(QColor("#302643"))
                painter.setPen(QPen(QColor("#765da2"), 1))
                painter.drawRoundedRect(chip, 6, 6)
                painter.setPen(QColor("#d8c5ff"))
                painter.drawText(chip, Qt.AlignCenter, term)
                chip_x += chip_width + 6
                if chip_x > box.right() - 80:
                    break
        painter.setFont(font)
        painter.setPen(QColor("#eee9f8"))
        painter.drawText(self.body_rect, Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap, step["body"])
        self.owner._continue_rect = QRectF()
        if step.get("key_next"):
            button = QRectF(box.right() - 134, box.bottom() - 42, 116, 30)
            painter.setBrush(QColor("#54417f"))
            painter.setPen(QPen(QColor("#cdbbff"), 1))
            painter.drawRoundedRect(button, 7, 7)
            painter.setPen(QColor("#f6e9b0"))
            painter.setFont(font)
            painter.drawText(button, Qt.AlignCenter, step.get("button", "点击继续"))
            self.owner._continue_rect = button
            key = QRectF(box.left() + 18, box.bottom() - 42, 92, 30)
            painter.setBrush(QColor("#263c4a"))
            painter.setPen(QPen(QColor("#77cce0"), 1))
            painter.drawRoundedRect(key, 7, 7)
            painter.setPen(QColor("#a8e8f5"))
            painter.drawText(key, Qt.AlignCenter, "Enter 继续")
        else:
            hint = step.get("hint", "请点击高亮区域操作")
            if self.target.isEmpty():
                hint = "目标正在载入，可按 Enter 继续"
            hint_box = QRectF(box.left() + 18, box.bottom() - 42, width - 36, 30)
            painter.setBrush(QColor("#302643"))
            painter.setPen(QPen(QColor("#765da2"), 1))
            painter.drawRoundedRect(hint_box, 7, 7)
            painter.setPen(QColor("#f6e9b0"))
            painter.drawText(hint_box, Qt.AlignCenter, hint)

    @staticmethod
    def _focus_terms(step):
        """Return a few short labels that make the requested action scannable."""
        terms = ("设置", "语言", "翻译", "点击", "Enter", "启动器接入码", "创建房间", "简体中文", "自动", "提示", "好友", "Minecraft")
        return tuple(term for term in terms if term in step["body"])[0:3]


class OnboardingCoach(QObject):
    """Coordinates a lightweight spotlight over actual QML controls."""
    changed = Signal()
    steps = [
        dict(target="launcher-nav-settings", title="先设置游戏",
             body="这里打开启动器设置。我们先确认游戏语言和资源介绍翻译。", window="launcher", action="settings"),
        dict(target="setting-select-game-language", title="选择游戏语言", demo="language",
             body="点击整个紫色发光的下拉框，再从列表中选择你想使用的 Minecraft 游戏语言，例如‘简体中文’。这是游戏语言，修改后下次启动游戏生效。", hint="点击下拉框 → 点击一种语言", window="launcher", action="language"),
        dict(target="setting-toggle-translation.enabled", title="资源介绍翻译",
             body="开启后，模组、资源包等介绍会显示翻译。这个开关不会修改游戏文件。", window="launcher", action="translation"),
        dict(target="setting-group-multiplayer.quick_action", title="联机设置怎么工作",
             body="自动：游戏开放局域网后自动创建房间并打开，识别房间邀请码时自动加入。提示：只闪烁首页联机按钮，由你点击确认。关闭：完全手动。请在下方选一项。", window="launcher", action="quick_action"),
        dict(target="setting-toggle-multiplayer.notification_sound", title="好友与联机提示音", demo="sound-settings",
             body="收到好友申请、房间邀请或加入申请时，可以播放声音提醒。点击高亮开关选择是否播放；关闭声音后，闪烁和未读提醒仍会保留。设置立即生效，选好后点击继续，也可以直接保留当前选择。", window="launcher", key_next=True),
        dict(target="open-lobby-home", title="先认识联机提醒",
             body="现在是联机按钮的正常状态。选择‘首页提示’时，游戏开放局域网后，这里会闪烁提醒；需要你点击才会处理。点击下方按钮，先体验一次闪烁。", window="launcher", action="lobby", demo="multiplayer", key_next=True, button="体验闪烁"),
        dict(target="tutorial-friends-target", title="好友通知会闪烁",
             body="收到好友请求或房间邀请时，好友按钮会像这样闪烁，并显示未读数量。这只是通知演示，无需添加好友；实际使用时，先添加启动器接入码，才会显示真实好友按钮。", window="launcher", action="friends", demo="friends", key_next=True),
        dict(target="node-picker", title="查看联机节点入口", demo="node",
             body="点击发光的下拉框查看选项。教学期间‘添加与管理节点’会被锁定，不会进入添加页面；真实使用时再选择它，粘贴启动器接入码并连接节点。本次只查看入口，随后直接继续。", window="lobby", key_next=True),
        dict(target="rooms-list", title="发现房间",
             body="添加节点并连接成功后，公开房间会显示在这里。没有节点时不会显示房间，这是正常状态。按 Enter 继续。", window="lobby", key_next=True),
        dict(target="create-mode-prepare", title="可以先开房再准备", demo="create",
             body="创建房间有两种方式。默认先开房：房主不启动游戏也能邀请朋友，朋友可以先同步安装。房间先等大家准备，你随时可以启动游戏。点击继续，认识另一种方式。", window="lobby", key_next=True, prepare="create"),
        dict(target="create-mode-world", title="也可以关联已开放的世界", demo="create-world",
             body="如果你已经进入 Minecraft 并选择了‘对局域网开放’，点击这个选项，再从扫描结果里选择世界。这个方式会检查真实游戏端口。按 Enter 继续。", window="lobby", key_next=True),
        dict(target="create-node-unavailable", title="为什么现在不能创建",
             body="创建房间和好友功能都需要先添加启动器接入码。本次演示按未添加接入码的状态展示，所以创建按钮不可用；实际添加并连接节点后即可操作。", window="lobby", key_next=True),
        dict(target="create-next", title="确认后创建房间",
             body="选好游戏配置和创建方式后，点击这里创建房间。不必等游戏启动；选择关联世界时，先选好开放的世界。点击完成或按 Enter，将关闭联机大厅并返回首页。", window="lobby", key_next=True, button="完成教学"),
    ]

    def __init__(self, launcher):
        super().__init__(launcher)
        self.launcher = launcher
        self.index = 0
        self.visible = False
        self._overlays = {}
        self._target_object = None
        self._target_quick = None
        self._target_rect = QRectF()
        self._continue_rect = QRectF()
        self._continue_pressed = False
        self._lobby = None
        self._multiplayer_demo_active = False
        self._create_snapshot = None
        self._timer = QTimer(self)
        self._timer.setInterval(120)
        self._timer.timeout.connect(self.refresh)

    def start(self):
        if self.launcher.settings_manager.get_setting("onboarding.completed", False):
            return
        # Only active teaching needs a global input lock. Keeping a Python
        # application filter installed during normal background downloads also
        # routes unrelated Qt object events through the UI's Python callback.
        QApplication.instance().installEventFilter(self)
        self.visible = True
        self.index = 0
        self._multiplayer_demo_active = False
        self._continue_rect = QRectF()
        self.changed.emit()
        self._timer.start()
        self._prepare_step()
        self.refresh()

    @Slot(str, result=bool)
    def isStep(self, name):
        return self.demoStep == name

    @Property(str, notify=changed)
    def demoStep(self):
        """The current synthetic demo marker, exposed reactively to QML."""
        if not self.visible:
            return ""
        if self.steps[self.index].get("demo") == "multiplayer":
            return "multiplayer" if self._multiplayer_demo_active else "multiplayer-normal"
        return str(self.steps[self.index].get("demo", ""))

    def current_step(self):
        step = self.steps[self.index]
        if step.get("demo") == "multiplayer" and self._multiplayer_demo_active:
            return {**step, "title": "这就是联机提醒", "key_next": False,
                    "body": "看到按钮闪烁了吗？这表示发现了可联机事件。‘提示’需要点击确认；‘自动’则会在开放局域网后自动创建房间并打开。接下来点击发光按钮，认识好友通知。",
                    "hint": "点击闪烁的联机按钮继续"}
        return step

    def _prepare_step(self):
        step = self.steps[self.index]
        target = self.steps[self.index]["target"]
        if target.startswith("setting-"):
            self.launcher.switch_pages("设置")
            self.launcher.settings_page.general_tab_btn_clicked()
        elif target == "open-lobby-home":
            self.launcher.switch_pages("开始")
        elif step.get("prepare") == "create" and self._lobby is not None:
            # Show the create page even without a node so the disabled state
            # teaches the real prerequisite instead of pretending it works.
            # The normal controller rejects this route until a node exists.
            # For onboarding, show the same page in a read-only state so the
            # disabled controls and their prerequisite remain visible.
            backend = self._lobby_backend()
            if backend is not None:
                keys = ("page", "worlds", "nodeAvailable", "worldScanning", "busy", "error", "notice", "pendingOpenWorldPort")
                self._create_snapshot = {key: backend.view.get(key) for key in keys}
                self._update_backend(backend, page="create", worlds=[], nodeAvailable=False,
                                     worldScanning=False, busy=False, error="", notice="", pendingOpenWorldPort=0)
        elif target == "node-picker":
            if self._lobby is None:
                self.launcher.started_page._ensure_multiplayer_dialog()
                self.attach_lobby(self.launcher.started_page._multiplayer_dialog)
            self._lobby.showNormal()
            self._lobby.raise_()
            self._lobby.activateWindow()
            backend = self._lobby_backend()
            if backend is not None:
                self._update_backend(backend, page="hall")

    def _lobby_backend(self):
        if self._lobby is None:
            return None
        backend = getattr(self._lobby, "backend", None)
        if backend is not None:
            return backend
        for quick in self._lobby.findChildren(QWidget, ""):
            context = getattr(quick, "rootContext", None)
            if context is not None:
                backend = context().contextProperty("lobby")
                if backend is not None:
                    return backend
        return None

    @staticmethod
    def _update_backend(backend, **values):
        """Update either the live controller or the lightweight QML test backend."""
        patch = getattr(backend, "patch", None)
        if callable(patch):
            patch(**values)
            return
        state = getattr(backend, "_view", None)
        if isinstance(state, dict):
            backend._view = {**state, **values}
            signal = getattr(backend, "viewChanged", None) or getattr(backend, "changed", None)
            if signal is not None:
                signal.emit()

    def attach_lobby(self, lobby):
        self._lobby = lobby
        if self.visible and self.steps[self.index]["window"] == "lobby":
            QTimer.singleShot(180, self.refresh)

    @Slot(str)
    def action(self, action):
        if self.visible and self.steps[self.index].get("action") == action:
            if action == "lobby" and not self._multiplayer_demo_active:
                self._multiplayer_demo_active = True
                self.changed.emit()
                self.refresh()
                return
            self._advance()

    def _continue(self):
        if self.steps[self.index].get("demo") == "multiplayer" and not self._multiplayer_demo_active:
            self.action("lobby")
            return
        self._advance()

    def _window(self):
        return self.launcher if self.steps[self.index]["window"] == "launcher" else self._lobby

    def _set_overlay(self, window):
        if window not in self._overlays:
            self._overlays[window] = _Spotlight(self, window.centralWidget() if hasattr(window, "centralWidget") else window)
        overlay = self._overlays[window]
        parent = overlay.parentWidget()
        overlay.setGeometry(parent.rect())
        overlay.show()
        overlay.raise_()
        return overlay

    def refresh(self):
        if not self.visible:
            return
        window = self._window()
        if window is None or not window.isVisible():
            return
        name = self.steps[self.index]["target"]
        quicks = window.findChildren(QWidget, "")
        target = None
        for quick in quicks:
            if not quick.isVisible():
                continue
            root = getattr(quick, "rootObject", None)
            if root is None:
                continue
            root_object = root()
            if root_object is None:
                continue
            item = self._find_qml_item(root_object, name)
            if item is not None:
                target = (quick, item)
                break
        if target is None:
            if name.startswith("setting-"):
                page = self.launcher.settings_page.general_page
                if page.isVisible():
                    page.controller.tutorialTargetRequested.emit(name)
            if self.steps[self.index]["window"] == "lobby":
                # Room delegates can disappear for one event loop turn while
                # switching pages. Keep the keyboard/click continuation card
                # visible until the real target is mounted again.
                overlay = self._set_overlay(window)
                self._target_object = None
                self._target_quick = None
                self._target_rect = QRectF()
                overlay.target = QRectF()
                overlay.update()
            return
        quick, item = target
        if not item.isVisible() or item.width() <= 0 or item.height() <= 0:
            if name.startswith("setting-"):
                self.launcher.settings_page.general_page.controller.tutorialTargetRequested.emit(name)
            if self.steps[self.index]["window"] == "lobby":
                overlay = self._set_overlay(window)
                self._target_object = None
                self._target_quick = None
                self._target_rect = QRectF()
                overlay.target = QRectF()
                overlay.update()
            return
        rect = item.boundingRect()
        top_left = item.mapToScene(rect.topLeft())
        bottom_right = item.mapToScene(rect.bottomRight())
        scene_rect = QRectF(top_left, bottom_right)
        if name.startswith("setting-") and not QRectF(quick.rect()).contains(scene_rect):
            self.launcher.settings_page.general_page.controller.tutorialTargetRequested.emit(name)
            return
        global_top = quick.mapToGlobal(top_left.toPoint())
        global_bottom = quick.mapToGlobal(bottom_right.toPoint())
        overlay = self._set_overlay(window)
        self._target_object = item
        self._target_quick = quick
        self._target_rect = QRectF(overlay.mapFromGlobal(global_top), overlay.mapFromGlobal(global_bottom))
        overlay.target = self._target_rect
        overlay.update()

    def _popup_item(self):
        if self._target_object is None:
            return None
        try:
            if not self._target_object.property("tutorialPopupVisible"):
                return None
            window = self._target_object.window()
            if window is not None:
                return self._find_qml_item(window.contentItem(), self._target_object.objectName() + "-popup")
        except RuntimeError:
            pass
        return None

    def _popup_rect(self, overlay):
        popup = self._popup_item()
        if popup is None:
            return QRectF()
        top = self._target_quick.mapToGlobal(popup.mapToScene(popup.boundingRect().topLeft()).toPoint())
        bottom = self._target_quick.mapToGlobal(popup.mapToScene(popup.boundingRect().bottomRight()).toPoint())
        return QRectF(overlay.mapFromGlobal(top), overlay.mapFromGlobal(bottom))

    @staticmethod
    def _find_qml_item(parent, name):
        pending = [parent]
        visited = set()
        while pending:
            item = pending.pop()
            # Keep wrappers alive while traversing. PySide can otherwise reuse
            # a collected wrapper's id for an unrelated, unvisited QML item.
            if item in visited:
                continue
            visited.add(item)
            if item.objectName() == name:
                return item
            pending.extend(item.childItems())
        return None

    def _allowed_global_rects(self):
        if self._target_rect.isEmpty():
            return []
        window = self._window()
        overlay = self._overlays.get(window)
        if overlay is None:
            return []
        target = self._target_rect.toRect().adjusted(-8, -8, 8, 8)
        result = [QRectF(overlay.mapToGlobal(target.topLeft()),
                         overlay.mapToGlobal(target.bottomRight()))]
        # ComboBox options live in a popup outside the combo rectangle. Allow
        # those clicks while still blocking every unrelated control.
        popup = self._popup_item()
        if popup is not None:
            top = self._target_quick.mapToGlobal(popup.mapToScene(popup.boundingRect().topLeft()).toPoint())
            bottom = self._target_quick.mapToGlobal(popup.mapToScene(popup.boundingRect().bottomRight()).toPoint())
            result.append(QRectF(top, bottom))
        return result

    def _continue_contains(self, point):
        if self._continue_rect.isEmpty():
            return False
        window = self._window()
        overlay = self._overlays.get(window)
        if overlay is None:
            return False
        top_left = overlay.mapToGlobal(self._continue_rect.topLeft().toPoint())
        bottom_right = overlay.mapToGlobal(self._continue_rect.bottomRight().toPoint())
        return QRectF(top_left, bottom_right).contains(point)

    def _advance(self):
        self._continue_rect = QRectF()
        if self.index + 1 >= len(self.steps):
            self.finish()
            return
        current_window = self._window()
        overlay = self._overlays.get(current_window)
        if overlay:
            overlay.target = QRectF()
            overlay.hide()
        old = self.steps[self.index]["window"]
        self.index += 1
        self.changed.emit()
        self._target_object = None
        self._target_quick = None
        self._target_rect = QRectF()
        if self.steps[self.index]["window"] != old:
            overlay = self._overlays.get(self.launcher)
            if overlay:
                overlay.target = QRectF()
                overlay.show()
                overlay.raise_()
                overlay.update()
        # Navigation/reloading may destroy the clicked QML delegate. Wait until
        # its signal handler returns before preparing the following page.
        QTimer.singleShot(0, self, self._prepare_and_refresh)

    def _prepare_and_refresh(self):
        if self.visible:
            self._prepare_step()
            self.refresh()

    def finish(self):
        self.visible = False
        QApplication.instance().removeEventFilter(self)
        self.changed.emit()
        self._timer.stop()
        self._continue_rect = QRectF()
        if self._create_snapshot is not None:
            backend = self._lobby_backend()
            if backend is not None:
                self._update_backend(backend, **self._create_snapshot)
            self._create_snapshot = None
        self.launcher.settings_manager.set_setting("onboarding.completed", True)
        self.launcher.settings_manager.save_settings()
        for overlay in self._overlays.values():
            overlay.hide()
        if self._lobby is not None:
            self._lobby.close()
        self.launcher.switch_pages("开始")
        self.launcher.showNormal()
        self.launcher.raise_()
        self.launcher.activateWindow()

    def eventFilter(self, watched, event):
        if not self.visible:
            return False
        if event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape:
            self.finish()
            return True
        if event.type() == QEvent.KeyPress and event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if self.current_step().get("key_next"):
                self._continue()
                return True
        if event.type() == QEvent.KeyPress and event.key() in (Qt.Key_Tab, Qt.Key_Backtab):
            return True
        if event.type() == QEvent.KeyPress:
            # Only the active choice may accept typing/arrow keys. Stale focus
            # on a previous control must not change unrelated settings.
            choice = self._target_object
            return not (self.demoStep in ("language", "node") and choice is not None
                        and choice.property("activeFocus"))
        if event.type() == QEvent.Wheel:
            return not any(rect.contains(event.globalPosition()) for rect in self._allowed_global_rects())
        if event.type() in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease, QEvent.MouseButtonDblClick):
            try:
                point = event.globalPosition().toPoint()
            except AttributeError:
                point = event.globalPos()
            if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                if self._continue_contains(point):
                    self._continue_pressed = True
                    return True
            if event.type() == QEvent.MouseButtonRelease and self._continue_pressed:
                self._continue_pressed = False
                if event.button() == Qt.LeftButton and self._continue_contains(point):
                    self._continue()
                return True
            if not any(rect.contains(point) for rect in self._allowed_global_rects()):
                # Consume all unrelated clicks while teaching.
                return True
        return False
