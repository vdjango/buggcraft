from unittest.mock import patch
import json
import zipfile
from _qml_test_support import LauncherQmlCase


class InstanceModpackEntryTests(LauncherQmlCase):
    def test_export_is_cancellable_while_qt_remains_responsive(self):
        import threading
        from PySide6.QtCore import QTimer
        from core.modpacks import export_pack as real_export
        instance = self.game_dir / 'versions/1.21.8'
        metadata = instance / '1.21.8.json'
        metadata.write_text(json.dumps(dict(id='1.21.8', clientVersion='1.21.8')), encoding='utf-8')
        (instance / 'config').mkdir()
        (instance / 'config/settings.txt').write_bytes(b'portable-content' * 200000)
        archive = self.directory / 'cancelled.buggpack'
        started, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        worker_threads, ticks = [], []
        timer = QTimer()
        timer.setInterval(10)
        timer.timeout.connect(lambda: ticks.append(threading.get_ident()))
        timer.start()
        self.addCleanup(timer.stop)
        def gated_export(*args, **kwargs):
            report = kwargs['progress']
            def progress(label, done, total):
                report(label, done, total)
                if label.startswith('正在打包') and not started.is_set():
                    worker_threads.append(threading.get_ident())
                    started.set()
                    if not release.wait(10):
                        raise TimeoutError('UI did not respond while exporting')
            kwargs['progress'] = progress
            return real_export(*args, **kwargs)
        self.window.switch_pages('实例')
        page = self.window.version_page.versions_page
        self.pump()
        with patch('ui.pages.qml_instances.export_pack', side_effect=gated_export), \
                patch('ui.pages.qml_instances.QFileDialog.getSaveFileName', return_value=(str(archive), 'Buggcraft package')):
            self.click(page, 'instance-export-1.21.8')
            dialog = page.controller._export_dialog
            self.snapshot('modpack-export-modes', dialog)
            self.click(dialog.host, 'dialog-action-0')
            self.wait_until(started.is_set)
            before = len(ticks)
            self.wait_until(lambda: len(ticks) > before + 2)
            self.assertNotEqual(worker_threads[0], threading.get_ident())
            self.snapshot('modpack-export-progress', dialog)
            self.click(dialog.host, 'dialog-action-0')
            self.assertTrue(page.controller._export_worker.cancel.is_set())
            release.set()
            self.wait_until(lambda: page.controller._export_worker is None)
        self.assertFalse(archive.exists())
        self.assertTrue(dialog.isVisible())
        self.assertEqual(dialog.controller.message, '导出已取消')
        self.click(dialog.host, 'dialog-action-0')
        self.wait_until(lambda: page.controller._export_dialog is None)
        self.assert_no_qml_errors()

    def test_buggpack_drag_drop_opens_actual_import_form(self):
        from PySide6.QtCore import QMimeData, QPoint, QPointF, QUrl, Qt
        from PySide6.QtGui import QDragEnterEvent, QDropEvent
        from PySide6.QtWidgets import QApplication
        from core.modpacks import export_pack
        archive = self.directory / 'dropped.buggpack'
        export_pack(self.game_dir, '1.21.8', archive)
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(archive))])
        enter = QDragEnterEvent(QPoint(100, 100), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        drop = QDropEvent(QPointF(100, 100), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        QApplication.sendEvent(self.window.started_page.quick, enter)
        self.assertTrue(enter.isAccepted())
        QApplication.sendEvent(self.window.started_page.quick, drop)
        self.pump(100)
        controller = self.window.download_page.content_page.controller
        self.wait_until(lambda: not controller.pack_inspecting)
        self.assertEqual(controller.pack_path, str(archive.resolve()))
        self.assertEqual(controller.view, 'import')
        self.assert_no_qml_errors()

    def test_export_button_writes_buggcraft_pack_from_real_instance_row(self):
        instance = self.game_dir / 'versions' / '1.21.8'
        metadata = json.loads((instance / '1.21.8.json').read_text(encoding='utf-8'))
        metadata.update(clientVersion='1.21.8', buggcraftModpack={
            'name': 'UI 导出包', 'version': '1', 'minecraft': '1.21.8',
            'loader': '', 'loaderVersion': '',
        })
        (instance / '1.21.8.json').write_text(json.dumps(metadata), encoding='utf-8')
        (instance / 'config').mkdir()
        (instance / 'config' / 'ui-export.json').write_text('{"ok":true}', encoding='utf-8')
        archive = self.directory / 'ui-export.buggpack'
        self.window.switch_pages('实例')
        page = self.window.version_page.versions_page
        self.pump()
        with patch('ui.pages.qml_instances.QFileDialog.getSaveFileName',
                   return_value=(str(archive), 'Buggcraft package')):
            self.assertIsNotNone(self.item(page, 'instance-export-1.21.8'))
            self.click(page, 'instance-export-1.21.8')
            dialog = page.controller._export_dialog
            self.assertIsNotNone(dialog)
            self.click(dialog.host, 'dialog-action-0')
        self.wait_until(lambda: page.controller._export_worker is None)
        self.assertTrue(archive.is_file())
        with zipfile.ZipFile(archive) as packaged:
            self.assertIn('buggcraft.pack.json', packaged.namelist())
            self.assertEqual(packaged.read('files/config/ui-export.json'), b'{"ok":true}')
        self.assertIn('整合包已导出', page.controller.view['status'])
        self.assertIs(page.controller._export_dialog, dialog)
        self.assertTrue(dialog.isVisible())
        self.assertEqual(dialog.controller.actions, ['关闭'])
        self.snapshot('modpack-export-complete', dialog)
        self.click(dialog.host, 'dialog-action-0')
        self.wait_until(lambda: page.controller._export_dialog is None)

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
