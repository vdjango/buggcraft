"""Exercise the in-page installation flow and compatible component selection."""
from unittest.mock import patch

from _qml_test_support import LauncherQmlCase


class InstallationQmlTests(LauncherQmlCase):
    def setUp(self):
        super().setUp()
        self.window.switch_pages('下载')
        self.page = self.window.download_page.games_page
        self.controller = self.page.controller
        self.controller.versions = [dict(id='1.20.1')]
        self.controller.selectGame('1.20.1')
        self.pump()

    def select(self, name):
        self.controller.openComponent(name)
        self.wait_until(lambda: not self.controller.loader_busy)
        self.assertEqual(self.controller.install_view, 'versions')
        self.click(self.page, 'component-version-0')
        self.assertEqual(self.controller.install_view, 'components')

    def test_component_tiles_keep_original_dimensions_and_selection_requires_commit(self):
        tile = self.item(self.page, 'component-Forge')
        self.assertEqual((tile.width(), tile.height()), (140, 150))
        self.click(self.page, 'component-Forge')
        self.wait_until(lambda: not self.controller.loader_busy)
        self.assertEqual(self.controller.loader, '')
        self.snapshot('install-component-versions')
        self.click(self.page, 'game-install-back')
        self.assertEqual(self.controller.loader, '')
        self.select('Forge')
        self.assertEqual(self.controller.loader, 'Forge')
        self.snapshot('install-components-forge')
        self.controller.openComponent('Fabric')
        self.assertEqual(self.controller.install_view, 'components')
        self.click(self.page, 'component-Forge-remove')
        self.assertEqual(self.controller.loader, '')
        self.click(self.page, 'game-install-back')
        self.assertEqual(self.controller.install_view, 'catalogue')
        self.assert_no_qml_errors()

    def test_quilt_and_both_apis_are_separate_choices_and_reach_install_worker(self):
        self.select('Quilt')
        self.select('Fabric API')
        self.select('QSL/QFAPI')
        selected = [item['name'] for item in self.controller.view['components'] if item['selected']]
        self.assertEqual(set(selected), {'Quilt', 'Fabric API', 'QSL/QFAPI'})
        with patch.object(self.page, 'start_install') as install:
            self.click(self.page, 'install-selected-game')
        self.assertEqual(install.call_args.args, ('1.20.1', 'Quilt', '47.4.0'))
        self.assertEqual({item['name'] for item in install.call_args.kwargs['addons']}, {'Fabric API', 'QSL/QFAPI'})
        self.controller.removeComponent('Fabric API')
        self.assertEqual(set(self.controller.addons), {'QSL/QFAPI'})
        self.controller.removeComponent('Quilt')
        self.assertEqual(self.controller.addons, {})
        self.assert_no_qml_errors()

    def test_back_invalidates_pending_versions_and_game_change_clears_addons(self):
        with patch.object(self.controller.pool, 'start'):
            self.controller.openComponent('Forge')
        sequence = self.controller.loader_sequence
        self.click(self.page, 'game-install-back')
        self.controller._finished(sequence, 'component:Forge', [dict(name='47')], '')
        self.assertEqual(self.controller.component_versions, [])
        self.controller.addons = {'Fabric API': dict(name='stale')}
        self.controller.versions.append(dict(id='1.21.8'))
        self.controller.selectGame('1.21.8')
        self.assertEqual(self.controller.addons, {})
        self.assert_no_qml_errors()

    def test_second_row_remains_clickable_in_original_small_window(self):
        scroll = self.item(self.page, 'game-component-scroll').property('contentItem')
        scroll.setProperty('contentY', max(0, scroll.property('contentHeight') - scroll.height()))
        self.pump()
        tile = self.item(self.page, 'component-Quilt')
        position = tile.mapToItem(scroll, tile.boundingRect().center())
        self.assertGreaterEqual(position.y(), 0)
        self.assertLessEqual(position.y(), scroll.height())
        self.snapshot('install-components-scrolled')
        self.click(self.page, 'component-Quilt')
        self.wait_until(lambda: not self.controller.loader_busy)
        self.assertEqual(self.controller.pending_component, 'Quilt')
        self.click(self.page, 'component-version-0')
        self.assertEqual(self.controller.loader, 'Quilt')
        self.assert_no_qml_errors()
