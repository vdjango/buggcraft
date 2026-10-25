"""First-run setup renders, saves preferences, and can be safely skipped."""
from types import SimpleNamespace
from unittest.mock import Mock

from _qml_test_support import LauncherQmlCase
from core.launcher import MinecraftLibLauncher
from ui.dialog.OnboardingDialog import OnboardingDialog


class OnboardingTests(LauncherQmlCase):
    def test_wizard_renders_and_persists_language_translation_and_play_style(self):
        dialog = OnboardingDialog(None, self.window.resource_path)
        self.addCleanup(dialog.close)
        self.assertIsNotNone(dialog.quick.rootObject(), str(dialog.quick.errors()))
        dialog.show()
        self.pump()
        self.snapshot('onboarding-welcome', dialog)

        controller = dialog.controller
        self.click(dialog, 'onboarding-next')
        self.assertEqual(controller.step, 1)
        controller.setLanguage('en_us')
        controller.setTranslation(True)
        self.click(dialog, 'onboarding-next')
        self.assertEqual(controller.step, 2)
        controller.togglePreference('modded')
        self.click(dialog, 'onboarding-next')
        self.assertEqual(controller.step, 3)
        controller.setRoute('create')
        self.pump()
        self.snapshot('onboarding-room-choice', dialog)
        controller.skip()

        self.assertTrue(self.manager.get_setting('onboarding.completed'))
        self.assertEqual(self.manager.get_setting('game.language'), 'en_us')
        self.assertTrue(self.manager.get_setting('translation.enabled'))
        self.assertEqual(self.manager.get_setting('onboarding.game_preferences'), ['modded'])
        self.assert_no_qml_errors()

    def test_invalid_preference_and_language_are_ignored(self):
        dialog = OnboardingDialog(None, self.window.resource_path)
        self.addCleanup(dialog.close)
        dialog.controller.setLanguage('unsupported')
        dialog.controller.togglePreference('unexpected')
        self.assertEqual(dialog.controller.language, 'zh_cn')
        self.assertEqual(dialog.controller.preferences, [])

    def test_selected_game_locale_is_accepted_by_launcher(self):
        launcher = MinecraftLibLauncher(str(self.directory))
        launcher.set_language('en_us')
        self.assertEqual(launcher.minecraft_language, 'en_us')

    def test_first_run_entry_opens_and_create_route_guides_to_node_setup(self):
        self.manager.set_setting('onboarding.completed', False)
        self.window.show_first_run_onboarding()
        self.pump()
        dialog = self.window._onboarding_dialog
        self.assertIsNotNone(dialog.quick.rootObject(), str(dialog.quick.errors()))

        backend = SimpleNamespace(view={'nodeAvailable': False}, navigate=Mock())
        page = SimpleNamespace(_multiplayer_dialog=SimpleNamespace(backend=backend),
                               show_multiplayer_dialog=Mock())
        dialog.launcher = SimpleNamespace(started_page=page)
        dialog.controller.setRoute('create')
        dialog.controller.finish()
        page.show_multiplayer_dialog.assert_called_once_with()
        backend.navigate.assert_called_once_with('nodes')
        self.assertTrue(self.manager.get_setting('onboarding.completed'))
        self.assert_no_qml_errors()\n