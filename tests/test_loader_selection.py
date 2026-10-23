from unittest.mock import patch
from _qml_test_support import LauncherQmlCase
from core.loader_rules import LOADERS, COMPONENTS, incompatibility


class LoaderSelectionTests(LauncherQmlCase):
    def test_matrix_matches_requested_combinations(self):
        allowed = {'Forge': {'Forge', 'OptiFine'}, 'NeoForge': {'NeoForge'},
                   'Fabric': {'Fabric', 'Fabric API'}, 'Quilt': {'Quilt', 'Fabric API', 'QSL/QFAPI'}}
        for loader in LOADERS:
            for component in COMPONENTS:
                self.assertEqual(not incompatibility(component, loader), component in allowed[loader])

    def test_commit_blocks_others_remove_restores_and_game_change_clears(self):
        controller = self.window.download_page.games_page.controller
        controller.versions = [dict(id='1.20.1'), dict(id='1.21.1')]
        controller.selectGame('1.20.1')
        controller.selectLoader('Forge')
        self.wait_until(lambda: not controller.loader_busy)
        self.assertEqual(controller.loader_version, '47.4.0')
        self.assertIn('Forge', next(item for item in controller.view['components'] if item['name'] == 'Fabric API')['reason'])
        controller.selectLoader('Fabric')
        self.assertEqual(controller.loader, 'Forge')
        controller.selectLoader('')
        controller.selectLoader('Quilt')
        self.wait_until(lambda: not controller.loader_busy)
        self.assertIn('Quilt', next(item for item in controller.view['components'] if item['name'] == 'OptiFine')['reason'])
        controller.selectGame('1.21.1')
        self.assertEqual(controller.loader, '')
        self.assertTrue(all(not item['reason'] for item in controller.view['components']))

    def test_stale_loader_response_cannot_restore_previous_game_selection(self):
        controller = self.window.download_page.games_page.controller
        controller.versions = [dict(id='1.20.1'), dict(id='1.21.1')]
        controller.selectGame('1.20.1')
        with patch.object(controller.pool, 'start'):
            controller.selectLoader('Forge')
        sequence = controller.loader_sequence
        controller.selectGame('1.21.1')
        controller._finished(sequence, 'Forge', ['47.4.0'], '')
        self.assertEqual((controller.loader, controller.loader_version), ('', ''))
