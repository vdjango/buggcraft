"""First-run guidance stays inside the launcher's real pages and controls."""
from _qml_test_support import LauncherQmlCase, qt_mouse_click
from core.launcher import MinecraftLibLauncher
from PySide6.QtCore import QEvent, QObject, QPoint, QRectF
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtCore import QUrl
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QDialog, QVBoxLayout
from unittest.mock import patch
from _qml_test_support import ROOT


class OnboardingCoachTests(LauncherQmlCase):
    def test_global_input_filter_only_receives_events_during_teaching(self):
        from ui.widgets.onboarding_coach import OnboardingCoach

        watched = QObject()
        class CountingCoach(OnboardingCoach):
            received = 0
            def eventFilter(self, target, event):
                if target is watched and event.type() == QEvent.User:
                    self.received += 1
                return super().eventFilter(target, event)

        coach = CountingCoach(self.window)
        self.app.sendEvent(watched, QEvent(QEvent.User))
        self.assertEqual(coach.received, 0, 'Inactive teaching must not intercept normal Qt events')
        self.manager.set_setting('onboarding.completed', False)
        coach.start()
        self.app.sendEvent(watched, QEvent(QEvent.User))
        self.assertEqual(coach.received, 1, 'Active teaching must retain its global input lock')
        coach.finish()
        self.app.sendEvent(watched, QEvent(QEvent.User))
        self.assertEqual(coach.received, 1, 'Finishing must remove the application filter')

    def step_index(self, target):
        return next(index for index, step in enumerate(self.window.tutorial_controller.steps)
                    if step['target'] == target)

    def continue_past_sound_settings(self, coach):
        # Hosted release runners can take longer to deliver the preceding
        # settings click while the real QML page is settling.
        self.wait_until(lambda: coach.demoStep == 'sound-settings')
        QTest.keyClick(self.window.settings_page.general_page.quick, Qt.Key_Return)
        self.pump(200)

    def qml_item(self, quick, name):
        root = quick.rootObject()
        self.assertIsNotNone(root, str(quick.errors()))

        def find(item):
            if item.objectName() == name:
                return item
            for child in item.childItems():
                found = find(child)
                if found is not None:
                    return found
            return None

        found = find(root)
        self.assertIsNotNone(found, name)
        return found

    def assert_visible_spotlight(self, coach):
        coach.refresh()
        self.assertIsNotNone(coach._target_object)
        overlay = coach._overlays[coach._window()]
        self.assertTrue(overlay.isVisible())
        self.assertTrue(QRectF(overlay.rect()).contains(coach._target_rect),
                        f'Target outside the launcher: {coach._target_rect}')

    def assert_tutorial_glow(self, control):
        self.assertTrue(control.property('tutorialHighlight'))
        glow = next((child for child in control.childItems()
                     if child.objectName() == 'choice-tutorial-glow'), None)
        self.assertIsNotNone(glow)
        self.assertTrue(glow.isVisible())

    def open_tutorial_lobby(self, **state):
        from tests.test_lobby_layout import LobbyBackend
        backend = LobbyBackend()
        backend._view.update(state)
        dialog = QDialog(self.window)
        dialog.resize(721, 505)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(0, 0, 0, 0)
        quick = QQuickWidget(dialog)
        quick.setResizeMode(QQuickWidget.SizeRootObjectToView)
        quick.rootContext().setContextProperty('lobby', backend)
        coach = self.window.tutorial_controller
        quick.rootContext().setContextProperty('tutorial', coach)
        quick.setSource(QUrl.fromLocalFile(str(ROOT / 'resources/qml/multiplayer/Lobby.qml')))
        layout.addWidget(quick)
        self.manager.set_setting('onboarding.completed', False)
        coach.start()
        coach.attach_lobby(dialog)
        coach.index = self.step_index('node-picker')
        coach.changed.emit()
        coach._prepare_and_refresh()
        self.pump(200)
        return coach, backend, dialog, quick

    def test_intro_card_uses_launcher_hierarchy_and_action_labels(self):
        self.manager.set_setting('onboarding.completed', False)
        coach = self.window.tutorial_controller
        coach.start()
        self.pump(200)
        overlay = coach._overlays[coach._window()]
        overlay.grab()
        self.assertGreaterEqual(overlay.card_rect.width(), 350)
        self.assertTrue(overlay.card_rect.contains(overlay.body_rect))
        self.assertIn('设置', overlay._focus_terms(coach.current_step()))
        self.assertGreater(overlay.body_height, 0)
        coach.finish()

    def test_room_prompt_stays_actionable_when_target_is_temporarily_missing(self):
        coach, backend, dialog, quick = self.open_tutorial_lobby()
        self.assertEqual(coach.index, self.step_index('node-picker'))
        with patch.object(coach, '_find_qml_item', return_value=None):
            coach.refresh()
            self.pump(100)
        overlay = coach._overlays[dialog]
        overlay.grab()
        self.assertTrue(overlay.isVisible())
        self.assertTrue(coach._target_rect.isEmpty())
        self.assertFalse(coach._continue_rect.isEmpty())
        point = overlay.mapTo(dialog, coach._continue_rect.center().toPoint())
        qt_mouse_click(dialog, point)
        self.pump(200)
        self.assertEqual(coach.index, self.step_index('rooms-list'))
        coach.finish()

    def test_mouse_can_choose_a_language_from_the_undimmed_popup(self):
        self.manager.set_setting('onboarding.completed', False)
        coach = self.window.tutorial_controller
        coach.start()
        self.click(self.window.title_bar, 'launcher-nav-settings')
        self.pump(200)
        page = self.window.settings_page.general_page
        self.click(page, 'setting-select-game-language')
        self.pump(200)
        popup = coach._popup_item()
        self.assertIsNotNone(popup)
        self.assertGreater(popup.width(), 200)
        point = popup.mapToScene(popup.boundingRect().topLeft()).toPoint()
        point += QPoint(50, 18)
        global_point = page.quick.mapToGlobal(point)
        self.assertTrue(any(rect.contains(global_point) for rect in coach._allowed_global_rects()))
        overlay = coach._overlays[self.window]
        mask = overlay.grab().toImage()
        local = overlay.mapFromGlobal(global_point)
        pixel = QPoint(round(local.x() * mask.devicePixelRatio()), round(local.y() * mask.devicePixelRatio()))
        self.assertEqual(mask.pixelColor(pixel).alpha(), 0,
                         f'Popup must not be covered by the dark mask: {local}, {coach._popup_rect(overlay)}')
        self.assertFalse(overlay.card_rect.intersects(coach._popup_rect(overlay)))
        self.snapshot('onboarding-language-popup')
        qt_mouse_click(page.quick, point)
        self.pump(200)
        self.assertEqual(coach.index, 2)
        self.assert_no_qml_errors()

    def test_node_dropdown_is_clickable_without_leaving_the_tutorial(self):
        coach, backend, dialog, quick = self.open_tutorial_lobby(nodes=[], nodeIndex=-1, nodeAvailable=False)
        node = self.qml_item(quick, 'node-picker')
        self.assert_tutorial_glow(node)
        empty_add_node = self.qml_item(quick, 'empty-add-node')
        self.assertFalse(empty_add_node.property('enabled'))
        qt_mouse_click(quick,
                         empty_add_node.mapToScene(empty_add_node.boundingRect().center()).toPoint())
        self.pump(100)
        self.assertEqual(backend.view['page'], 'hall')
        self.assertEqual(backend.actions, [])
        unrelated = self.qml_item(quick, 'hall-transport')
        qt_mouse_click(quick,
                         unrelated.mapToScene(unrelated.boundingRect().center()).toPoint())
        self.pump(100)
        self.assertFalse(unrelated.property('tutorialPopupVisible'))
        qt_mouse_click(quick,
                         node.mapToScene(node.boundingRect().center()).toPoint())
        self.pump(200)
        self.assertTrue(node.property('tutorialPopupVisible'))
        popup = coach._popup_item()
        self.assertIsNotNone(popup)
        qt_mouse_click(quick,
                         popup.mapToScene(popup.boundingRect().center()).toPoint())
        self.pump(200)
        self.assertEqual(backend.view['page'], 'hall')
        self.assertEqual(backend.actions, [])
        self.assertEqual(coach.index, self.step_index('node-picker'))
        self.assertTrue(node.property('tutorialPopupVisible'))
        QTest.keyClick(quick, Qt.Key_Escape)
        self.pump(100)
        self.assertFalse(node.property('tutorialPopupVisible'))
        self.snapshot('onboarding-node')
        coach._continue()
        self.pump(200)
        self.assertEqual(coach.index, self.step_index('rooms-list'))
        self.assert_no_qml_errors()

    def test_demo_restores_real_node_and_world_state_on_exit(self):
        worlds = [dict(version='1.21.8', port=51234)]
        coach, backend, dialog, quick = self.open_tutorial_lobby(worlds=worlds, nodeAvailable=True)
        coach.index = self.step_index('create-mode-prepare')
        coach.changed.emit()
        coach._prepare_and_refresh()
        self.pump(200)
        self.assertEqual(backend.view['page'], 'create')
        self.assertFalse(backend.view['nodeAvailable'])
        coach.finish()
        self.pump(200)
        self.assertEqual(backend.view['page'], 'hall')
        self.assertTrue(backend.view['nodeAvailable'])
        self.assertEqual(backend.view['worlds'], worlds)
        self.assertEqual(backend.actions, [])
        self.assertFalse(dialog.isVisible())
        self.assertTrue(self.window.started_page.isVisible())
        self.assert_no_qml_errors()

    def test_creation_modes_are_demonstrated_without_scanning_or_creating_a_room(self):
        coach, backend, dialog, quick = self.open_tutorial_lobby(pendingOpenWorldPort=51234)
        coach.index = self.step_index('create-mode-prepare')
        coach.changed.emit()
        coach._prepare_and_refresh()
        self.pump(200)
        self.assert_visible_spotlight(coach)
        self.assertFalse(self.qml_item(quick, 'create-world-discovery').isVisible())
        QTest.keyClick(quick, Qt.Key_Return)
        self.pump(200)
        self.assertEqual(coach.index, self.step_index('create-mode-world'))
        self.assert_visible_spotlight(coach)
        button = self.qml_item(quick, 'create-mode-world')
        qt_mouse_click(quick, button.mapToScene(button.boundingRect().center()).toPoint())
        self.pump(200)
        self.assertTrue(self.qml_item(quick, 'create-world-discovery').isVisible())
        self.assertEqual(backend.actions, [])
        # Other controls remain locked even after revealing the real panel.
        unrelated = self.qml_item(quick, 'discover-worlds')
        qt_mouse_click(quick, unrelated.mapToScene(unrelated.boundingRect().center()).toPoint())
        self.pump(100)
        self.assertEqual(backend.actions, [])
        coach.finish()
        self.pump(100)
        self.assertEqual(backend.view['pendingOpenWorldPort'], 51234)
        self.assertFalse(dialog.isVisible())
        self.assert_no_qml_errors()

    def test_all_long_instructions_fit_inside_the_card(self):
        coach, backend, dialog, quick = self.open_tutorial_lobby()
        for index in range(len(coach.steps)):
            if coach.steps[index]['target'] == 'tutorial-friends-target':
                self.window.switch_pages('开始')
            coach.index = index
            coach.changed.emit()
            coach._prepare_and_refresh()
            self.pump(200)
            self.assert_visible_spotlight(coach)
            overlay = coach._overlays[coach._window()]
            overlay.grab()
            self.assertTrue(QRectF(overlay.rect()).contains(overlay.card_rect), f'Step {index}')
            self.assertTrue(overlay.card_rect.contains(overlay.body_rect), f'Step {index}')
            self.assertGreaterEqual(overlay.body_rect.height(), overlay.body_height)
            self.snapshot('onboarding-step-' + str(index), coach._window())
        coach.finish()

    def test_first_run_flash_preview_requires_user_action(self):
        self.manager.set_setting('onboarding.completed', False)
        coach = self.window.tutorial_controller
        coach.start()
        for action in ('settings', 'language', 'translation', 'quick_action'):
            coach.action(action)
        self.continue_past_sound_settings(coach)
        self.pump(200)
        self.assertEqual(coach.demoStep, 'multiplayer-normal')
        glow = self.item(self.window.started_page, 'home-multiplayer-glow')
        self.assertFalse(glow.property('active'))
        with patch.object(self.window.started_page, 'show_multiplayer_dialog') as open_lobby:
            QTest.keyClick(self.window.started_page.quick, Qt.Key_Return)
            self.pump(200)
            self.assertEqual(coach.index, self.step_index('open-lobby-home'))
            self.assertTrue(glow.property('active'))
            phase = glow.property('phase')
            self.pump(150)
            self.assertNotEqual(glow.property('phase'), phase)
            self.snapshot('onboarding-multiplayer-flash')
            self.click(self.window.started_page, 'open-lobby-home')
            self.assertEqual(coach.index, self.step_index('tutorial-friends-target'))
            open_lobby.assert_not_called()
        self.assertTrue(self.item(self.window.started_page, 'tutorial-friends-target').isVisible())
        self.assertTrue(self.item(self.window.started_page, 'home-friends-glow').property('active'))
        coach.finish()
        self.assertFalse(self.item(self.window.started_page, 'open-friends-home').isVisible())
        self.assert_no_qml_errors()

    def test_real_controller_completes_without_a_node_or_clipboard_join(self):
        from ui.dialog.MultiplayerDialog import MultiplayerDialog
        dialog = MultiplayerDialog(self.window.started_page, self.directory / 'onboarding-lobby.json')
        self.window.started_page._multiplayer_dialog = dialog
        self.addCleanup(dialog.shutdown)
        coach = self.window.tutorial_controller
        coach.attach_lobby(dialog)
        self.manager.set_setting('onboarding.completed', False)
        coach.start()
        with patch.object(dialog.backend, 'join_from_clipboard') as clipboard_join:
            for action in ('settings', 'language', 'translation', 'quick_action', 'sound', 'lobby', 'lobby', 'friends'):
                if action == 'sound':
                    self.continue_past_sound_settings(coach)
                else:
                    coach.action(action)
                self.pump(100)
            self.assertEqual(coach.index, self.step_index('node-picker'))
            self.assertTrue(dialog.isVisible())
            self.assertEqual(dialog.backend.view['nodes'], [])
            for target in ('rooms-list', 'create-mode-prepare', 'create-mode-world', 'create-node-unavailable', 'create-next'):
                QTest.keyClick(dialog.quick, Qt.Key_Return)
                self.pump(150)
                self.assertEqual(coach.index, self.step_index(target))
                self.assert_visible_spotlight(coach)
            QTest.keyClick(dialog.quick, Qt.Key_Return)
            self.pump(150)
            self.assertFalse(coach.visible)
            self.assertEqual(dialog.backend.view['page'], 'hall')
            self.assertEqual(dialog.backend.records, {})
            self.assertFalse(dialog.isVisible())
            self.assertFalse(dialog._shutdown)
            self.assertFalse(dialog.backend.closed)
            self.assertTrue(self.window.started_page.isVisible())
            self.assertTrue(self.window.isVisible())
            clipboard_join.assert_not_called()
        self.window.started_page._show_multiplayer_window()
        self.pump(100)
        self.assertTrue(dialog.isVisible())
        self.assertFalse(dialog.backend.closed)
        self.assert_no_qml_errors()

    def test_all_quick_action_choices_save_and_suppress_automatic_actions_during_guidance(self):
        coach = self.window.tutorial_controller
        page = self.window.settings_page.general_page
        for index, expected in enumerate(('关闭', '首页提示', '自动创建或加入')):
            with self.subTest(mode=expected):
                self.manager.set_setting('onboarding.completed', False)
                coach.start()
                coach.index = 3
                coach.changed.emit()
                coach._prepare_and_refresh()
                self.pump(200)
                self.click(page, 'setting-option-multiplayer.quick_action-' + str(index))
                self.pump(200)
                self.assertEqual(self.manager.get_setting('multiplayer.quick_action'), expected)
                self.continue_past_sound_settings(coach)
                self.assertEqual(coach.demoStep, 'multiplayer-normal')
                self.window.started_page.controller.multiplayer_action = 'create'
                with patch.object(self.window.started_page, '_ensure_multiplayer_dialog') as open_dialog:
                    self.window.started_page._run_auto_multiplayer()
                    open_dialog.assert_not_called()
                coach.finish()
        self.assert_no_qml_errors()

    def test_click_settings_keeps_language_guidance_visible(self):
        self.manager.set_setting('onboarding.completed', False)
        coach = self.window.tutorial_controller
        coach.start()
        self.click(self.window.title_bar, 'launcher-nav-settings')
        self.pump(200)

        self.assertEqual(coach.index, 1)
        self.assert_visible_spotlight(coach)
        language = self.item(self.window.settings_page.general_page, 'setting-select-game-language')
        self.assert_tutorial_glow(language)
        self.assertFalse(language.property('tutorialPopupVisible'))
        self.assertGreater(language.width(), 200)
        self.assertAlmostEqual(coach._target_rect.width(), language.width(), delta=2.0)
        self.assert_no_qml_errors()

    def test_guidance_blocks_unrelated_clicks_until_the_target_is_used(self):
        self.manager.set_setting('onboarding.completed', False)
        coach = self.window.tutorial_controller
        coach.start()
        self.click(self.window.title_bar, 'launcher-nav-settings')
        self.pump(200)
        page = self.window.settings_page.general_page
        before = self.manager.get_setting('translation.enabled')
        self.click(page, 'setting-toggle-translation.enabled')
        self.assertEqual(coach.index, 1)
        self.assertEqual(self.manager.get_setting('translation.enabled'), before)
        self.assert_tutorial_glow(self.item(page, 'setting-select-game-language'))
        self.assert_no_qml_errors()

    def test_language_target_opens_the_real_dropdown(self):
        self.manager.set_setting('onboarding.completed', False)
        coach = self.window.tutorial_controller
        coach.start()
        self.click(self.window.title_bar, 'launcher-nav-settings')
        self.pump(200)
        page = self.window.settings_page.general_page
        self.click(page, 'setting-select-game-language')
        language = self.item(page, 'setting-select-game-language')
        self.assertTrue(language.property('activeFocus'))
        self.assertTrue(language.property('tutorialPopupVisible'))
        QTest.keyClick(page.quick, Qt.Key_Down)
        self.assertGreaterEqual(language.property('highlightedIndex'), 0)
        QTest.keyClick(page.quick, Qt.Key_Return)
        self.pump(200)
        self.assertEqual(coach.index, 2)
        self.assert_no_qml_errors()

    def test_enter_steps_also_have_a_clickable_continue_button(self):
        from tests.test_lobby_layout import LobbyBackend
        self.manager.set_setting('onboarding.completed', False)
        coach = self.window.tutorial_controller
        backend = LobbyBackend()
        dialog = QDialog(self.window)
        dialog.resize(721, 505)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(0, 0, 0, 0)
        quick = QQuickWidget(dialog)
        quick.setResizeMode(QQuickWidget.SizeRootObjectToView)
        quick.rootContext().setContextProperty('lobby', backend)
        quick.rootContext().setContextProperty('tutorial', coach)
        quick.setSource(QUrl.fromLocalFile(str(ROOT / 'resources/qml/multiplayer/Lobby.qml')))
        layout.addWidget(quick)

        def show_lobby():
            dialog.show()
            coach.attach_lobby(dialog)

        coach.start()
        for action in ('settings', 'language', 'translation', 'quick_action'):
            coach.action(action)
        self.continue_past_sound_settings(coach)
        coach.action('lobby')
        coach.action('lobby')
        show_lobby()
        self.pump(250)
        coach.action('friends')
        self.pump(250)
        self.assertEqual(coach.index, self.step_index('node-picker'))
        self.assertFalse(coach._continue_rect.isEmpty())
        overlay = coach._overlays[dialog]
        point = overlay.mapTo(dialog, coach._continue_rect.center().toPoint())
        qt_mouse_click(dialog, point)
        self.pump(200)
        self.assertEqual(coach.index, self.step_index('rooms-list'))
        self.assert_no_qml_errors()

    def test_real_settings_interactions_reach_home_lobby_entry(self):
        self.manager.set_setting('onboarding.completed', False)
        coach = self.window.tutorial_controller
        coach.start()
        self.click(self.window.title_bar, 'launcher-nav-settings')
        self.pump(200)
        page = self.window.settings_page.general_page
        self.assert_visible_spotlight(coach)
        self.click(page, 'setting-select-game-language')
        QTest.keyClick(page.quick, Qt.Key_Down)
        QTest.keyClick(page.quick, Qt.Key_Return)
        self.pump(250)
        self.assertEqual(coach.index, 2)
        self.assert_visible_spotlight(coach)
        self.assertEqual(self.manager.get_setting('game.language'),
                         page.controller.groups[3]['value'])
        self.click(page, 'setting-toggle-translation.enabled')
        self.pump(250)
        self.assertTrue(self.manager.get_setting('translation.enabled'))
        self.assertEqual(coach.index, 3)
        self.click(page, 'setting-option-multiplayer.quick_action-1')
        self.pump(250)
        self.assertEqual(coach.index, 4)
        self.assert_visible_spotlight(coach)
        self.continue_past_sound_settings(coach)
        self.assertTrue(self.window.started_page.isVisible())
        self.assertFalse(self.item(self.window.started_page, 'home-multiplayer-glow').property('active'))
        self.click(self.window.started_page, 'open-lobby-home')
        self.assertEqual(coach.index, self.step_index('open-lobby-home'))
        self.assertTrue(self.item(self.window.started_page, 'home-multiplayer-glow').property('active'))
        self.assert_visible_spotlight(coach)
        self.assert_no_qml_errors()

    def test_sound_guidance_toggles_real_setting_without_forcing_a_choice(self):
        coach = self.window.tutorial_controller
        page = self.window.settings_page.general_page
        key = 'multiplayer.notification_sound'
        for initial in (True, False):
            with self.subTest(initial=initial):
                page.controller.setValue(key, initial)
                self.manager.set_setting('onboarding.completed', False)
                coach.start()
                coach.index = self.step_index('setting-toggle-' + key)
                coach.changed.emit()
                coach._prepare_and_refresh()
                # A newly exposed SettingsForm can need another Qt layout
                # turn on hosted macOS. Wait for the actual control instead
                # of accepting the preceding navigation spotlight.
                def sound_target_ready():
                    coach.refresh()
                    try:
                        return (coach._target_object is not None
                                and coach._target_object.objectName() == 'setting-toggle-' + key
                                and not coach._target_rect.isEmpty())
                    except RuntimeError:
                        return False
                self.wait_until(sound_target_ready)
                self.assert_visible_spotlight(coach)
                self.assertEqual(coach._target_object.objectName(), 'setting-toggle-' + key)
                self.assertEqual(self.manager.get_setting(key), initial)
                self.click(page, 'setting-toggle-' + key)
                self.pump(200)
                self.assertEqual(self.manager.get_setting(key), not initial)
                self.assertEqual(coach.demoStep, 'sound-settings')
                self.assert_visible_spotlight(coach)
                self.click(page, 'setting-toggle-' + key)
                self.pump(200)
                self.assertEqual(self.manager.get_setting(key), initial)
                self.continue_past_sound_settings(coach)
                self.assertEqual(coach.demoStep, 'multiplayer-normal')
                self.assertEqual(self.manager.get_setting(key), initial)
                coach.finish()
        self.assert_no_qml_errors()

    def test_sound_guidance_click_continue_preserves_the_current_setting(self):
        coach = self.window.tutorial_controller
        page = self.window.settings_page.general_page
        page.controller.setValue('multiplayer.notification_sound', False)
        self.manager.set_setting('onboarding.completed', False)
        coach.start()
        coach.index = self.step_index('setting-toggle-multiplayer.notification_sound')
        coach.changed.emit()
        coach._prepare_and_refresh()
        self.pump(200)
        self.assert_visible_spotlight(coach)
        overlay = coach._overlays[self.window]
        overlay.grab()
        self.assertFalse(coach._continue_rect.isEmpty())
        point = overlay.mapTo(self.window, coach._continue_rect.center().toPoint())
        qt_mouse_click(self.window, point)
        self.pump(200)
        self.assertEqual(coach.demoStep, 'multiplayer-normal')
        self.assertFalse(self.manager.get_setting('multiplayer.notification_sound'))
        self.assert_no_qml_errors()

    def test_mouse_completion_closes_lobby_and_returns_to_home(self):
        coach, backend, dialog, quick = self.open_tutorial_lobby()
        coach.index = self.step_index('create-mode-prepare')
        coach.changed.emit()
        coach._prepare_and_refresh()
        self.pump(200)
        coach.index = self.step_index('create-next')
        coach.changed.emit()
        coach._prepare_and_refresh()
        self.pump(200)
        overlay = coach._overlays[dialog]
        overlay.grab()
        point = overlay.mapTo(dialog, coach._continue_rect.center().toPoint())
        qt_mouse_click(dialog, point)
        self.pump(200)
        self.assertFalse(coach.visible)
        self.assertFalse(dialog.isVisible())
        self.assertTrue(self.window.started_page.isVisible())
        self.assertEqual(backend.view['page'], 'hall')
        self.assertTrue(self.manager.get_setting('onboarding.completed'))
        self.assertTrue(all(not overlay.isVisible() for overlay in coach._overlays.values()))
        self.assert_no_qml_errors()

    def test_click_through_to_real_lobby_and_create_page_without_creating_room(self):
        from tests.test_lobby_layout import LobbyBackend
        self.manager.set_setting('onboarding.completed', False)
        coach = self.window.tutorial_controller
        backend = LobbyBackend()
        backend._view['version'] = '1.21.8'
        dialog = QDialog(self.window)
        dialog.resize(721, 505)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(0, 0, 0, 0)
        quick = QQuickWidget(dialog)
        quick.setResizeMode(QQuickWidget.SizeRootObjectToView)
        quick.rootContext().setContextProperty('lobby', backend)
        quick.rootContext().setContextProperty('tutorial', coach)
        quick.setSource(QUrl.fromLocalFile(str(ROOT / 'resources/qml/multiplayer/Lobby.qml')))
        layout.addWidget(quick)

        def show_lobby():
            dialog.show()
            coach.attach_lobby(dialog)

        coach.start()
        self.click(self.window.title_bar, 'launcher-nav-settings')
        self.pump(200)
        page = self.window.settings_page.general_page
        self.click(page, 'setting-select-game-language')
        QTest.keyClick(page.quick, Qt.Key_Down)
        QTest.keyClick(page.quick, Qt.Key_Return)
        self.pump(200)
        self.click(page, 'setting-toggle-translation.enabled')
        self.pump(200)
        self.click(page, 'setting-option-multiplayer.quick_action-1')
        self.pump(200)
        self.continue_past_sound_settings(coach)
        self.click(self.window.started_page, 'open-lobby-home')
        self.assertEqual(coach.index, self.step_index('open-lobby-home'))
        self.click(self.window.started_page, 'open-lobby-home')
        self.pump(200)
        self.assertEqual(coach.index, self.step_index('tutorial-friends-target'))
        self.assertTrue(self.item(self.window.started_page, 'home-friends-glow').property('active'))
        self.assertEqual(self.item(self.window.started_page, 'home-friends-badge').property('count'), 2)
        coach.attach_lobby(dialog)
        self.click(self.window.started_page, 'tutorial-friends-target')
        self.pump(200)
        self.assertEqual(coach.index, self.step_index('node-picker'))
        self.assert_visible_spotlight(coach)
        node = self.qml_item(quick, 'node-picker')
        self.assert_tutorial_glow(node)
        point = node.mapToScene(node.boundingRect().center()).toPoint()
        qt_mouse_click(quick, point)
        self.pump(200)
        self.assertTrue(node.property('tutorialPopupVisible'))
        self.assertAlmostEqual(coach._target_rect.width(), node.width(), delta=2.0)
        QTest.keyClick(quick, Qt.Key_Return)
        self.pump(200)
        self.assertEqual(coach.index, self.step_index('rooms-list'))
        self.assert_visible_spotlight(coach)
        QTest.keyClick(quick, Qt.Key_Return)
        self.pump(200)
        self.assertEqual(coach.index, self.step_index('create-mode-prepare'))
        self.assert_visible_spotlight(coach)
        QTest.keyClick(quick, Qt.Key_Return)
        self.pump(200)
        self.assertEqual(coach.index, self.step_index('create-mode-world'))
        self.assert_visible_spotlight(coach)
        QTest.keyClick(quick, Qt.Key_Return)
        self.pump(200)
        self.assertEqual(coach.index, self.step_index('create-node-unavailable'))
        self.assert_visible_spotlight(coach)
        self.assertFalse(self.qml_item(quick, 'create-next').property('enabled'))
        QTest.keyClick(quick, Qt.Key_Return)
        self.pump(200)
        self.assertEqual(coach.index, self.step_index('create-next'))
        self.assert_visible_spotlight(coach)
        QTest.keyClick(quick, Qt.Key_Return)
        self.pump(200)
        self.assertFalse(coach.visible)
        self.assertTrue(self.manager.get_setting('onboarding.completed'))
        self.assertFalse(dialog.isVisible())
        self.assertTrue(self.window.started_page.isVisible())
        self.assertNotIn('quickCreate', [name for name, _ in backend.actions])
        self.assert_no_qml_errors()

    def test_settings_guidance_reopens_collapsed_section(self):
        self.window.switch_pages('设置')
        page = self.window.settings_page.general_page
        self.item(page, 'setting-group-game.language').setProperty('expanded', False)
        self.manager.set_setting('onboarding.completed', False)
        coach = self.window.tutorial_controller
        coach.start()
        self.click(self.window.title_bar, 'launcher-nav-settings')
        self.pump(250)
        self.assertTrue(self.item(page, 'setting-group-game.language').property('expanded'))
        self.assert_visible_spotlight(coach)
        self.assert_no_qml_errors()

    def test_first_run_starts_in_place_and_escape_completes(self):
        self.manager.set_setting('onboarding.completed', False)
        coach = self.window.tutorial_controller
        coach.start()
        self.pump()

        self.assertTrue(coach.visible)
        self.assertEqual(coach.steps[0]['target'], 'launcher-nav-settings')
        self.assertFalse(hasattr(self.window, '_onboarding_dialog'))
        coach.finish()
        self.assertTrue(self.manager.get_setting('onboarding.completed'))

    def test_language_and_translation_are_real_settings(self):
        controller = self.window.settings_page.general_page.controller
        controller.setValue('game.language', 'en_us')
        controller.setValue('translation.enabled', True)

        self.assertEqual(self.manager.get_setting('game.language'), 'en_us')
        self.assertTrue(self.manager.get_setting('translation.enabled'))

    def test_spotlight_resolves_controls_from_launcher_qml(self):
        self.manager.set_setting('onboarding.completed', False)
        coach = self.window.tutorial_controller
        coach.start()
        self.window.switch_pages('设置')
        coach.index = 1
        self.pump(80)
        coach.refresh()

        self.assertGreater(coach._target_rect.width(), 0)
        self.assertGreater(coach._target_rect.height(), 0)
        self.assert_no_qml_errors()

    def test_language_selection_advances_tutorial_and_can_be_skipped(self):
        coach = self.window.tutorial_controller
        self.manager.set_setting('onboarding.completed', False)
        coach.start()
        coach.index = 1
        coach.action('language')
        self.assertEqual(coach.index, 2)
        coach.finish()
        self.assertTrue(self.manager.get_setting('onboarding.completed'))

    def test_real_control_actions_advance_both_multiplayer_paths(self):
        coach = self.window.tutorial_controller
        self.manager.set_setting('onboarding.completed', False)
        coach.start()
        for action, expected in (('settings', 1), ('language', 2), ('translation', 3), ('quick_action', 4), ('sound', 5), ('lobby', 6), ('friends', 7)):
            if action == 'lobby':
                coach.action('lobby')
            if action == 'sound':
                self.continue_past_sound_settings(coach)
            else:
                coach.action(action)
            self.assertEqual(coach.index, expected)
        coach._advance()
        self.assertEqual(coach.index, self.step_index('rooms-list'))
        coach._advance()
        self.assertEqual(coach.index, self.step_index('create-mode-prepare'))
        coach._advance()
        self.assertEqual(coach.index, self.step_index('create-mode-world'))
        coach._advance()
        self.assertEqual(coach.index, self.step_index('create-node-unavailable'))
        coach._advance()
        self.assertEqual(coach.index, self.step_index('create-next'))
        coach._advance()
        self.assertFalse(coach.visible)
        self.assertTrue(self.manager.get_setting('onboarding.completed'))

    def test_selected_game_locale_is_accepted_by_launcher(self):
        launcher = MinecraftLibLauncher(str(self.directory))
        launcher.set_language('en_us')
        self.assertEqual(launcher.minecraft_language, 'en_us')
