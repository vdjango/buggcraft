"""First-run guidance stays inside the launcher's real pages and controls."""
from _qml_test_support import LauncherQmlCase
from core.launcher import MinecraftLibLauncher


class OnboardingCoachTests(LauncherQmlCase):
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
        for action, expected in (('settings', 1), ('language', 2), ('translation', 3), ('lobby', 4)):
            coach.action(action)
            self.assertEqual(coach.index, expected)
        coach._advance()
        self.assertEqual(coach.index, 5)
        coach._advance()
        self.assertEqual(coach.index, 6)
        coach.action('create')
        self.assertEqual(coach.index, 7)
        coach.action('privacy')
        self.assertEqual(coach.index, 8)
        coach.action('create-world')
        self.assertFalse(coach.visible)
        self.assertTrue(self.manager.get_setting('onboarding.completed'))

    def test_selected_game_locale_is_accepted_by_launcher(self):
        launcher = MinecraftLibLauncher(str(self.directory))
        launcher.set_language('en_us')
        self.assertEqual(launcher.minecraft_language, 'en_us')
