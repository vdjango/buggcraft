"""In-place first-run coach that spotlights existing launcher controls."""
from PySide6.QtCore import QEvent, QObject, QRectF, QTimer, Qt, QVariantAnimation, Slot
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QWidget


class _Spotlight(QWidget):
    def __init__(self, owner, parent):
        super().__init__(parent)
        self.owner = owner
        self.target = QRectF()
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

    def _set_glow(self, value):
        self.glow = value
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)

    def paintEvent(self, event):
        if not self.owner.visible or self.target.isEmpty():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        hole = self.target.adjusted(-7, -7, 7, 7)
        mask = QPainterPath()
        mask.setFillRule(Qt.OddEvenFill)
        mask.addRect(QRectF(self.rect()))
        mask.addRoundedRect(hole, 6, 6)
        painter.fillPath(mask, QColor(10, 9, 15, 178))
        painter.setPen(QPen(QColor(157, 131, 255, 170 + round(80 * self.glow)), 2))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(hole, 6, 6)

        step = self.owner.steps[self.owner.index]
        width = min(310, max(230, self.width() - 32))
        height = 106
        x = min(max(16, hole.left()), self.width() - width - 16)
        y = hole.bottom() + 14
        if y + height > self.height() - 12:
            y = max(12, hole.top() - height - 14)
        box = QRectF(x, y, width, height)
        painter.setPen(QPen(QColor("#514970"), 1))
        painter.setBrush(QColor("#211f2b"))
        painter.drawRoundedRect(box, 5, 5)
        painter.setPen(QColor("#a994ff"))
        painter.setFont(self.font())
        painter.drawText(box.adjusted(14, 12, -14, -68), Qt.AlignLeft | Qt.AlignVCenter,
                         f"{self.owner.index + 1} / {len(self.owner.steps)}  ·  {step['title']}")
        painter.setPen(QColor("#f0edf7"))
        painter.drawText(box.adjusted(14, 35, -14, -25), Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap,
                         step["body"])
        painter.setPen(QColor("#aaa2b9"))
        footer = "回车键继续  ·  退出键跳过" if step.get("key_next") else "点击高亮区域继续  ·  退出键跳过"
        painter.drawText(box.adjusted(14, 0, -14, -9), Qt.AlignLeft | Qt.AlignBottom, footer)


class OnboardingCoach(QObject):
    """Coordinates a lightweight spotlight over actual QML controls."""
    steps = [
        dict(target="launcher-nav-settings", title="先设置游戏",
             body="这里打开启动器设置。我们先确认游戏语言和资源介绍翻译。", window="launcher", action="settings"),
        dict(target="setting-select-game-language", title="选择游戏语言",
             body="选择 Minecraft 内使用的语言。启动器会在下次启动游戏时应用。", window="launcher", action="language"),
        dict(target="setting-toggle-translation.enabled", title="资源介绍翻译",
             body="开启后，模组、资源包等介绍会显示翻译。这个开关不会修改游戏文件。", window="launcher", action="translation"),
        dict(target="open-lobby-home", title="进入联机大厅",
             body="大厅可以浏览公开房间，也可以自己创建房间。", window="launcher", action="lobby"),
        dict(target="node-picker", title="选择联机节点",
             body="先选择可用节点；没有节点时，可从这里添加接入码或稍后再设置。", window="lobby", key_next=True),
        dict(target="rooms-list", title="发现房间",
             body="公开房间会显示在这里。可以搜索并查看，再由你决定是否加入。", window="lobby", key_next=True),
        dict(target="open-create", title="主动创建",
             body="点击这里配置世界和房间可见范围。创建操作会在你确认后才执行。", window="lobby", action="create"),
        dict(target="create-advanced", title="可选房间设置",
             body="高级选项中可以公开房间或同步聊天；默认使用私密房间。", window="lobby", action="privacy"),
        dict(target="create-next", title="检查游戏世界",
             body="这里会检查选中的世界和联机端口。按 Enter 结束教学；之后确认信息再点这里继续，不会自动开房。", window="lobby", action="create-world"),
    ]

    def __init__(self, launcher):
        super().__init__(launcher)
        self.launcher = launcher
        self.index = 0
        self.visible = False
        self._overlays = {}
        self._target_object = None
        self._target_rect = QRectF()
        self._lobby = None
        self._timer = QTimer(self)
        self._timer.setInterval(120)
        self._timer.timeout.connect(self.refresh)
        QApplication.instance().installEventFilter(self)

    def start(self):
        if self.launcher.settings_manager.get_setting("onboarding.completed", False):
            return
        self.visible = True
        self.index = 0
        self._timer.start()
        self.refresh()

    def attach_lobby(self, lobby):
        self._lobby = lobby
        if self.visible and self.steps[self.index]["window"] == "lobby":
            QTimer.singleShot(180, self.refresh)

    @Slot(str)
    def action(self, action):
        if self.visible and self.steps[self.index].get("action") == action:
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
            return
        quick, item = target
        rect = item.boundingRect()
        top_left = item.mapToScene(rect.topLeft())
        bottom_right = item.mapToScene(rect.bottomRight())
        global_top = quick.mapToGlobal(top_left.toPoint())
        global_bottom = quick.mapToGlobal(bottom_right.toPoint())
        overlay = self._set_overlay(window)
        self._target_object = item
        self._target_rect = QRectF(overlay.mapFromGlobal(global_top), overlay.mapFromGlobal(global_bottom))
        overlay.target = self._target_rect
        overlay.update()

    @staticmethod
    def _find_qml_item(parent, name):
        pending = [parent]
        visited = set()
        while pending:
            item = pending.pop()
            identity = id(item)
            if identity in visited:
                continue
            visited.add(identity)
            if item.objectName() == name:
                return item
            pending.extend(item.childItems())
        return None

    def _advance(self):
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
        self._target_object = None
        self._target_rect = QRectF()
        if self.steps[self.index]["window"] != old:
            overlay = self._overlays.get(self.launcher)
            if overlay:
                overlay.hide()
        self.refresh()

    def finish(self):
        self.visible = False
        self._timer.stop()
        self.launcher.settings_manager.set_setting("onboarding.completed", True)
        self.launcher.settings_manager.save_settings()
        for overlay in self._overlays.values():
            overlay.hide()

    def eventFilter(self, watched, event):
        if not self.visible:
            return False
        if event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape:
            self.finish()
            return False
        if event.type() == QEvent.KeyPress and event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if self.steps[self.index].get("key_next"):
                self._advance()
                return False
        return False
