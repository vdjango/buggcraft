"""Real QML button clicks against temporary game instances only."""
import json
from unittest.mock import patch

from PySide6.QtTest import QTest
from _qml_test_support import LauncherQmlCase, Qt


class InstanceDeletionTests(LauncherQmlCase):
    def open_confirmation(self, identity='1.20.1', action='deleteVersion'):
        self.window.switch_pages('实例')
        controller = self.window.version_page.versions_page.controller
        controller.action(identity, action)
        self.pump()
        dialog = controller._delete_dialog
        self.assertIsNotNone(dialog)
        return controller, dialog

    def delete_and_wait(self, controller, dialog):
        self.click(dialog.host, 'dialog-action-1')
        self.wait_until(lambda: controller._delete_worker is None
                        and (controller._delete_dialog is None or dialog.controller.title != '正在删除…'))

    def test_cancel_button_keeps_instance_and_launcher_alive(self):
        controller, dialog = self.open_confirmation()
        self.click(dialog.host, 'dialog-action-0')
        self.assertIsNone(controller._delete_dialog)
        self.assertTrue((self.game_dir / 'versions/1.20.1').is_dir())
        self.assertTrue(self.window.isVisible())
        self.assertEqual(controller.view['confirmation'], {})
        self.assert_no_qml_errors()

    def test_delete_button_removes_only_target_and_keeps_launcher_alive(self):
        controller, dialog = self.open_confirmation()
        self.delete_and_wait(controller, dialog)
        self.assertIsNone(controller._delete_dialog)
        self.assertFalse((self.game_dir / 'versions/1.20.1').exists())
        self.assertTrue((self.game_dir / 'versions/1.21.8').is_dir())
        self.assertTrue(self.window.isVisible())
        self.assert_no_qml_errors()

    def test_repeated_cancel_escape_and_reopen_do_not_destroy_active_qml(self):
        for index in range(12):
            controller, dialog = self.open_confirmation()
            self.assertFalse(self.item(dialog.host, 'dialog-action-0').property('primary'))
            self.assertFalse(self.item(dialog.host, 'dialog-action-0').property('danger'))
            self.assertTrue(self.item(dialog.host, 'dialog-action-1').property('danger'))
            if index % 2:
                QTest.keyClick(dialog.quick, Qt.Key_Escape)
                self.pump()
            else:
                self.click(dialog.host, 'dialog-action-0')
            self.assertIsNone(controller._delete_dialog)
            self.assertTrue((self.game_dir / 'versions/1.20.1').is_dir())
        self.assert_no_qml_errors()

    def test_running_or_inherited_instance_is_not_deleted(self):
        controller, dialog = self.open_confirmation()
        with patch.object(controller, '_running', return_value=[(str(self.game_dir), '1.20.1')]):
            self.delete_and_wait(controller, dialog)
        self.assertIn('退出', dialog.controller.detail)
        self.assertIn('退出', controller.view['status'])
        path = self.game_dir / 'versions/1.21.8/1.21.8.json'
        path.write_text(json.dumps(dict(id='1.21.8', inheritsFrom='1.20.1')), encoding='utf-8')
        controller, dialog = self.open_confirmation()
        self.delete_and_wait(controller, dialog)
        self.assertIn('依赖', dialog.controller.detail)
        self.assertTrue((self.game_dir / 'versions/1.20.1').exists())

    def test_directory_switch_during_confirmation_prevents_deletion(self):
        controller, dialog = self.open_confirmation()
        self.manager.set_setting('minecraft.directory.enable', str(self.directory / 'other'))
        self.delete_and_wait(controller, dialog)
        self.assertIn('目录已切换', dialog.controller.detail)
        self.assertTrue((self.game_dir / 'versions/1.20.1').exists())

    def test_instance_defaults_to_highlighted_permanent_delete_and_can_only_remove(self):
        controller, dialog = self.open_confirmation()
        self.assertFalse(self.item(dialog.host, 'keep-game-directory').property('checked'))
        action = self.item(dialog.host, 'dialog-action-1')
        self.assertTrue(action.property('danger'))
        self.assertEqual(action.property('text'), '永久删除')
        warning = self.item(dialog.host, 'delete-local-files-warning-text')
        self.assertIn('会删除本地文件', warning.property('text'))
        self.assertIn('无法撤销', warning.property('text'))
        self.click(dialog.host, 'keep-game-directory')
        self.assertFalse(action.property('danger'))
        self.assertEqual(action.property('text'), '仅移除')
        original = (self.game_dir / 'versions/1.20.1/1.20.1.json').read_bytes()
        with patch('ui.pages.qml_instances.delete_minecraft_version') as delete_files:
            self.delete_and_wait(controller, dialog)
        delete_files.assert_not_called()
        self.assertEqual((self.game_dir / 'versions/1.20.1/1.20.1.json').read_bytes(), original)
        self.assertNotIn('1.20.1', [row['version'] for row in controller.view['versions']])
        controller.reload()
        self.assertNotIn('1.20.1', [row['version'] for row in controller.view['versions']])
        controller.restoreRemoved()
        self.assertIn('1.20.1', [row['version'] for row in controller.view['versions']])
        self.assertEqual(controller.view['removedCount'], 0)
        self.assert_no_qml_errors()

    def test_removed_dependant_still_prevents_deleting_its_parent_files(self):
        child = self.game_dir / 'versions/1.21.8'
        (child / '1.21.8.json').write_text(json.dumps(dict(id='1.21.8', inheritsFrom='1.20.1')), encoding='utf-8')
        controller, dialog = self.open_confirmation('1.21.8')
        self.click(dialog.host, 'keep-game-directory')
        self.delete_and_wait(controller, dialog)
        controller, dialog = self.open_confirmation('1.20.1')
        self.delete_and_wait(controller, dialog)
        self.assertIn('依赖', dialog.controller.detail)
        self.assertTrue((self.game_dir / 'versions/1.20.1').exists())

    def test_directory_cancel_and_delete_only_touch_temporary_games(self):
        controller, dialog = self.open_confirmation(str(self.game_dir), 'deleteDirectory')
        self.click(dialog.host, 'dialog-action-0')
        self.assertTrue(self.game_dir.exists())
        controller, dialog = self.open_confirmation(str(self.game_dir), 'deleteDirectory')
        self.assertTrue(self.item(dialog.host, 'keep-game-directory').property('checked'))
        self.click(dialog.host, 'keep-game-directory')
        self.delete_and_wait(controller, dialog)
        self.assertFalse(self.game_dir.exists())
        self.assertTrue(self.window.isVisible())
        self.assert_no_qml_errors()

    def test_remove_directory_can_keep_all_files_and_be_added_again(self):
        original = (self.game_dir / 'versions/1.20.1/1.20.1.json').read_bytes()
        controller, dialog = self.open_confirmation(str(self.game_dir), 'deleteDirectory')
        self.assertTrue(self.item(dialog.host, 'keep-game-directory').property('checked'))
        with patch('ui.pages.qml_instances.delete_minecraft_directory') as delete_files:
            self.delete_and_wait(controller, dialog)
        delete_files.assert_not_called()
        self.assertEqual((self.game_dir / 'versions/1.20.1/1.20.1.json').read_bytes(), original)
        self.assertNotIn(str(self.game_dir), self.manager.get_setting('minecraft.directory.installed'))
        with patch('ui.pages.qml_instances.QFileDialog.getExistingDirectory', return_value=str(self.game_dir)):
            controller.addDirectory()
        self.assertIn(str(self.game_dir), self.manager.get_setting('minecraft.directory.installed'))
        self.assert_no_qml_errors()

    def test_delete_failure_reports_error_and_allows_retry(self):
        controller, dialog = self.open_confirmation()
        with patch('ui.pages.qml_instances.delete_minecraft_version', return_value=False):
            self.delete_and_wait(controller, dialog)
        self.assertEqual(controller._delete_dialog, dialog)
        self.assertIn('删除失败', dialog.controller.detail)
        self.assertIn('删除失败', controller.view['status'])
        self.assertLess(dialog.height(), 240)
        self.assertTrue((self.game_dir / 'versions/1.20.1').exists())
        controller, dialog = self.open_confirmation()
        self.snapshot('instance-delete-confirmation', dialog)
        self.delete_and_wait(controller, dialog)
        self.assertFalse((self.game_dir / 'versions/1.20.1').exists())
        self.assert_no_qml_errors()

    def test_selected_instance_and_last_instance_refresh_header_safely(self):
        controller = self.window.version_page.versions_page.controller
        identities = [item['version'] for item in controller.view['versions']]
        for identity in identities:
            controller.selectVersion(identity)
            controller, dialog = self.open_confirmation(identity)
            self.delete_and_wait(controller, dialog)
            remaining = [item['version'] for item in controller.view['versions']]
            self.assertNotIn(identity, remaining)
            if remaining:
                self.assertIn(self.manager.get_setting('minecraft.version.enable'), remaining)
        self.assertFalse(controller.view['versions'])
        self.assertFalse(self.manager.get_setting('minecraft.version.enable'))
        self.assertTrue(self.window.isVisible())
        self.assert_no_qml_errors()

    def test_core_jar_reference_blocks_deletion_and_null_room_metadata_is_safe(self):
        path = self.game_dir / 'versions/1.21.8/1.21.8.json'
        path.write_text(json.dumps(dict(id='1.21.8', jar='1.20.1', buggcraftRoom=None)), encoding='utf-8')
        controller, dialog = self.open_confirmation()
        self.delete_and_wait(controller, dialog)
        self.assertIn('依赖', dialog.controller.detail)
        self.assertTrue((self.game_dir / 'versions/1.20.1').exists())
        path.write_text(json.dumps(dict(id='1.21.8', buggcraftRoom=None)), encoding='utf-8')
        controller, dialog = self.open_confirmation()
        self.delete_and_wait(controller, dialog)
        self.assertFalse((self.game_dir / 'versions/1.20.1').exists())
        self.assert_no_qml_errors()
