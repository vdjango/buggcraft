"""Client UI acceptance cases.

The tests create the production launcher window, deliver Qt input events
directly to its controls, and keep remote responses local and deterministic.
The default offscreen platform renders the UI without occupying the desktop.
Set ``QT_QPA_PLATFORM=windows`` only for an intentional visible replay.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sys
from unittest.mock import Mock, patch

from _qml_test_support import LauncherQmlCase, QTest, Qt, qt_mouse_click, qt_mouse_drag

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "buggcraft"))

from PySide6.QtCore import QPoint, QTimer
from client_ui_fixtures import ClientUiFixtures


class ClientUiAcceptanceCase(LauncherQmlCase):
    """Shared Qt event helpers and isolated client data."""

    def setUp(self):
        super().setUp()
        self.pause = max(0, int(os.environ.get("BUGGCRAFT_UI_PAUSE_MS", "120")))
        root = Path(os.environ.get(
            "BUGGCRAFT_UI_OUTPUT",
            str(ROOT.parent / ".test-tools" / "client-ui-pytest"),
        )).resolve()
        self.output = root / self._testMethodName
        self.screens = self.output / "screenshots"
        self.screens.mkdir(parents=True, exist_ok=True)
        self.actions = []
        self.checks = []
        self._test_passed = False
        self.fixtures = ClientUiFixtures(self.output)
        self.addCleanup(self.fixtures.close)

        self.manager.set_setting("minecraft.directory.enable", str(self.game_dir))
        self.manager.set_setting("minecraft.directory.installed", [str(self.game_dir)])
        self.manager.set_setting("minecraft.version.enable", "1.21.8")
        self.manager.set_setting("minecraft.version.installed", ["1.21.8", "1.20.1"])
        self.manager.set_setting("multiplayer.notification_sound", True)
        self.manager.set_setting("launcher.allow_multiple", False)

        self._patch(patch(
            "core.downloads.MinecraftDownloader.urls",
            lambda _downloader, url: self.fixtures.route(_downloader, url),
        ))
        self._patch(patch("core.content.ContentCatalogue.search", self._fixture_search))
        self._patch(patch("core.content.ContentCatalogue.versions",
                          lambda catalogue, *args, **kwargs:
                          self._fixture_versions(catalogue, *args, **kwargs)))
        self._patch(patch("core.content.ContentCatalogue.project", self._fixture_project))
        self._patch(patch("ui.pages.qml_games.GameCatalogueController.refresh", lambda *_a, **_k: None))
        try:
            import core.loaders as loaders
            self._patch(patch.object(loaders, "available_versions", lambda *_a, **_k: ["0.16.9"]))
        except Exception:
            pass
        try:
            import ui.pages.download.content_browser as browser
            self._patch(patch.object(
                browser.QFileDialog,
                "getOpenFileName",
                return_value=(str(self.fixtures.pack_path), "Modrinth pack"),
            ))
        except Exception:
            pass

        # The multiplayer QML and controller remain production objects; only
        # the service transport and worker are local to this acceptance case.
        try:
            import ui.multiplayer_controller as multiplayer_module
            self._patch(patch.object(multiplayer_module, "TunnelService",
                                     return_value=Mock(endpoints={})))
            self._patch(patch.object(multiplayer_module.MultiplayerController,
                                     "job", side_effect=lambda _key, task: task.close()))
        except Exception:
            pass

    def _patch(self, patcher):
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def _fixture_search(_catalogue, _query, kind, *_args, **_kwargs):
        return {"hits": [{
            "source": "Modrinth", "project_id": "ui-fixture-" + kind,
            "title": "UI Fixture " + kind, "description": "Local UI fixture",
            "body": "Fixture project details", "game_versions": ["1.21.8"],
            "loaders": ["fabric"], "categories": ["utility"],
        }], "has_more": False}

    def _fixture_versions(self, _catalogue, _project, *args, **kwargs):
        kind = kwargs.get("kind") or (args[2] if len(args) > 2 else "mod")
        name = next(name for name in self.fixtures.payloads
                    if name.startswith("ui-fixture-" + kind + "."))
        return {"versions": [self.fixtures.version(kind)], "has_more": False}

    @staticmethod
    def _fixture_project(_catalogue, _project, *_args, **_kwargs):
        return {"source": "Modrinth", "project_id": "ui-fixture",
                "title": "UI Fixture", "description": "Fixture",
                "body": "Fixture project details", "game_versions": ["1.21.8"]}

    def record(self, kind, target, detail=""):
        self.actions.append({"kind": kind, "target": target, "detail": detail})

    def check(self, condition, label):
        self.assertTrue(condition, label)
        self.checks.append(label)

    def pause_ui(self):
        self.pump(self.pause)

    def settled_item(self, host, name):
        """Wait for wheel inertia and queued layout before aiming a click.

        Qt Quick consumes a press during a flick to stop scrolling. Linux's
        wheel animation can still be moving after a control enters the
        viewport, so a fixed pause alone does not make that press a click.
        """
        import time
        deadline = time.monotonic() + 5
        previous = None
        stable = 0
        while time.monotonic() < deadline:
            self.pump(20)
            item = self.item(host, name)
            point = item.mapToScene(item.boundingRect().center())
            geometry = (point.x(), point.y(), item.width(), item.height())
            moving = False
            ancestor = item
            while ancestor is not None:
                moving = moving or bool(ancestor.property("moving"))
                ancestor = ancestor.parentItem()
            stable = stable + 1 if geometry == previous and not moving else 0
            if stable >= 3:
                return item
            previous = geometry
        self.fail("UI control keeps moving before input: " + name)

    def click_ui(self, host, name):
        item = self.settled_item(host, name)
        self.assertTrue(item.isVisible(), name)
        widget = host.quick if hasattr(host, "quick") else host
        point = item.mapToScene(item.boundingRect().center()).toPoint()
        self.record("mouseClick", name)
        qt_mouse_click(widget, point)
        self.pause_ui()
        return item

    def key_ui(self, host, key, name):
        widget = host.quick if hasattr(host, "quick") else host
        self.record("keyPress", name, str(key))
        QTest.keyClick(widget, key)
        self.pause_ui()

    def text_ui(self, host, name, value):
        self.click_ui(host, name)
        widget = host.quick if hasattr(host, "quick") else host
        QTest.keyClick(widget, Qt.Key_A, Qt.ControlModifier)
        QTest.keyClick(widget, Qt.Key_Backspace)
        self.record("textInput", name, value)
        QTest.keyClicks(widget, value)
        self.pause_ui()

    def drag_ui(self, host, name):
        item = self.settled_item(host, name)
        widget = host.quick if hasattr(host, "quick") else host
        start = item.mapToScene(QPoint(5, int(item.height() / 2))).toPoint()
        end = item.mapToScene(QPoint(max(5, int(item.width() - 5)),
                                     int(item.height() / 2))).toPoint()
        self.record("mouseDrag", name)
        qt_mouse_drag(widget, start, end)
        self.pause_ui()

    def screenshot_ui(self, name, widget=None):
        self.pause_ui()
        image = (widget or self.window).grab()
        self.assertFalse(image.isNull(), name)
        image.save(str(self.screens / (name + ".png")))

    def navigate(self, name):
        self.click_ui(self.window.title_bar, name)

    def wait_for(self, condition, label, timeout=15000):
        deadline = __import__("time").monotonic() + timeout / 1000
        while __import__("time").monotonic() < deadline:
            if condition():
                self.checks.append(label)
                return
            self.pause_ui()
        self.fail("Timed out: " + label)

    def write_report(self, passed):
        self.output.mkdir(parents=True, exist_ok=True)
        (self.output / "actions.jsonl").write_text(
            "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in self.actions),
            encoding="utf-8",
        )
        (self.output / "client-ui-result.json").write_text(json.dumps({
            "passed": passed, "checks": self.checks,
            "qt_platform": self.app.platformName(),
            "mouse_input": "QApplication.sendEvent",
            "actions": self.actions, "screenshots": sorted(
                str(path.relative_to(self.output)) for path in self.screens.glob("*.png")
            ), "test": self._testMethodName,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    def finish_test(self):
        self._test_passed = True

    def tearDown(self):
        self.write_report(self._test_passed)
        super().tearDown()


class ClientUiHomeTests(ClientUiAcceptanceCase):
    """Home workflows use real controls, including the modal login loop."""

    def test_home_version_sidebar_and_page_navigation(self):
        home = self.window.started_page
        header = self.window.title_bar
        previous = home.launcher.minecraft_version
        self.click_ui(header, "version-picker")
        picker = header._picker
        selected = header.controller.versions[1]
        self.check(selected != previous, "picker offers a different installed version")
        self.click_ui(picker.host, "choice-option-1")
        self.check(not picker.isVisible(), "selecting a version closes the popup")
        self.check(home.launcher.minecraft_version == selected
                   and self.manager.get_setting("minecraft.version.enable") == selected,
                   "mouse selection updates the launch version and saved selection")
        self.check(self.item(home, "home-launch-subtitle").property("text") == selected,
                   "home launch button displays the newly selected version")
        self.screenshot_ui("home-version-selected")

        self.click_ui(header, "toggle-launcher-sidebar")
        self.check(self.window.menu_collapsed and home.controller.view["collapsed"],
                   "sidebar collapses through its visible button")
        self.check(not self.item(home, "navigation-option-0").isVisible(),
                   "collapsed sidebar hides login mode controls")
        self.screenshot_ui("home-sidebar-collapsed")
        self.click_ui(header, "toggle-launcher-sidebar")
        self.check(not self.window.menu_collapsed
                   and self.item(home, "navigation-option-0").isVisible(),
                   "second click restores the sidebar and its controls")

        for target, tab in (("launcher-nav-download", 1), ("launcher-nav-settings", 2),
                            ("instances-button", 3), ("launcher-nav-home", 0)):
            self.navigate(target)
            self.check(self.window.current_tab == tab, "home navigation opens " + target)
            self.screenshot_ui("home-navigation-" + str(tab))
        self.check(home.launcher.minecraft_version == selected,
                   "page navigation preserves the selected version")
        self.navigate("instances-button")
        instances = self.window.version_page.versions_page
        instances.ensure_loaded()
        self.click_ui(instances, "instance-row-" + previous)
        self.navigate("launcher-nav-home")
        self.check(home.launcher.minecraft_version == previous
                   and self.item(home, "home-launch-subtitle").property("text") == previous
                   and header.controller.view["selected"] == previous,
                   "clicking another instance synchronizes Home, header and launch selection")
        self.screenshot_ui("home-instance-switched")
        self.assert_no_qml_errors()
        self.finish_test()

    def test_home_offline_login_validation_and_launch_options(self):
        from core.launch_options import offline_uuid

        home = self.window.started_page
        self.click_ui(home, "navigation-option-0")
        self.text_ui(home, "offline-username", "   ")
        self.click_ui(home, "offline-login-confirm")
        self.check(not home.auth_manager.is_authenticated()
                   and self.item(home, "home-status").property("text") == "请输入用户名。",
                   "blank offline username shows an error and does not authenticate")
        with patch.object(home.launcher, "start") as start:
            self.click_ui(home, "launch-game")
            start.assert_not_called()
        self.check(self.item(home, "home-launch-title").property("text") == "请先设置角色",
                   "unauthenticated launch explains the missing role")
        self.screenshot_ui("home-offline-validation")

        self.text_ui(home, "offline-username", "  UI_Player  ")
        self.click_ui(home, "offline-login-confirm")
        self.check(home.auth_manager.is_authenticated()
                   and home.auth_manager.current_mode == "offline",
                   "offline confirmation authenticates the selected account mode")
        self.check(self.item(home, "home-username").property("text") == "UI_Player",
                   "home displays the trimmed offline username")
        self.click_ui(home, "switch-account")
        self.check(not home.auth_manager.is_authenticated()
                   and self.item(home, "offline-username").isVisible(),
                   "switch account clears the role and restores the login input")
        self.text_ui(home, "offline-username", "UI_Player_2")
        self.click_ui(home, "offline-login-confirm")
        saved = json.loads((Path(home.cache_path) / "auth_credentials.json").read_text(encoding="utf-8"))
        self.check(saved["offline"]["username"] == "UI_Player_2"
                   and saved["offline"]["uuid"] == offline_uuid("UI_Player_2"),
                   "offline account switch saves the new username and corresponding UUID")
        self.screenshot_ui("home-offline-authenticated")
        # The real Home launch path builds options; the game worker is the
        # boundary. This case does not claim an actual Java process started.
        with patch.object(home.launcher, "start") as start:
            self.click_ui(home, "launch-game")
        start.assert_called_once_with()
        options = home.launcher._options
        self.check(options["username"] == "UI_Player_2"
                   and options["uuid"] == offline_uuid("UI_Player_2")
                   and options["token"] is None,
                   "launch receives the current offline username, UUID and no online token")
        self.check(options["version"] == home.launcher.minecraft_version
                   and home.launcher._language == self.manager.get_setting("game.language", "zh_cn"),
                   "launch receives the selected version and configured language")
        self.screenshot_ui("home-offline-launch-requested")
        self.assert_no_qml_errors()
        self.finish_test()

    def test_home_online_device_login_cancel_and_success(self):
        import base64

        home = self.window.started_page
        dialog = home.login_dialog
        self.click_ui(home, "navigation-option-1")
        self.check(home.auth_manager.current_mode == "online"
                   and self.item(home, "online-login").isVisible(),
                   "online mode exposes the premium login button")
        # This local token has no credentials or signature and is never sent
        # anywhere. It lets the production UI check expiration and save state.
        payload = base64.urlsafe_b64encode(json.dumps({"exp": 4102444800}).encode()).decode().rstrip("=")
        token = "e30." + payload + ".ui-fixture"
        account = dict(type="online", uuid="a" * 32, token=token,
                       refresh_token="ui-fixture-refresh", expires_at=4102444800)

        for outcome in ("cancel", "success"):
            errors = []
            guard = QTimer(dialog)
            guard.setSingleShot(True)

            def timeout():
                errors.append(AssertionError("Device login UI did not finish"))
                dialog.reject()

            def respond():
                try:
                    dialog.auth.signals.progress.emit("等待微软设备授权")
                    dialog.auth.signals.device_code.emit("UI-CODE", "https://microsoft.com/devicelogin")
                    self.pause_ui()
                    self.check(dialog.isVisible(), "premium login opens a real modal dialog")
                    self.check(self.item(dialog, "login-device-code").property("text") == "UI-CODE"
                               and self.item(dialog, "login-verification-uri").property("text")
                               == "https://microsoft.com/devicelogin",
                               "device code and official sign-in address are displayed")
                    self.click_ui(dialog, "copy-login-code")
                    self.check(self.app.clipboard().text() == "UI-CODE"
                               and dialog.controller.copied,
                               "copy device code updates clipboard and button state")
                    self.screenshot_ui("home-online-device-" + outcome, dialog)
                    if outcome == "cancel":
                        self.click_ui(dialog, "dialog-action-1")
                    else:
                        # Substitute only the external authentication result;
                        # dialog completion, account binding and saving are real.
                        dialog.auth.signals.success.emit("UI_Premium", account)
                except BaseException as error:
                    errors.append(error)
                    dialog.reject()

            guard.timeout.connect(timeout)
            try:
                with patch.object(dialog.auth, "start_login", side_effect=respond) as login:
                    guard.start(10000)
                    self.click_ui(home, "online-login")
                    login.assert_called_once_with()
            finally:
                guard.stop()
                guard.deleteLater()
            if errors:
                raise errors[0]
            self.check(not dialog.isVisible() and not dialog._login_pending,
                       "device login modal loop closes after " + outcome)
            if outcome == "cancel":
                self.check(not home.auth_manager.is_authenticated()
                           and self.item(home, "home-status").property("text") == "取消登录",
                           "cancel preserves unauthenticated state and explains the result")
            else:
                self.check(home.auth_manager.is_authenticated()
                           and home.auth_manager.current_mode == "online"
                           and self.item(home, "home-username").property("text") == "UI_Premium",
                           "authentication response binds and displays the premium account")
        self.screenshot_ui("home-online-authenticated")
        saved = json.loads((Path(home.cache_path) / "auth_credentials.json").read_text(encoding="utf-8"))
        self.check(saved["online"]["username"] == "UI_Premium"
                   and all(saved["online"][field] == account[field]
                           for field in ("uuid", "token", "refresh_token", "expires_at")),
                   "premium authentication saves the account identity and credentials")
        with patch.object(home.launcher, "start") as start:
            self.click_ui(home, "launch-game")
        start.assert_called_once_with()
        self.check(home.launcher._options["uuid"] == account["uuid"]
                   and home.launcher._options["token"] == token
                   and home.launcher._options["username"] == "UI_Premium"
                   and home.launcher._options["version"] == home.launcher.minecraft_version,
                   "premium launch receives the authenticated identity, token and selected version")
        self.assert_no_qml_errors()
        self.finish_test()

    def test_home_lobby_and_direct_friends_entry(self):
        home = self.window.started_page
        self.click_ui(home, "open-lobby-home")
        lobby = home._multiplayer_dialog
        self.check(lobby.isVisible(), "home multiplayer button opens the real lobby")
        self.screenshot_ui("home-opened-lobby", lobby)
        # Only service data is supplied; the direct Home entry still needs an
        # actual click after closing the lobby, as a player would use it.
        lobby.backend.apply_social_state({
            "account": "a" * 32 + "." + "b" * 32, "username": "UITest",
            "friends": [{"account": "c" * 32 + "." + "d" * 32,
                         "username": "Player_01", "online": True}],
            "requests": [], "invitations": [], "joinRequests": [],
            "capabilities": {"room_presence": True, "join_requests": True, "friend_code": True},
        })
        lobby.close()
        self.wait_for(lambda: self.item(home, "open-friends-home").isVisible(),
                      "home friends entry appears after social account data arrives")
        self.click_ui(home, "open-friends-home")
        friends = lobby.friends_window
        self.check(friends is not None and friends.isVisible(),
                   "direct Home friends entry opens the real friends window")
        self.screenshot_ui("home-opened-friends", friends)
        self.key_ui(friends, Qt.Key_Escape, "home-friends-escape")
        self.check(not friends.isVisible() and self.window.isVisible(),
                   "closing friends returns to the launcher")
        self.assert_no_qml_errors()
        self.finish_test()


class ClientUiNavigationTests(ClientUiAcceptanceCase):
    def test_client_ui_navigation_and_settings(self):
        self.check(self.window.isVisible() and self.window.width() > 0,
                   "launcher window visible")
        self.screenshot_ui("home")
        self.click_ui(self.window.title_bar, "version-picker")
        picker = self.window.title_bar._picker
        self.check(picker is not None and picker.isVisible(), "version picker opens")
        self.key_ui(picker, Qt.Key_Down, "version-picker-down")
        self.key_ui(picker, Qt.Key_Escape, "version-picker-escape")
        self.check(not picker.isVisible(), "version picker closes with Escape")

        self.click_ui(self.window.title_bar, "instances-button")
        self.check(self.window.current_tab == 3, "instances page opens")
        self.screenshot_ui("instances")
        self.click_ui(self.window.title_bar, "launcher-nav-home")

        self.navigate("launcher-nav-settings")
        page = self.window.settings_page.general_page
        page.ensure_loaded()
        self.screenshot_ui("settings")
        page.quick.rootObject().revealTutorialTarget("setting-select-game-language")
        self.click_ui(page, "setting-select-game-language")
        self.key_ui(page, Qt.Key_Escape, "language-escape")
        page.quick.rootObject().revealTutorialTarget("setting-toggle-translation.enabled")
        self.click_ui(page, "setting-toggle-translation.enabled")
        self.click_ui(page, "setting-toggle-translation.enabled")
        page.quick.rootObject().revealTutorialTarget("setting-option-multiplayer.quick_action-1")
        self.click_ui(page, "setting-option-multiplayer.quick_action-1")
        page.quick.rootObject().revealTutorialTarget("setting-toggle-multiplayer.notification_sound")
        self.click_ui(page, "setting-toggle-multiplayer.notification_sound")
        self.click_ui(page, "setting-toggle-multiplayer.notification_sound")
        self.drag_ui(page, "setting-opacity-slider")
        self.screenshot_ui("settings-controls")

        self.window.settings_page.java_tab_btn_clicked()
        self.window.settings_page.java_page.ensure_loaded()
        self.check(self.item(self.window.settings_page.java_page, "java-versions-section") is not None,
                   "Java settings page rendered")
        self.window.settings_page.about_tab_btn_clicked()
        self.window.settings_page.about_page.ensure_loaded()
        self.screenshot_ui("settings-about")
        self.finish_test()


class ClientUiInstanceTests(ClientUiAcceptanceCase):
    def open_instances(self):
        self.click_ui(self.window.title_bar, 'instances-button')
        page = self.window.version_page.versions_page
        page.ensure_loaded()
        self.check(self.window.current_tab == 3, 'instance management visible')
        return page

    def test_instance_selection_settings_folder_and_directory_switch(self):
        page = self.open_instances()
        self.click_ui(page, 'instance-row-1.20.1')
        self.check(self.manager.get_setting('minecraft.version.enable') == '1.20.1',
                   'clicked instance becomes the selected launch version')
        with patch('ui.pages.qml_instances.open_folder', return_value=True) as opened:
            self.click_ui(page, 'instance-folder-1.20.1')
        opened.assert_called_once_with(str(self.game_dir / 'versions/1.20.1'))
        self.click_ui(page, 'instance-settings-1.20.1')
        self.check(self.window.version_page.stack.currentWidget() is not page,
                   'instance settings opens from its real row button')
        self.screenshot_ui('instance-settings')
        page = self.open_instances()
        empty = self.directory / 'new-game-directory'
        empty.mkdir()
        with patch('ui.pages.qml_instances.QFileDialog.getExistingDirectory', return_value=str(empty)):
            self.click_ui(page, 'instance-add-directory')
        self.check(self.manager.get_setting('minecraft.directory.enable') == str(empty),
                   'added directory becomes active')
        self.check(not page.controller.view['versions'], 'empty directory shows no stale instances')
        self.screenshot_ui('instance-empty-directory')
        self.navigate('launcher-nav-home')
        self.check(self.window.started_page.controller.view['launchTitle'] == '选择游戏'
                   and not self.window.launcher.minecraft_version,
                   'Home has no stale launch target after selecting an empty directory')
        page = self.open_instances()
        self.click_ui(page, 'instance-directory-' + str(self.game_dir))
        self.check(len(page.controller.view['versions']) == 3, 'switch restores real directory scan')
        self.check(self.manager.get_setting('minecraft.version.enable') in ('1.20.1', '1.21.8'),
                   'switch chooses an installed version')
        self.screenshot_ui('instance-directory-restored')
        self.click_ui(page, 'instance-install-game')
        self.check(self.window.current_tab == 1, 'install button opens game downloads')
        self.assert_no_qml_errors()
        self.finish_test()

    def test_instance_delete_cancel_confirm_and_last_version(self):
        page = self.open_instances()
        self.click_ui(page, 'instance-delete-1.20.1')
        dialog = page.controller._delete_dialog
        self.screenshot_ui('instance-delete-confirmation', dialog)
        self.click_ui(dialog.host, 'dialog-action-0')
        self.check((self.game_dir / 'versions/1.20.1').is_dir(), 'cancel preserves game files')
        # All targets were created by this case; no user game directory is used.
        for identity in ('1.20.1', '1.21.8', '长名称测试-' + 'instance-' * 6):
            self.click_ui(page, 'instance-row-' + identity)
            self.click_ui(page, 'instance-delete-' + identity)
            dialog = page.controller._delete_dialog
            self.click_ui(dialog.host, 'dialog-action-1')
            self.wait_for(lambda: page.controller._delete_worker is None
                          and page.controller._delete_dialog is None, 'selected instance deletion completes')
            self.check(not (self.game_dir / 'versions' / identity).exists(),
                       'real selected instance directory removed')
            self.check(identity not in [row['version'] for row in page.controller.view['versions']],
                       'deleted instance disappears from the rendered model')
            self.navigate('launcher-nav-home')
            selected = self.manager.get_setting('minecraft.version.enable')
            remaining = page.controller.view['versions']
            self.check(selected != identity and (selected in [row['version'] for row in remaining]
                       if remaining else not selected),
                       'Home launch target falls back to an installed version after each deletion')
            self.check(self.window.started_page.controller.view['launchSubtitle'] == (selected or '请下载或导入游戏')
                       and (bool(selected) or self.window.started_page.controller.view['launchTitle'] == '选择游戏'),
                       'Home renders the current target immediately after each deletion')
            page = self.open_instances()
        self.check(not self.manager.get_setting('minecraft.version.enable'),
                   'last deletion clears selected version')
        self.screenshot_ui('instance-all-deleted')
        self.navigate('launcher-nav-home')
        self.check(self.window.started_page.controller.view['launchTitle'] == '选择游戏',
                   'home safely offers version selection after last deletion')
        self.screenshot_ui('home-after-last-instance-delete')
        self.assert_no_qml_errors()
        self.finish_test()


class ClientUiUpdateTests(ClientUiAcceptanceCase):
    """Click update dialogs while the real downloader reads loopback HTTP."""

    def setUp(self):
        super().setUp()
        from core import update_client
        from launcher_update_ui_fixtures import LauncherUpdateUiFixtures
        import ui.launcher_updates as updater

        self.update_http = LauncherUpdateUiFixtures()
        self.addCleanup(self.update_http.close)
        self._patch(patch.object(update_client.urllib.request, "urlopen", self.update_http.urlopen))
        self._patch(patch.object(update_client.urllib.request, "build_opener", self.update_http.build_opener))
        self._patch(patch.object(updater.platform, "system", return_value="Windows"))
        self._patch(patch.object(update_client, "platform_id", return_value="windows-x64"))
        self._patch(patch.object(updater.sys, "argv", [str(self.directory / "Buggcraft.exe")]))
        self.installed = self.directory / "Buggcraft.exe"
        self.installed.write_bytes(b"installed launcher must survive failed updates")
        self.install_patch = patch.object(updater, "apply_update")
        self.install = self.install_patch.start()
        self.addCleanup(self.install_patch.stop)
        # Never execute a fixture package or replace the test runner. The real
        # parser, download worker, progress and verification remain active.
        self.open_page_patch = patch.object(updater.QDesktopServices, "openUrl")
        self.open_page = self.open_page_patch.start()
        self.addCleanup(self.open_page_patch.stop)
        self.update = updater.LauncherUpdateController(
            self.window, Mock(), ROOT / "resources", packaged=True)
        self.window.launcher_updates = self.update
        self.window.settings_page.general_page.controller.bind_updates(self.update)

    def tearDown(self):
        self.update_http.release_download.set()
        self.update.shutdown()
        (self.output / "update-requests.json").write_text(
            json.dumps(self.update_http.requests, indent=2), encoding="utf-8")
        super().tearDown()

    def open_update_settings(self):
        self.navigate("launcher-nav-settings")
        page = self.window.settings_page.general_page
        page.ensure_loaded()
        page.quick.rootObject().revealTutorialTarget("setting-group-settings.general.update")
        self.pause_ui()
        return page

    def action(self, label):
        dialog = self.update.dialog
        self.check(dialog is not None and dialog.isVisible(), "update dialog visible: " + label)
        index = dialog.controller.actions.index(label)
        self.click_ui(dialog, "update-action-" + str(index))

    def open_offer(self):
        page = self.open_update_settings()
        self.click_ui(page, "launcher-check-updates")
        self.wait_for(lambda: not self.update.busy and self.update.dialog is not None,
                      "manual check opens update offer")
        self.check(self.item(self.update.dialog, "update-new-version").property("text") == "9.9.9",
                   "release version rendered")
        self.check(self.item(self.update.dialog, "update-current-version").property("text") == self.update.version,
                   "installed version rendered")
        return page

    def wait_for_download(self):
        self.wait_for(lambda: not self.update.busy, "update download worker completes")
        self.check(not self.update.workers, "no update worker leaked")

    def assert_installed(self):
        self.install.assert_called_once()
        package = self.install.call_args.args[0]
        self.check(package.read_bytes() == self.update_http.payload,
                   "only the verified package reaches installation handoff")
        self.update.app.quit.assert_called_once()
        self.check("重启" in self.update.status, "successful handoff status visible")

    def assert_failed_safely(self):
        self.install.assert_not_called()
        self.update.app.quit.assert_not_called()
        self.check(self.installed.read_bytes() == b"installed launcher must survive failed updates",
                   "installed executable retained on failure")
        self.check(not list(self.directory.glob(".buggcraft-update-*")),
                   "partial and corrupt packages cleaned up")
        self.check(self.item(self.update.dialog, "update-title").property("text") == "更新未完成",
                   "download error dialog visible")

    def test_update_check_failure_and_channel_retry(self):
        page = self.open_update_settings()
        self.update_http.check_failure = True
        self.click_ui(page, "launcher-update-channel-development")
        self.wait_for(lambda: not self.update.busy and self.update.dialog is not None,
                      "failed beta check opens error dialog")
        self.check("失败" in self.item(page, "launcher-update-status").property("text"),
                   "check failure visible in settings")
        self.screenshot_ui("update-check-failed", self.update.dialog)
        self.update_http.check_failure = False
        self.update_http.available = False
        self.action("重试")
        self.wait_for(lambda: not self.update.busy, "retry check completes")
        self.check("最新可用版本" in self.item(page, "launcher-update-status").property("text"),
                   "retry shows latest beta status")
        self.check(self.manager.get_setting("settings.general.update") == "development",
                   "selected update channel persisted")
        self.check(all(item["query"].get("channel") == ["beta"] for item in self.update_http.requests),
                   "initial check and retry both request selected beta channel")
        self.click_ui(page, "launcher-check-updates")
        self.wait_for(lambda: not self.update.busy, "manual latest check completes")
        self.screenshot_ui("update-settings-latest", page)
        self.assert_no_qml_errors()
        self.finish_test()

    def test_update_reminder_and_manual_check_reopens_offer(self):
        page = self.open_offer()
        dialog = self.update.dialog
        self.screenshot_ui("update-offer", dialog)
        self.action("稍后提醒")
        self.wait_for(lambda: self.update.dialog is None, "offer closes after reminder")
        reminder = self.manager.get_setting("settings.general.update_reminder")
        self.check(reminder["version"] == "9.9.9", "reminder saved for correct version")
        from config.settings import SettingsManager
        restored = SettingsManager(self.directory / "config")
        self.check(restored.get_setting("settings.general.update_reminder") == reminder,
                   "reminder persists on disk")
        self.click_ui(page, "launcher-check-updates")
        self.wait_for(lambda: not self.update.busy and self.update.dialog is not None,
                      "manual check bypasses reminder")
        self.screenshot_ui("update-manual-offer", self.update.dialog)
        self.click_ui(self.update.dialog, "update-close")
        self.wait_for(lambda: self.update.dialog is None, "close button dismisses offer")
        self.check(self.update_http.ticket_count == 0, "closing offer never starts download")
        self.install.assert_not_called()
        self.assert_no_qml_errors()
        self.finish_test()

    def test_update_ticket_progress_background_and_verified_install(self):
        self.update_http.pause_download = True
        page = self.open_offer()
        self.action("立即更新")
        self.wait_for(lambda: self.update_http.download_paused.is_set() and self.update.dialog is not None
                      and self.update.dialog.controller.progress > 0,
                      "streaming download exposes intermediate progress")
        dialog = self.update.dialog
        self.check(0 < self.item(dialog, "update-progress").property("value") < 1,
                   "rendered progress between zero and complete")
        self.check(not self.item(dialog, "update-close").isEnabled(), "close disabled while downloading")
        self.check(not self.item(page, "launcher-check-updates").isEnabled(),
                   "duplicate check disabled while downloading")
        self.key_ui(dialog, Qt.Key_Escape, "update-download-escape")
        self.check(dialog.isVisible(), "Escape cannot destroy active download dialog")
        self.screenshot_ui("update-downloading", dialog)
        self.action("后台下载")
        self.check(not dialog.isVisible() and self.window.isVisible(),
                   "background action hides only update dialog")
        self.install.assert_not_called()
        self.update.app.quit.assert_not_called()
        self.update_http.release_download.set()
        self.wait_for_download()
        self.assert_installed()
        self.check(self.update_http.ticket_count == 1, "one fresh download ticket requested")
        self.check(self.update_http.count(self.update_http.asset_path) == 0,
                   "successful ticket download does not fetch stable fallback")
        self.screenshot_ui("update-verified-handoff", page)
        self.assert_no_qml_errors()
        self.finish_test()

    def test_update_download_failure_retry_gets_new_ticket(self):
        self.update_http.cdn_failure = self.update_http.stable_failure = True
        self.open_offer()
        self.action("立即更新")
        self.wait_for_download()
        self.assert_failed_safely()
        self.check("失败" in self.update.status, "download failure status visible")
        self.screenshot_ui("update-download-failed", self.update.dialog)
        self.update_http.cdn_failure = self.update_http.stable_failure = False
        self.action("重试")
        self.wait_for_download()
        self.assert_installed()
        self.check(self.update_http.ticket_count == 2, "retry obtains fresh ticket")
        cdn_requests = [item for item in self.update_http.requests if item["path"] == "/cdn/Buggcraft.exe"]
        self.check([item["query"]["ticket"] for item in cdn_requests] == [["1"], ["2"]],
                   "retry uses new CDN URL instead of stale ticket")
        self.assert_no_qml_errors()
        self.finish_test()

    def test_update_cdn_failure_falls_back_to_same_origin(self):
        self.update_http.cdn_failure = True
        page = self.open_offer()
        self.action("立即更新")
        self.wait_for_download()
        self.assert_installed()
        self.check(self.update_http.count("/cdn/Buggcraft.exe") == 1,
                   "CDN attempted before stable fallback")
        self.check(self.update_http.count(self.update_http.asset_path) == 1,
                   "stable same-origin fallback downloaded")
        self.check(self.update.dialog is None, "successful fallback shows no error dialog")
        self.screenshot_ui("update-cdn-fallback-verified", page)
        self.assert_no_qml_errors()
        self.finish_test()

    def test_update_hash_failure_download_page_and_close(self):
        self.update_http.corrupt = True
        page = self.open_offer()
        self.action("立即更新")
        self.wait_for_download()
        self.assert_failed_safely()
        self.check("SHA-256" in self.update.dialog.controller.detail,
                   "verification failure preserves exact reason")
        self.screenshot_ui("update-hash-failed", self.update.dialog)
        self.action("官网下载")
        self.open_page.assert_called_once()
        self.check(self.open_page.call_args.args[0].toString() == "https://download.bugg.icu/",
                   "fallback opens official release page")
        self.click_ui(page, "launcher-check-updates")
        self.wait_for(lambda: not self.update.busy and self.update.dialog is not None,
                      "manual check reopens offer after verification failure")
        self.action("立即更新")
        self.wait_for_download()
        self.assert_failed_safely()
        self.action("关闭")
        self.wait_for(lambda: self.update.dialog is None, "error close returns to settings")
        self.check(self.window.isVisible(), "launcher remains usable after closing error")
        self.open_page.assert_called_once()
        self.assert_no_qml_errors()
        self.finish_test()

    def test_update_without_ticket_downloads_same_origin(self):
        self.update_http.include_ticket = False
        page = self.open_offer()
        self.action("立即更新")
        self.wait_for_download()
        self.assert_installed()
        self.check(self.update_http.ticket_count == 0, "legacy manifest uses no ticket")
        self.check(self.update_http.count(self.update_http.asset_path) == 1,
                   "legacy stable asset URL downloaded")
        self.check(all(item["userAgent"] == "Buggcraft-Launcher" for item in self.update_http.requests),
                   "same-origin compatibility User-Agent retained")
        self.screenshot_ui("update-legacy-url-verified", page)
        self.assert_no_qml_errors()
        self.finish_test()


class ClientUiDownloadTests(ClientUiAcceptanceCase):
    def test_client_ui_download_and_modpack_import(self):
        # The shared fixture starts with this instance installed. Exercise a
        # fresh download instead of triggering the duplicate-name dialog.
        shutil.rmtree(self.game_dir / 'versions' / '1.21.8', ignore_errors=True)
        self.navigate("launcher-nav-download")
        page = self.window.download_page.games_page
        page.ensure_loaded()
        # The catalogue response is a local fixture.  Seed it through the
        # production controller before sending the search and click events.
        page.controller.versions = [
            {"id": "1.21.8", "type": "release", "releaseTime": "2026-01-01"},
        ]
        page.controller.changed.emit()
        self.screenshot_ui("downloads")
        self.text_ui(page, "catalogue-query", "1.21")
        self.key_ui(page, Qt.Key_Return, "catalogue-search")
        self.check(self.item(page, "install-1.21.8") is not None,
                   "game version result rendered")
        self.click_ui(page, "install-1.21.8")
        self.screenshot_ui("game-install")
        self.click_ui(page, "install-selected-game")
        tasks = self.window.download_page.tasks_page
        self.wait_for(lambda: bool(tasks._tasks) and
                      tasks._tasks[0].get("state") not in tasks.ACTIVE,
                      "game download task completed", timeout=20000)
        self.check(tasks._tasks[0].get("state") != "失败", "game download succeeded")
        self.check((self.game_dir / "versions" / "1.21.8" / "1.21.8.jar").is_file(),
                   "game archive installed")
        self.screenshot_ui("game-download-complete", tasks)

        self.window.download_page.on_download_clicked()
        self.window.download_page.open_content("modpack", "import")
        content = self.window.download_page.content_page
        content.host.ensure_loaded()
        self.wait_for(lambda: content.controller.view == "import", "mrpack import view opened")
        self.click_ui(content, "choose-pack-file")
        self.text_ui(content, "pack-instance-name", "ui-pytest-import")
        self.click_ui(content, "start-pack-import")
        self.wait_for(lambda: bool(tasks._tasks) and
                      tasks._tasks[0].get("state") not in tasks.ACTIVE,
                      "mrpack import task completed", timeout=25000)
        self.check(tasks._tasks[0].get("state") != "失败", "mrpack import succeeded")
        self.check((self.game_dir / "versions" / "ui-pytest-import" /
                    "config" / "ui-acceptance.json").is_file(),
                   "mrpack override installed")
        self.screenshot_ui("mrpack-import-complete", tasks)
        self.finish_test()


class ClientUiMultiplayerTests(ClientUiAcceptanceCase):
    def test_client_ui_multiplayer_and_social_tabs(self):
        page = self.window.started_page
        page.ensure_loaded()
        self.click_ui(page, "open-lobby-home")
        self.pause_ui()
        dialog = page._multiplayer_dialog
        self.assertIsNotNone(dialog)
        backend = dialog.backend
        backend.patch(
            nodes=[{"title": "UI 测试节点", "path": "ui-fixture-node",
                    "personalCode": True, "codeExpired": False}],
            nodeIndex=0, nodeAvailable=True, nodeLatencyMs=12, rooms=[],
        )
        invitation_id = "3" * 32
        backend.seen_friend_invitations.add(invitation_id)
        backend.apply_social_state({
            "account": "a" * 32 + "." + "b" * 32,
            "username": "UITest",
            "friends": [{"account": "c" * 32 + "." + "d" * 32,
                          "username": "Player_01", "online": True,
                          "room": {"id": "e" * 32, "title": "测试房间",
                                   "role": "host", "availability": "ready",
                                   "can_request": True}}],
            "requests": [{"account": "f" * 32 + "." + "0" * 32,
                           "username": "Request_01", "incoming": True}],
            "invitations": [{"account": "1" * 32 + "." + "2" * 32,
                              "username": "Invite_01", "id": invitation_id}],
            "joinRequests": [{"account": "5" * 32 + "." + "6" * 32,
                               "username": "Join_01", "id": "7" * 32,
                               "room": "8" * 32, "incoming": True,
                               "status": "pending"}],
            "capabilities": {"room_presence": True, "join_requests": True,
                              "friend_code": True},
        })
        self.pause_ui()
        self.screenshot_ui("multiplayer-hall", dialog)
        self.click_ui(dialog, "node-picker")
        self.key_ui(dialog, Qt.Key_Escape, "node-picker-escape")
        self.click_ui(dialog, "open-friends-window")
        friends = dialog.friends_window
        self.wait_for(lambda: friends is not None and friends.isVisible(),
                      "friends window visible")
        self.screenshot_ui("friends", friends)
        self.click_ui(friends, "friend-search")
        self.text_ui(friends, "friend-search", "Player_01")
        self.click_ui(friends, "friend-filter-online")
        self.click_ui(friends, "friends-tab-1")
        self.check(self.item(friends, "accept-friend") is not None,
                   "friend request action rendered")
        self.screenshot_ui("friend-requests", friends)
        self.click_ui(friends, "friends-tab-2")
        self.check(self.item(friends, "join-friend-invite") is not None,
                   "friend invitation action rendered")
        self.screenshot_ui("friend-invitations", friends)
        self.click_ui(friends, "friends-tab-3")
        self.check(self.item(friends, "accept-join-request") is not None,
                   "join request action rendered")
        self.screenshot_ui("join-requests", friends)
        self.key_ui(friends, Qt.Key_Escape, "friends-escape")
        dialog.close()
        self.finish_test()

