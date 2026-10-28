"""Player-facing regressions: deletion feedback and resource-level progress."""
import json
import shutil
import threading
from unittest.mock import Mock, patch
from types import SimpleNamespace

from PySide6.QtTest import QTest
from _qml_test_support import LauncherQmlCase, Qt, qt_mouse_click
from PySide6.QtCore import QPoint


class UiRefinementTests(LauncherQmlCase):
    def test_only_the_dialog_header_starts_a_window_drag(self):
        self.window.switch_pages('实例')
        controller = self.window.version_page.versions_page.controller
        controller.action('1.20.1', 'deleteVersion')
        self.pump()
        dialog = controller._delete_dialog
        move = Mock()
        with patch.object(dialog, 'windowHandle', return_value=SimpleNamespace(startSystemMove=move)):
            qt_mouse_click(dialog.quick, QPoint(30, 15))
            qt_mouse_click(dialog.quick, QPoint(130, 35))
            self.assertEqual(move.call_count, 2)
            qt_mouse_click(dialog.quick, QPoint(120, 110))
            self.assertEqual(move.call_count, 2)
        self.click(dialog.host, 'dialog-action-0')
        self.assert_no_qml_errors()

    def test_delete_stays_open_while_working_and_shows_os_error_before_retry(self):
        self.window.switch_pages('实例')
        controller = self.window.version_page.versions_page.controller
        controller.action('1.20.1', 'deleteVersion')
        self.pump()
        dialog = controller._delete_dialog
        started, release = threading.Event(), threading.Event()

        def locked(*args, **kwargs):
            started.set()
            release.wait(3)
            raise PermissionError('session.lock 正被另一个程序使用（WinError 32）')

        with patch('ui.pages.qml_instances.delete_minecraft_version', side_effect=locked):
            try:
                self.click(dialog.host, 'dialog-action-1')
                self.wait_until(started.is_set)
                self.assertTrue(dialog.controller.working)
                self.assertFalse(self.item(dialog.host, 'dialog-action-0').isEnabled())
                QTest.keyClick(dialog.quick, Qt.Key_Escape)
                self.pump()
                self.assertTrue(dialog.isVisible())
                self.snapshot('delete-in-progress', dialog)
            finally:
                release.set()
            self.wait_until(lambda: controller._delete_worker is None)
        self.assertIs(controller._delete_dialog, dialog)
        self.assertIn('session.lock', self.item(dialog.host, 'dialog-detail').property('text'))
        self.assertIn('WinError 32', dialog.controller.detail)
        self.assertFalse(self.item(dialog.host, 'dialog-action-1').property('danger'))
        self.snapshot('delete-error-and-retry', dialog)
        self.click(dialog.host, 'dialog-action-1')
        self.wait_until(lambda: controller._delete_dialog is None)
        self.assertFalse((self.game_dir / 'versions/1.20.1').exists())
        self.assert_no_qml_errors()

    def test_single_long_version_fits_its_popup_without_empty_bottom_row(self):
        for path in (self.game_dir / 'versions').iterdir():
            shutil.rmtree(path)
        identity = '永生-公测V1.1d（拖入启动器即可自动下载）'
        path = self.game_dir / 'versions' / identity / (identity + '.json')
        path.parent.mkdir()
        path.write_text(json.dumps(dict(id=identity)), encoding='utf-8')
        header = self.window.title_bar
        header.refresh_versions()
        self.click(header, 'version-picker')
        popup = header._picker
        option = self.item(popup.host, 'choice-option-0')
        title = self.item(popup.host, 'version-option-title-0')
        self.assertEqual(popup.height(), 69)
        self.assertEqual(option.height(), 59)
        self.assertLess(title.width(), option.width() - 70)
        self.assertGreater(title.width(), 80)
        self.snapshot('single-version-picker', popup)
        QTest.keyClick(popup.quick, Qt.Key_Enter)
        self.pump()
        self.assertEqual(self.manager.get_setting('minecraft.version.enable'), identity)
        self.assert_no_qml_errors()

    def test_file_progress_handles_large_files_duplicates_and_live_log_switching(self):
        downloads = self.window.download_page
        page = downloads.tasks_page
        task = dict(id='file-fixture', version='示例整合包', game_dir=str(self.game_dir),
                    state='进行中', progress=3, maximum=12, logs=['正在准备游戏依赖…'])
        page._tasks = [task]
        examples = [
            dict(key='mods/example.jar', name='example.jar', path='mods/example.jar',
                 done=5 * 1024 ** 3, total=10 * 1024 ** 3, state='downloading'),
            dict(key='libraries/example.jar', name='example.jar', path='libraries/example.jar',
                 done=2048, total=2048, state='cached'),
            dict(key='mods/broken.jar', name='broken.jar', path='mods/broken.jar',
                 done=800, total=2048, state='failed', error='文件校验失败'),
            dict(key='assets/texture.png', name='minecraft/textures/texture.png', path='assets/objects/texture',
                 done=10000, total=32000, state='verifying'),
        ]
        for event in examples:
            page.update_file_event('file-fixture', event)
        self.assertEqual(len(task['files']), 4)
        self.assertEqual(task['files'][0]['done'], 5 * 1024 ** 3)
        page.refresh_tasks()
        downloads.on_progress_clicked()
        self.pump(120)
        self.click(page.host, 'task-log-file-fixture')
        listing = self.item(page.host, 'task-log-files')
        self.assertEqual(listing.property('count'), 4)
        self.snapshot('download-file-progress')
        page.update_file_event('file-fixture', dict(examples[0], done=10 * 1024 ** 3, state='verified'))
        self.pump(550)
        self.assertTrue(any(item['key'] == 'mods/example.jar' and item['state'] == 'verified'
                            for item in page.view_controller.currentFiles))
        self.click(page.host, 'log-text-tab')
        self.assertFalse(listing.isVisible())
        self.assertIn('正在准备', page.view_controller.logLines[0])
        self.snapshot('download-text-log')
        self.click(page.host, 'log-files-tab')
        self.assertTrue(listing.isVisible())
        self.assert_no_qml_errors()

    def test_thousands_of_resource_files_keep_only_visible_progress_rows(self):
        downloads = self.window.download_page
        page = downloads.tasks_page
        task = dict(id='many', version='1.20.1', game_dir=str(self.game_dir),
                    state='进行中', progress=0, maximum=3000, logs=[], files=[
                        dict(key=str(i), name='resource-' + str(i), done=0, total=100, state='pending')
                        for i in range(3000)])
        page._tasks = [task]
        page.refresh_tasks()
        downloads.on_progress_clicked()
        self.pump(120)
        self.click(page.host, 'task-log-many')
        listing = self.item(page.host, 'task-log-files')
        self.assertEqual(listing.property('count'), 3000)
        content = listing.property('contentItem')
        self.assertLess(len(content.childItems()), 30)
        listing.setProperty('contentY', listing.property('contentHeight') - listing.height())
        self.pump()
        self.assertLess(len(content.childItems()), 30)
        self.assert_no_qml_errors()
