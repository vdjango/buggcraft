from unittest.mock import patch
from _qml_test_support import LauncherQmlCase


class InstanceModpackEntryTests(LauncherQmlCase):
    def test_import_uses_selected_directory_after_each_directory_change(self):
        page = self.window.version_page.versions_page
        empty = self.directory / 'empty'
        empty.mkdir()
        for directory in (self.game_dir, empty, self.game_dir):
            self.manager.set_setting('minecraft.directory.installed', [str(self.game_dir), str(empty)])
            page.controller.reload()
            page.controller.selectDirectory(str(directory))
            downloads = self.window.download_page
            with patch.object(downloads.content_page.controller, 'choosePack'):
                downloads.games_page.controller.importPack()
            controller = self.window.download_page.content_page.controller
            self.assertEqual(controller.import_directory, str(directory))
            self.assertEqual(controller.view, 'import')
            self.assertIs(self.window.download_page.stack.currentWidget(), self.window.download_page.content_page)
        self.assert_no_qml_errors()

    def test_instance_heading_stays_fixed_and_has_no_duplicate_import_entry(self):
        self.window.switch_pages('实例')
        page = self.window.version_page.versions_page
        self.pump()
        button = self.item(page, 'instance-heading')
        geometry = (button.x(), button.y(), button.width(), button.height())
        page.controller._versions = [dict(version='长名称-' * 45, description='Forge')]
        page.controller.changed.emit()
        self.pump()
        self.assertEqual((button.x(), button.y(), button.width(), button.height()), geometry)
        def names(item):
            return [item.objectName()] + [name for child in item.childItems() for name in names(child)]
        self.assertNotIn('import-modpack', names(page.quick.rootObject()))
        self.assertIs(self.window.content_stack.currentWidget(), self.window.version_page)
        self.assert_no_qml_errors()

    def test_running_instance_is_protected_from_deletion(self):
        from types import SimpleNamespace
        page = self.window.version_page.versions_page
        with patch.object(page.controller, '_running', return_value=[(str(self.game_dir), '1.21.8', str(self.game_dir))]):
            page.controller.action('1.21.8', 'deleteVersion')
            page.controller.confirmDelete(True)
        self.assertTrue((self.game_dir / 'versions/1.21.8').exists())
        self.assertIn('退出', page.controller.view['status'])
