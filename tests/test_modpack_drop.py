"""Native file drops above every QML page use the shared import page."""
import json
from zipfile import ZipFile

from _qml_test_support import LauncherQmlCase
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtQuickWidgets import QQuickWidget


class ModpackDropTests(LauncherQmlCase):
    def test_slow_inspection_keeps_ui_responsive_and_late_result_cannot_replace_new_file(self):
        import threading
        from unittest.mock import patch
        from PySide6.QtCore import QTimer
        from core.modpacks import inspect_pack as real_inspect
        archives = []
        for name in ('slow', 'current'):
            archive = self.directory / (name + '.mrpack')
            with ZipFile(archive, 'w') as bundle:
                bundle.writestr('modrinth.index.json', json.dumps(dict(
                    formatVersion=1, game='minecraft', name=name, versionId='1',
                    dependencies={'minecraft': '1.20.1'}, files=[])))
            archives.append(archive)
        entered, release, completed = (threading.Event() for _ in range(3))
        self.addCleanup(release.set)
        threads, ticks = [], []
        timer = QTimer()
        timer.setInterval(10)
        timer.timeout.connect(lambda: ticks.append(True))
        timer.start()
        self.addCleanup(timer.stop)
        def inspect(path):
            threads.append(threading.get_ident())
            if str(path) == str(archives[0]):
                entered.set()
                if not release.wait(10):
                    raise TimeoutError('Inspection blocked the Qt event loop')
                completed.set()
            return real_inspect(path)
        page = self.window.download_page.content_page
        controller = page.controller
        with patch('ui.pages.download.content_browser.inspect_pack', side_effect=inspect):
            self.window.download_page.tasks_page.import_modpack(str(archives[0]))
            self.window.switch_pages('下载')
            self.wait_until(entered.is_set)
            self.assertFalse(self.item(page, 'start-pack-import').isEnabled())
            before = len(ticks)
            self.wait_until(lambda: len(ticks) > before + 2)
            self.assertTrue(all(thread != threading.get_ident() for thread in threads))
            controller.inspectPack(str(archives[1]))
            self.wait_until(lambda: not controller.pack_inspecting)
            self.assertIn('current', controller.pack_summary)
            release.set()
            self.wait_until(completed.is_set)
            self.assertTrue(controller.pool.waitForDone(2000))
            self.pump()
        self.assertEqual(controller.pack_path, str(archives[1]))
        self.assertIn('current', controller.pack_summary)
        self.assertNotIn('slow', controller.pack_summary)
        self.assertFalse(self.window.download_page.tasks_page._workers)
        self.assert_no_qml_errors()

    def test_drop_on_every_major_page_opens_and_inspects_same_form(self):
        for index, tab in enumerate(self.window.tab_names):
            archive = self.directory / f'dropped-{index}.MRPACK'
            with ZipFile(archive, 'w') as bundle:
                bundle.writestr('modrinth.index.json', json.dumps(dict(
                    formatVersion=1, game='minecraft', name='Dropped pack', versionId='1',
                    dependencies={'minecraft': '1.20.1'}, files=[])))
            self.window.switch_pages(tab)
            self.pump()
            current = self.window.content_stack.currentWidget()
            quick = current.findChild(QQuickWidget)
            target = quick or current
            self.assertTrue(target.acceptDrops())
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(str(archive))])
            for event in (QDragEnterEvent(QPoint(10, 10), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier),
                          QDragMoveEvent(QPoint(10, 10), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier),
                          QDropEvent(QPointF(10, 10), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)):
                self.app.sendEvent(target, event)
                self.assertTrue(event.isAccepted())
            self.pump()
            controller = self.window.download_page.content_page.controller
            self.assertEqual(controller.view, 'import')
            self.assertEqual(controller.pack_path, str(archive.resolve()))
            self.assertEqual(controller.pack_name, archive.stem)
            self.assertEqual(controller.pack_error, '')
            self.assertEqual(self.window.content_stack.currentIndex(), 1)
            self.assertIs(self.window.download_page.stack.currentWidget(), self.window.download_page.content_page)
            self.assertFalse(self.window.download_page.tasks_page._workers)
        self.assert_no_qml_errors()

    def test_invalid_archive_displays_existing_import_error_without_starting_task(self):
        archive = self.directory / 'invalid.zip'
        archive.write_bytes(b'not an archive')
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(archive))])
        enter = QDragEnterEvent(QPoint(1, 1), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        self.app.sendEvent(self.window, enter)
        self.app.sendEvent(self.window, QDropEvent(QPointF(1, 1), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier))
        self.pump()
        controller = self.window.download_page.content_page.controller
        self.wait_until(lambda: not controller.pack_inspecting)
        self.assertEqual(controller.view, 'import')
        self.assertEqual(controller.pack_path, '')
        self.assertTrue(controller.pack_error)
        self.assertFalse(self.window.download_page.tasks_page._workers)
