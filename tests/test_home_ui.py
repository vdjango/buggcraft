"""Home checklist replay using shipping QML, isolated data and real Qt events.

Authentication responses and Minecraft's command are local fixtures. Child
processes, launcher workers, settings, downloads and dialogs remain real.
This module never claims browser authorization or the Minecraft main menu.
"""
import base64
import json
from pathlib import Path
import sys
from unittest.mock import patch

from PySide6.QtCore import QPoint, QTimer, QUrl
from PySide6.QtQuickWidgets import QQuickWidget
import shiboken6

from _qml_test_support import QTest, Qt, ROOT, qt_mouse_click, qt_mouse_move
from test_client_ui_acceptance import ClientUiAcceptanceCase as _HomeCase


def account(username="UI_Premium", identity="a", expires=4102444800):
    payload = base64.urlsafe_b64encode(json.dumps({"exp": expires}).encode()).decode().rstrip("=")
    return username, dict(type="online", uuid=identity * 32,
                          token="e30." + payload + ".ui-fixture",
                          refresh_token="local-fixture-refresh", expires_at=expires)


class HomeChecklistUiTests(_HomeCase):
    def tearDown(self):
        # Workers must finish before the owning QWidget and temporary files go.
        if hasattr(self, "window"):
            sessions = self.window.started_page.launcher
            for record in list(sessions.sessions):
                sessions.selected_id = record["id"]
                sessions.stop(force=True)
            self.wait_for(lambda: not sessions._sessions, "all child workers finish before window teardown")
        super().tearDown()

    def prepare_game_process(self):
        script = self.directory / "home-game-fixture.py"
        script.write_text('import sys\nprint("HOME_UI_READY", flush=True)\n'
                          'value = sys.stdin.readline().strip()\n'
                          'if value == "crash":\n'
                          '    print("HOME_UI_CRASH", flush=True)\n'
                          '    sys.exit(17)\n', encoding="utf-8")
        self.manager.set_setting("java.path", sys.executable)
        self.manager.set_setting("minecraft.auto_allocate_memory", False)
        self.manager.set_setting("memory.allocation", 1024)
        self.manager.set_version_setting("launcher.visibility", "游戏启动后保持不变")
        self._patch(patch("config.javafinder.JavaPathFinder._get_java_version",
                          return_value=("Java 21 fixture", (21, 0, 1))))
        self._patch(patch("core.launcher.verified_installation", return_value=True))
        self._patch(patch("core.launcher.minecraft_launcher_lib.command.get_minecraft_command",
                          side_effect=lambda *_a: [sys.executable, str(script)]))
        return self.window.started_page.launcher

    def launch_child(self, sessions, count=1):
        self.click_ui(self.window.started_page, "launch-game")
        # The full release matrix runs several Qt/process suites in one job.
        # Keep the functional assertion unchanged while allowing slow hosted
        # runners to finish preparing the real child worker.
        self.wait_for(lambda: len(sessions.sessions) == count
                      and all(row["phase"] == "running" for row in sessions.sessions),
                      "Home starts independent child processes: " + str(count),
                      timeout=60000)
        return sessions.selected["launcher"].process

    def exit_child(self, process, *, crash=False):
        self.record("fixtureProcessExit", str(process.pid), "crash" if crash else "normal")
        process.stdin.write(b"crash\n" if crash else b"exit\n")
        process.stdin.flush()

    def offline_login(self, name="Home_Player", enter=False):
        home = self.window.started_page
        self.click_ui(home, "navigation-option-0")
        if home.controller.view["authenticated"]:
            self.click_ui(home, "switch-account")
        self.text_ui(home, "offline-username", name)
        if enter:
            self.key_ui(home, Qt.Key_Return, "offline-username-enter")
        else:
            self.click_ui(home, "offline-login-confirm")
        self.check(home.auth_manager.offline.username == name,
                   "offline login binds the submitted player")

    def restart(self):
        """Recreate the window and settings from disk, without user files."""
        import config.settings as settings
        from windows.main_window import MinecraftLauncher

        self.manager.save_settings()
        self.window.close()
        self.wait_for(lambda: not self.window.isVisible(), "old window closes before restart")
        for quick in self.window.findChildren(QQuickWidget):
            if shiboken6.isValid(quick):
                quick.setSource(QUrl())
                shiboken6.delete(quick)
        self.window.deleteLater()
        self.pause_ui()
        self.manager = settings.SettingsManager(self.directory / "config")
        settings._settings_manager_instance = self.manager
        self.window = MinecraftLauncher(str(ROOT), str(self.directory / "cache"),
                                        str(self.directory / "config"), str(ROOT / "resources"))
        self.record("restart", "launcher", "new settings manager reads persisted temporary files")
        self.window.show()
        self.pause_ui()

    def modal_login(self, responses):
        """Keep the real modal loop; substitute only remote auth responses."""
        home = self.window.started_page
        dialog = home.login_dialog
        errors, remaining = [], list(responses)
        timer = QTimer(dialog)
        timer.setSingleShot(True)

        def timeout():
            errors.append(AssertionError("modal authentication did not finish"))
            dialog.reject()

        def respond():
            try:
                response = remaining.pop(0)
                dialog.auth.signals.device_code.emit("HOME-CODE", "https://microsoft.com/devicelogin")
                self.pause_ui()
                self.check(dialog.isVisible(), "login modal is visible")
                if isinstance(response, tuple):
                    dialog.auth.signals.success.emit(*response)
                elif response in ("cancel", "escape"):
                    if response == "cancel":
                        self.click_ui(dialog, "dialog-action-1")
                    else:
                        self.key_ui(dialog, Qt.Key_Escape, "login-dialog-escape")
                else:
                    dialog.auth.signals.failure.emit(response)
                    self.pause_ui()
                    self.check(self.item(dialog, "dialog-message").property("text") == response
                               and not home.auth_manager.is_authenticated(),
                               "authentication error is visible and does not sign in")
                    self.screenshot_ui("login-error-" + str(len(remaining)), dialog)
                    self.click_ui(dialog, "dialog-action-0")
            except BaseException as error:
                errors.append(error)
                dialog.reject()

        timer.timeout.connect(timeout)
        try:
            with patch.object(dialog.auth, "start_login", side_effect=respond) as login:
                timer.start(12000)
                self.click_ui(home, "online-login")
                self.assertEqual(login.call_count, len(responses))
        finally:
            timer.stop()
            timer.deleteLater()
        if errors:
            raise errors[0]
        self.check(not remaining and not dialog.isVisible(), "all modal login steps finish")

    def social(self, *, empty=False, notifications=False):
        home = self.window.started_page
        dialog = home._ensure_multiplayer_dialog()
        invitation_id = "3" * 32
        dialog.backend.seen_friend_invitations.add(invitation_id)
        dialog.backend.apply_social_state({
            "account": "a" * 32 + "." + "b" * 32, "username": "UI_Home",
            "friends": [] if empty else [
                {"account": "c" * 32 + "." + "d" * 32, "username": "Online_Player", "online": True},
                {"account": "e" * 32 + "." + "f" * 32, "username": "Offline_Player", "online": False}],
            "requests": [{"id": "0" * 32, "account": "1" * 32 + "." + "2" * 32,
                          "username": "Request_Player", "incoming": True}] if notifications else [],
            "invitations": [{"account": "4" * 32 + "." + "5" * 32,
                            "username": "Invite_Player", "id": invitation_id}] if notifications else [],
            "joinRequests": [{"account": "6" * 32 + "." + "7" * 32,
                             "username": "Join_Player", "id": "8" * 32, "room": "9" * 32,
                             "incoming": True, "status": "pending"}] if notifications else [],
            "capabilities": {"room_presence": True, "join_requests": True, "friend_code": True},
        })
        self.pause_ui()
        return dialog

    def test_restart_restores_offline_role_directory_and_selected_version(self):
        self.offline_login(enter=True)
        self.click_ui(self.window.title_bar, "version-picker")
        self.click_ui(self.window.title_bar._picker.host, "choice-option-1")
        selected = self.window.launcher.minecraft_version
        self.restart()
        home = self.window.started_page
        self.check(home.auth_manager.offline.username == "Home_Player"
                   and home.auth_manager.is_authenticated(), "restart restores the saved offline role")
        self.check(home.launcher.minecraft_version == selected
                   and Path(home.launcher.minecraft_directory) == self.game_dir,
                   "restart restores the saved game directory and selected version")
        self.check(self.item(home, "home-username").property("text") == "Home_Player"
                   and self.item(home, "home-launch-subtitle").property("text") == selected,
                   "restored account and instance render on Home")
        self.screenshot_ui("home-restored")
        self.assert_no_qml_errors()
        self.finish_test()

    def test_empty_home_installation_populates_version_picker_and_instances(self):
        empty = self.directory / "empty-games"
        empty.mkdir()
        self.manager.set_setting("minecraft.directory.enable", str(empty))
        self.manager.set_setting("minecraft.directory.installed", [str(empty)])
        self.manager.set_setting("minecraft.version.enable", None)
        self.restart()
        home = self.window.started_page
        self.check(not home.auth_manager.is_authenticated()
                   and self.item(home, "offline-username").isVisible()
                   and self.item(home, "home-launch-title").property("text") == "选择游戏",
                   "empty home offers login and game selection")
        self.click_ui(self.window.title_bar, "version-picker")
        self.check(not self.window.title_bar.controller.versions, "version popup has no phantom installation")
        self.key_ui(self.window.title_bar._picker, Qt.Key_Escape, "empty-version-escape")
        self.click_ui(home, "launch-game")
        self.check(self.window.current_tab == 3, "missing-version launch opens instance management")
        instances = self.window.version_page.versions_page
        self.click_ui(instances, "instance-install-game")
        self.check(self.window.current_tab == 1, "empty instance page offers game download")
        games = self.window.download_page.games_page
        games.controller.versions = [dict(id="1.21.8", type="release", releaseTime="2026-01-01")]
        games.controller.changed.emit()
        self.pause_ui()
        self.click_ui(games, "install-1.21.8")
        self.click_ui(games, "install-selected-game")
        tasks = self.window.download_page.tasks_page
        self.wait_for(lambda: bool(tasks._tasks) and tasks._tasks[0].get("state") not in tasks.ACTIVE,
                      "fixture game installation completes", timeout=20000)
        self.check(tasks._tasks[0]["state"] != "失败"
                   and (empty / "versions/1.21.8/1.21.8.jar").is_file(),
                   "production downloader writes the game archive in the chosen directory")
        self.navigate("instances-button")
        self.click_ui(instances, "instance-row-1.21.8")
        self.navigate("launcher-nav-home")
        self.click_ui(self.window.title_bar, "version-picker")
        self.check("1.21.8" in self.window.title_bar.controller.versions,
                   "installed version appears in the header popup")
        self.key_ui(self.window.title_bar._picker, Qt.Key_Escape, "installed-version-escape")
        self.check(self.item(home, "home-launch-subtitle").property("text") == "1.21.8",
                   "home displays the newly installed target")
        self.screenshot_ui("home-after-install")
        self.assert_no_qml_errors()
        self.finish_test()

    def test_version_round_trip_keyboard_escape_and_outside_click(self):
        header = self.window.title_bar
        original = header.controller.selected
        self.click_ui(header, "version-picker")
        self.key_ui(header._picker, Qt.Key_Down, "version-down")
        self.key_ui(header._picker, Qt.Key_Up, "version-up")
        self.check(header.controller.picker_index == 0, "Up restores the first highlighted row")
        self.key_ui(header._picker, Qt.Key_Down, "version-down-again")
        expected = header.controller.versions[1]
        self.key_ui(header._picker, Qt.Key_Return, "version-confirm")
        self.check(header.controller.selected == expected, "Down and Return select another version")
        self.click_ui(header, "version-picker")
        self.key_ui(header._picker, Qt.Key_Down, "version-down-cancel")
        self.key_ui(header._picker, Qt.Key_Escape, "version-cancel")
        self.check(header.controller.selected == expected and not header._picker.isVisible(),
                   "Escape dismisses without changing the selected version")
        self.click_ui(header, "version-picker")
        original_index = header.controller.versions.index(original)
        self.click_ui(header._picker.host, "choice-option-" + str(original_index))
        self.check(header.controller.selected == original, "mouse selection switches back to the original version")
        self.click_ui(header, "version-picker")
        self.record("mouseClick", "outside-version-popup", "Home content")
        # A popup owns the mouse grab: native outside clicks are delivered to
        # it using coordinates outside its bounds, rather than to the owner.
        outside = header._picker.mapFromGlobal(self.window.mapToGlobal(
            QPoint(self.window.width() // 2, self.window.height() - 20)))
        self.assertFalse(header._picker.rect().contains(outside))
        qt_mouse_click(header._picker, outside)
        self.pause_ui()
        self.check(not header._picker.isVisible() and header.controller.selected == original,
                   "clicking outside dismisses the popup without changing the selection")
        self.screenshot_ui("home-version-round-trip")
        self.assert_no_qml_errors()
        self.finish_test()

    def test_lobby_empty_add_node_switch_search_and_return(self):
        from dataclasses import replace
        from hookup.nodes import profile_data, save_json
        from test_friend_entry_regression import personal_profile

        home = self.window.started_page
        self.check(not self.item(home, "open-friends-home").isVisible(),
                   "without a social node Home does not offer a nonfunctional friends entry")
        self.click_ui(home, "open-lobby-home")
        dialog = home._multiplayer_dialog
        backend = dialog.backend
        self.check(not backend.view["nodes"] and backend.view["nodeIndex"] == -1
                   and self.item(dialog, "empty-add-node").isVisible(),
                   "a launcher without nodes offers the explicit add-node entry")
        self.screenshot_ui("home-lobby-without-node", dialog)
        self.click_ui(dialog, "empty-add-node")
        profile = personal_profile()
        self.text_ui(dialog, "node-web-address", 'community.example')
        self.click_ui(dialog, "login-official-device")
        self.check(backend.view["deviceLoginBusy"], "node login waits for browser authorization")
        backend.act('cancelDeviceLogin', {})
        # The device approval handshake has dedicated tests; supply its verified
        # profile here to exercise persistence and the Home/lobby round trip.
        backend.save_verified_node(profile)
        self.pause_ui()
        self.check(len(backend.view["nodes"]) == 1 and not backend.view["error"],
                   "verified device profile is saved by the production node store")
        self.click_ui(dialog, "back-hall")
        second = self.directory / "second-home-node.json"
        save_json(second, profile_data(replace(profile, server_port=3334)))
        backend.store.add_node(str(second))
        backend.reload_store()
        backend.patch(nodeAvailable=True, loading=False)
        self.pause_ui()
        self.click_ui(dialog, "node-picker")
        self.check(self.item(dialog, "node-picker").property("tutorialPopupVisible"),
                   "node selector opens before keyboard selection")
        qt_mouse_move(dialog.quick, QPoint(3, 3))
        self.pause_ui()
        self.key_ui(dialog, Qt.Key_Home, "node-list-first")
        self.key_ui(dialog, Qt.Key_Down, "node-list-second")
        self.check(self.item(dialog, "node-picker").property("highlightedIndex") == 1,
                   "node keyboard selection highlights the second profile")
        self.key_ui(dialog, Qt.Key_Return, "node-list-confirm")
        self.check(backend.node_path == str(second) and backend.view["nodeIndex"] == 1,
                   "node selection changes the actual selected profile")
        backend.patch(nodeAvailable=True, loading=False, rooms=[], roomError="")
        self.pause_ui()
        self.check(self.item(dialog, "rooms-empty").property("text") == "暂时没有开放房间",
                   "selected node renders the room-list empty result")
        self.text_ui(dialog, "room-search", "Home_Room")
        self.check(backend.view["roomQuery"] == "Home_Room", "room search reaches the production controller")
        self.text_ui(dialog, "room-search", "")
        self.wait_for(lambda: not backend.room_search_timer.isActive() and backend.view["loading"],
                      "clearing room search dispatches its debounced directory request")
        backend.finish("rooms:" + backend.room_generation + ":0",
                       dict(rooms=[], next=None, total=0, node_latency_ms=12), None)
        self.pause_ui()
        self.check(backend.view["nodeAvailable"] and not backend.view["loading"],
                   "successful search response restores node actions")
        for entry, expected in (("open-create", "create"), ("open-join", "join")):
            backend.patch(nodeAvailable=True, loading=False)
            self.pause_ui()
            self.click_ui(dialog, entry)
            self.check(backend.view["page"] == expected, "Home lobby opens " + expected)
            self.screenshot_ui("home-lobby-" + expected, dialog)
            self.click_ui(dialog, "back-hall")
            self.check(backend.view["page"] == "hall", "room form returns to the hall")
        self.click_ui(dialog, "close-window")
        self.check(not dialog.isVisible() and self.window.isVisible(), "closing the hall returns to Home")
        self.click_ui(home, "open-lobby-home")
        self.check(dialog.isVisible() and backend.view["page"] == "hall", "Home reopens the existing hall")
        self.key_ui(dialog, Qt.Key_Escape, "reopened-hall-escape")
        self.assert_no_qml_errors()
        self.finish_test()

    def test_instance_settings_remain_independent_after_switching_instances(self):
        self.navigate("instances-button")
        versions = self.window.version_page
        page = versions.versions_page
        self.click_ui(page, "instance-settings-1.21.8")
        settings = versions.settings_page
        self.click_ui(settings, "setting-toggle-instance.enable")
        self.click_ui(settings, "setting-option-minecraft.isolation-1")
        self.check(self.manager.get_version_setting_enable()
                   and self.manager.get_minecraft_isolation_directory() == str(self.game_dir / "versions/1.21.8"),
                   "the first instance saves its independent directory preference")
        self.click_ui(versions.tab_buttons_widget, "navigation-option-0")
        self.click_ui(page, "instance-settings-1.20.1")
        self.check(not self.manager.get_version_setting_enable()
                   and not self.item(settings, "setting-option-minecraft.isolation-1").isEnabled(),
                   "another instance still inherits settings after switching through the list")
        self.click_ui(settings, "setting-toggle-instance.enable")
        self.click_ui(settings, "setting-option-minecraft.isolation-0")
        self.check(self.manager.get_minecraft_isolation_directory() == str(self.game_dir),
                   "the second instance can save a different independent directory preference")
        self.screenshot_ui("home-second-instance-settings")
        self.click_ui(versions.tab_buttons_widget, "navigation-option-0")
        self.click_ui(page, "instance-settings-1.21.8")
        self.check(self.manager.get_version_setting_enable()
                   and self.manager.get_minecraft_isolation_directory() == str(self.game_dir / "versions/1.21.8"),
                   "returning to the first instance preserves its own saved override")
        from config.settings import SettingsManager
        restored = SettingsManager(self.directory / "config")
        self.check(restored.get_version_setting_enable()
                   and restored.get_minecraft_isolation_directory() == str(self.game_dir / "versions/1.21.8"),
                   "a fresh settings manager reads the selected instance override from disk")
        self.navigate("launcher-nav-home")
        self.check(self.window.started_page.controller.view["launchSubtitle"] == "1.21.8",
                   "returning Home keeps the selected instance as the launch target")
        self.assert_no_qml_errors()
        self.finish_test()

    def test_instance_running_delete_guard_and_directory_confirmation(self):
        self.offline_login()
        sessions = self.prepare_game_process()
        child = self.launch_child(sessions)
        self.navigate("instances-button")
        page = self.window.version_page.versions_page
        for target, message in (("instance-delete-1.21.8", "请先退出此实例中运行的游戏。"),
                                ("instance-remove-directory-" + str(self.game_dir), "请先退出此目录中运行的游戏。")):
            self.click_ui(page, target)
            dialog = page.controller._delete_dialog
            self.click_ui(dialog, "dialog-action-1")
            self.check(dialog.controller.title == "删除失败" and dialog.controller.detail == message
                       and child.poll() is None and (self.game_dir / "versions/1.21.8").exists(),
                       "running instance and directory deletion are refused without killing the process")
            self.screenshot_ui("home-running-delete-guard-" + str(len(self.actions)), dialog)
            self.click_ui(dialog, "dialog-action-0")
            self.wait_for(lambda: page.controller._delete_dialog is None, "delete guard closes")
        self.exit_child(child)
        self.wait_for(lambda: not sessions._sessions, "game exits before directory deletion")
        # Refuse to exercise destructive UI against any path outside this case.
        self.assertTrue(self.game_dir.resolve().is_relative_to(self.directory.resolve()))
        marker = self.game_dir / "home-delete-marker.txt"
        marker.write_text("temporary UI fixture", encoding="utf-8")
        for confirm in (False, True):
            self.click_ui(page, "instance-remove-directory-" + str(self.game_dir))
            dialog = page.controller._delete_dialog
            self.check("永久删除" in dialog.controller.detail, "directory confirmation describes actual deletion")
            if confirm:
                self.click_ui(dialog, "keep-game-directory")
                self.check(dialog.controller.data["keepDirectory"] == "false",
                           "explicit permanent-delete choice removes local files")
            self.screenshot_ui("home-directory-delete-" + str(confirm), dialog)
            self.click_ui(dialog, "dialog-action-1" if confirm else "dialog-action-0")
            self.wait_for(lambda: page.controller._delete_dialog is None
                          and page.controller._delete_worker is None, "directory deletion dialog finishes")
            self.check(marker.exists() != confirm, "cancel preserves files and confirmation deletes files")
        self.check(not self.game_dir.exists() and not page.controller.view["directories"]
                   and not page.controller.view["versions"], "deleted directory and instances disappear immediately")
        self.navigate("launcher-nav-home")
        self.check(self.window.started_page.controller.view["launchTitle"] == "选择游戏",
                   "deleting the only game directory restores Home's empty state")
        self.screenshot_ui("home-after-directory-deletion")
        self.assert_no_qml_errors()
        self.finish_test()

    def test_offline_empty_enter_confirmation_and_mode_round_trip(self):
        home = self.window.started_page
        for username in ("", "   "):
            self.text_ui(home, "offline-username", username)
            self.click_ui(home, "offline-login-confirm")
            self.check(not home.auth_manager.is_authenticated()
                       and self.item(home, "home-status").property("text") == "请输入用户名。",
                       "empty or whitespace username is rejected")
        self.offline_login("Enter_Player", enter=True)
        self.click_ui(home, "navigation-option-1")
        self.check(not home.auth_manager.is_authenticated()
                   and self.item(home, "online-login").isVisible(),
                   "offline identity does not authenticate the online mode")
        self.click_ui(home, "navigation-option-0")
        self.check(home.auth_manager.offline.username == "Enter_Player"
                   and self.item(home, "home-username").property("text") == "Enter_Player",
                   "switching back preserves the separate offline role")
        self.offline_login("Confirm_Player")
        self.screenshot_ui("home-login-mode-round-trip")
        self.assert_no_qml_errors()
        self.finish_test()

    def test_online_failures_retry_cancel_escape_and_switch_account(self):
        home = self.window.started_page
        self.offline_login("Kept_Offline")
        self.click_ui(home, "navigation-option-1")
        for message in ("微软授权已取消，请重新登录。", "登录码已过期，请重新登录。",
                        "无法连接微软登录服务，请检查网络后重试。", "此账号没有有效的 Minecraft Java 版角色。"):
            with self.subTest(message=message):
                self.modal_login([message, account()])
                self.check(home.auth_manager.current.username == "UI_Premium",
                           "retry after authentication failure binds the authenticated role")
                self.click_ui(home, "switch-account")
        self.modal_login(["cancel"])
        self.modal_login(["escape"])
        self.modal_login([account("Second_Premium", "b")])
        self.check(home.auth_manager.online.uuid == "b" * 32
                   and home.auth_manager.online.username == "Second_Premium"
                   and home.auth_manager.offline.username == "Kept_Offline",
                   "switching online accounts updates identity without altering the offline role")
        self.screenshot_ui("home-premium-second-account")
        self.assert_no_qml_errors()
        self.finish_test()

    def test_page_navigation_retains_input_and_sidebar_on_every_page(self):
        home = self.window.started_page
        self.text_ui(home, "offline-username", "Unsaved_Player")
        for target in ("launcher-nav-download", "launcher-nav-settings", "launcher-nav-home"):
            self.navigate(target)
            self.check(self.window.title_bar.controller.active == {"launcher-nav-download": "下载",
                       "launcher-nav-settings": "设置", "launcher-nav-home": "开始"}[target],
                       "navigation selection matches the visible page")
            for collapsed in (True, False):
                self.click_ui(self.window.title_bar, "toggle-launcher-sidebar")
                self.check(self.window.menu_collapsed == collapsed,
                           "visible sidebar button toggles on " + target)
        normal_pause, self.pause = self.pause, 0
        try:
            for _ in range(4):
                for target in ("launcher-nav-download", "launcher-nav-settings", "launcher-nav-home"):
                    self.navigate(target)
        finally:
            self.pause = normal_pause
        self.pause_ui()
        self.check(self.item(home, "offline-username").property("text") == "Unsaved_Player",
                   "page round trips preserve unsubmitted Home input")
        self.click_ui(home, "offline-username")
        self.key_ui(home, Qt.Key_Return, "login-after-page-round-trips")
        self.check(home.auth_manager.current.username == "Unsaved_Player",
                   "restored login control still responds after repeated navigation")
        self.screenshot_ui("home-navigation-input-retained")
        self.assert_no_qml_errors()
        self.finish_test()

    def test_home_friends_filters_tabs_unread_empty_and_reopen(self):
        dialog = self.social(notifications=True)
        home = self.window.started_page
        self.check(self.item(home, "home-friends-badge").property("count") > 0,
                   "Home exposes unread friend activity before opening")
        self.click_ui(home, "open-friends-home")
        friends = dialog.friends_window
        self.text_ui(friends, "friend-search", "Online_Player")
        self.check(self.item(friends, "friends-list").property("count") == 1,
                   "friend search shows the matching player")
        self.text_ui(friends, "friend-search", "")
        self.click_ui(friends, "friend-filter-online")
        self.check(self.item(friends, "friends-list").property("count") == 1,
                   "online filter excludes the offline friend")
        self.click_ui(friends, "friend-filter-all")
        self.check(self.item(friends, "friends-list").property("count") == 2,
                   "clearing filters restores all contacts")
        for tab in (1, 2, 3, 0):
            self.click_ui(friends, "friends-tab-" + str(tab))
            self.check(self.item(friends, "friends-list").property("count") == (2 if tab == 0 else 1),
                       "friend tab renders the corresponding entries: " + str(tab))
        self.key_ui(friends, Qt.Key_Escape, "friends-close-after-reading")
        notifications = home.controller.view["friendNotifications"]
        self.check(all(notifications[kind] == 0 for kind in ("requests", "invitations", "joinRequests"))
                   and not notifications["homeAttention"],
                   "reading notification tabs clears unread markers and Home attention")
        self.check(self.item(home, "home-friends-badge").property("count") == 3,
                   "pending requests remain counted until they are handled")
        self.click_ui(home, "open-friends-home")
        self.check(friends.isVisible(), "Home can reopen the same friends window")
        self.social(empty=True)
        self.check(self.item(friends, "friends-list").property("count") == 0
                   and self.item(friends, "empty-add-friend").isVisible(),
                   "empty friends list explains the next action")
        self.screenshot_ui("home-empty-friends", friends)
        self.key_ui(friends, Qt.Key_Escape, "friends-empty-close")
        self.assert_no_qml_errors()
        self.finish_test()

    def test_home_stop_normal_exit_crash_log_and_relaunch(self):
        sessions = self.prepare_game_process()
        home = self.window.started_page
        self.click_ui(home, "launch-game")
        self.check(not sessions.sessions and home.controller.view["launchTitle"] == "请先设置角色",
                   "launch without an account explains the missing prerequisite")
        self.offline_login()
        first = self.launch_child(sessions)
        self.check(home.controller.view["launchTitle"] == "停止游戏",
                   "single-session launch button becomes Stop")
        self.click_ui(home, "launch-game")
        self.wait_for(lambda: not sessions._sessions, "Stop finishes the actual process and worker")
        self.check(first.poll() is not None and sessions._sequence == 1,
                   "with multiple launch disabled the second click stops instead of spawning another")
        self.check(self.window._launch_error_dialog is None,
                   "intentional stopping does not report a crash")
        normal = self.launch_child(sessions)
        self.exit_child(normal)
        self.wait_for(lambda: not sessions._sessions, "normal child exit restores Home")
        self.check(normal.returncode == 0 and home.controller.view["launchTitle"] == "启动游戏",
                   "normal exit restores the launch button")
        crashed = self.launch_child(sessions)
        self.exit_child(crashed, crash=True)
        self.wait_for(lambda: not sessions._sessions and self.window._launch_error_dialog is not None
                      and self.window._launch_error_dialog.isVisible(),
                      "abnormal child exit presents the production error dialog")
        self.check(crashed.returncode == 17, "the actual abnormal exit code is retained")
        self.click_ui(self.window._launch_error_dialog, "dialog-action-0")
        self.check(self.window._debug_dialog.isVisible()
                   and any("退出代码：17" in line for line in self.window._debug_output),
                   "View log opens the production log with the abnormal exit code")
        self.screenshot_ui("home-crash-log", self.window._debug_dialog)
        self.key_ui(self.window._debug_dialog, Qt.Key_Escape, "close-crash-log")
        self.launch_child(sessions)
        self.click_ui(home, "launch-game")
        self.wait_for(lambda: not sessions._sessions, "Home successfully launches and stops after a crash")
        self.assert_no_qml_errors()
        self.finish_test()

    def test_home_four_processes_stop_only_the_selected_session(self):
        sessions = self.prepare_game_process()
        self.manager.set_setting("launcher.allow_multiple", True)
        self.offline_login()
        home = self.window.started_page
        home.on_page_activate()
        children = [self.launch_child(sessions, count) for count in range(1, 5)]
        self.check(len({process.pid for process in children}) == 4,
                   "four Home clicks launch four distinct OS processes")
        self.screenshot_ui("home-four-sessions")
        self.click_ui(home, "game-session-picker")
        self.key_ui(home, Qt.Key_Home, "select-first-session")
        self.key_ui(home, Qt.Key_Return, "confirm-first-session")
        self.check(sessions.selected["launcher"].process is children[0],
                   "session dropdown selects the first running process")
        self.click_ui(home, "game-session-actions")
        self.click_ui(home, "stop-current-game")
        self.wait_for(lambda: children[0].poll() is not None and len(sessions._sessions) == 3,
                      "menu stop removes only the selected worker")
        self.check(all(process.poll() is None for process in children[1:]) and sessions.running,
                   "three other processes remain alive after stopping the selected session")
        for remaining in (2, 1, 0):
            self.click_ui(home, "game-session-actions")
            self.click_ui(home, "stop-current-game")
            self.wait_for(lambda: len(sessions._sessions) == remaining,
                          "session menu stops one more process: " + str(remaining))
        self.check(all(process.poll() is not None for process in children)
                   and home.controller.view["launchTitle"] == "启动游戏",
                   "stopping all sessions restores the launch state")
        self.assert_no_qml_errors()
        self.finish_test()
