"""Download-page click acceptance, with isolated HTTP artifacts and real tasks.

Remote catalogue responses are fixtures. Production QML, workers, installers,
file verification and temporary instance directories remain active. These
tests do not assert that a fixture archive can run Minecraft.
"""
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import patch
from threading import Event
from contextlib import contextmanager

from PySide6.QtCore import QPoint, QPointF, QUrl, QMimeData
from PySide6.QtGui import QWheelEvent, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QApplication

from _qml_test_support import Qt, QTest, qt_mouse_click, qt_mouse_move
from test_client_ui_acceptance import ClientUiAcceptanceCase as _DownloadCase
from ui.pages.qml_games import GameCatalogueController

REAL_GAME_REFRESH = GameCatalogueController.refresh


class DownloadChecklistUiTests(_DownloadCase):
    KINDS = ("game", "mod", "resourcepack", "shader", "modpack")

    def setUp(self):
        super().setUp()
        self._subtest_failed = False
        from download_ui_fixtures import DownloadCatalogueFixtures
        self.catalogue = DownloadCatalogueFixtures(self.fixtures)
        self.addCleanup(self.catalogue.close)
        self._patch(patch("core.content.ContentCatalogue.search",
                          lambda _client, *a, **k: self.catalogue.search(*a, **k)))
        self._patch(patch("core.content.ContentCatalogue.versions",
                          lambda _client, *a, **k: self.catalogue.versions(*a, **k)))
        self._patch(patch("core.content.ContentCatalogue.project",
                          lambda _client, *a, **k: self.catalogue.project(*a, **k)))

    @contextmanager
    def subTest(self, **params):
        with super().subTest(**params):
            try:
                yield
            except BaseException:
                self._subtest_failed = True
                raise

    def finish_test(self):
        self._test_passed = not self._subtest_failed

    def tearDown(self):
        self.catalogue.close()
        for _started, release in self.fixtures.pauses.values():
            release.set()
        tasks = self.window.download_page.tasks_page
        for worker in list(tasks._workers.values()):
            worker.cancel_event.set()
        self.wait_for(lambda: not tasks._workers, "download workers finish before disposing their UI")
        (self.output / "catalogue-requests.json").write_text(
            json.dumps(self.catalogue.calls, ensure_ascii=False, indent=2), encoding="utf-8")
        (self.output / "http-requests.json").write_text(
            json.dumps(self.fixtures.requests, indent=2), encoding="utf-8")
        super().tearDown()

    def item(self, page, name):
        # The embedded content catalogue and the hidden Minecraft catalogue
        # deliberately reuse CatalogueList. Resolve the visible control.
        root = page.quick.rootObject()
        self.assertIsNotNone(root)
        def visible_match(item):
            if item.objectName() == name and item.isVisible():
                return item
            for child in item.childItems():
                found = visible_match(child)
                if found is not None:
                    return found
            return None
        found = visible_match(root)
        return found if found is not None else super().item(page, name)

    def open_downloads(self):
        self.navigate("launcher-nav-download")
        downloads = self.window.download_page
        page = downloads.games_page
        if downloads.stack.currentWidget() is not page:
            self.click_ui(downloads.tab_buttons_widget, "navigation-option-0")
        page.ensure_loaded()
        while page.controller.category == "game" and page.controller.install_view != "catalogue":
            self.click_ui(page, "game-install-back")
        return page

    def choose_filter(self, page, index, name="catalogue-filter"):
        self.click_ui(page, name)
        self.key_ui(page, Qt.Key_Home, name + "-first")
        for _ in range(index):
            self.key_ui(page, Qt.Key_Down, name + "-next")
        self.key_ui(page, Qt.Key_Return, name + "-confirm")

    def seed_games(self):
        page = self.open_downloads()
        page.controller.versions = [
            {"id": "1.21.8", "type": "release"},
            {"id": "1.20.1", "type": "release"},
            {"id": "26w01a", "type": "snapshot"},
            {"id": "b1.7.3", "type": "old_beta"},
            {"id": "a1.2.6", "type": "old_alpha"},
        ]
        page.controller.changed.emit()
        self.pause_ui()
        return page

    def open_kind(self, kind):
        page = self.open_downloads()
        controller = self.window.download_page.content_page.controller
        if page.controller.category != "game" and controller.view == "detail":
            self.click_ui(page, "content-back")
        self.click_ui(page, "content-kind-" + str(self.KINDS.index(kind)))
        self.wait_for(lambda: not controller.busy, kind + " catalogue settles")
        return page, controller

    def open_project(self, kind):
        page, controller = self.open_kind(kind)
        self.click_ui(page, "content-project-0")
        self.wait_for(lambda: not controller.busy and controller.view == "detail",
                      kind + " project and version responses arrive")
        return page, controller

    def search_content(self, page, controller, query, enter=True):
        self.text_ui(page, "catalogue-query", query)
        if enter:
            self.key_ui(page, Qt.Key_Return, "content-search-enter")
        else:
            self.click_ui(page, "catalogue-search")
        self.wait_for(lambda: not controller.busy, "content search completes: " + query)

    def content_dialog(self, kind):
        page, controller = self.open_project(kind)
        self.click_ui(page, "content-detail-tab-1")
        self.click_ui(page, "content-version-0")
        self.click_ui(page, "download-content-version")
        self.wait_for(lambda: controller._download_dialog is not None
                      and controller._download_dialog.isVisible(), "download confirmation is visible")
        return page, controller, controller._download_dialog

    def finished_task(self, task=None, state="已完成"):
        tasks = self.window.download_page.tasks_page
        task = tasks._tasks[0] if task is None else task
        self.wait_for(lambda: task["state"] not in tasks.ACTIVE and task["id"] not in tasks._workers,
                      "real download worker finishes: " + task["version"], timeout=25000)
        self.check(task["state"] == state,
                   "download final state: " + task["state"] + " " + task.get("error", ""))
        return task

    def scroll_list_to_end(self, page, name, condition):
        import time
        for _ in range(45):
            if condition():
                return
            # Project details arrive asynchronously and resize the version list.
            # Aim each wheel event at its current viewport, as a real pointer
            # would, rather than retaining coordinates from the first layout.
            item = self.item(page, name)
            point = item.mapToScene(item.boundingRect().center()).toPoint()
            qt_mouse_move(page.quick, point)
            event = QWheelEvent(QPointF(point), QPointF(page.quick.mapToGlobal(point)), QPoint(),
                                QPoint(0, -720), Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
            event.setTimestamp(int(time.monotonic() * 1000))
            self.record("wheel", name, "-720")
            QApplication.sendEvent(page.quick, event)
            self.pause_ui()
        self.screenshot_ui('scroll-failed-' + name)
        metrics = {key: item.property(key) for key in
                   ('contentY', 'contentHeight', 'height', 'count', 'hasMore', 'loading', 'appendPending')}
        self.record('scrollFailure', name, json.dumps(metrics))
        self.fail("Scrolling did not load more rows: " + name + ' ' + repr(metrics))

    def reveal_control(self, page, name):
        import time
        for _ in range(30):
            item = self.item(page, name)
            point = item.mapToScene(item.boundingRect().center())
            if 85 < point.y() < page.quick.height() - 70:
                return
            delta = -240 if point.y() >= page.quick.height() - 70 else 240
            position = QPoint(page.quick.width() // 2, page.quick.height() // 2)
            event = QWheelEvent(QPointF(position), QPointF(page.quick.mapToGlobal(position)), QPoint(),
                                QPoint(0, delta), Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
            event.setTimestamp(int(time.monotonic() * 1000))
            self.record("wheel", name, str(delta))
            QApplication.sendEvent(page.quick, event)
            self.pause_ui()
        self.fail("Control not reachable by scrolling: " + name)

    def pause_file(self, filename):
        import random
        from client_ui_fixtures import archive_bytes
        self.fixtures.payloads[filename] = archive_bytes({"fixture.txt": "UI streaming fixture",
            "padding.bin": random.Random(87).randbytes(2 * 1024 * 1024)})
        started, release = Event(), Event()
        self.fixtures.pauses[filename] = started, release
        return started, release

    def open_import(self, path=None):
        page = self.open_downloads()
        controller = self.window.download_page.content_page.controller
        if page.controller.category != "game" and controller.view == "detail":
            self.click_ui(page, "content-back")
        with patch("ui.pages.download.content_browser.QFileDialog.getOpenFileName",
                   return_value=(str(path or self.fixtures.pack_path), "Modpack")):
            self.click_ui(page, "download-import-pack")
        host = self.window.download_page.content_page
        self.check(controller.view == "import", "import entry opens its real form")
        self.wait_for(lambda: not controller.pack_inspecting, 'pack metadata inspection completes off UI thread')
        return host, controller

    def test_modpack_import_mrpack_and_curseforge_zip_name_and_instance_refresh(self):
        from client_ui_fixtures import archive_bytes
        cf = self.directory / "curseforge-pack.zip"
        cf.write_bytes(archive_bytes({"manifest.json": json.dumps({"manifestType": "minecraftModpack",
            "manifestVersion": 1, "name": "CF Test Pack", "version": "1.0", "author": "Fixture",
            "minecraft": {"version": "1.21.8", "modLoaders": []}, "files": [], "overrides": "overrides"}),
            "overrides/config/curseforge-ui.txt": "installed from ZIP"}))
        for index, archive in enumerate((self.fixtures.pack_path, cf)):
            with self.subTest(archive=archive.suffix):
                host, controller = self.open_import(archive)
                self.check(controller.pack_path == str(archive.resolve()) and bool(controller.pack_name)
                           and "1.21.8" in controller.pack_summary, "file selection reads pack metadata and proposes a name")
                identity = "download-import-" + str(index)
                self.text_ui(host, "pack-instance-name", identity)
                self.click_ui(host, "start-pack-import")
                task = self.finished_task()
                target = self.game_dir / "versions" / identity
                name = "ui-acceptance.json" if index == 0 else "curseforge-ui.txt"
                self.check(task["version"] == identity and (target / "config" / name).is_file()
                           and (target / (identity + ".json")).is_file(), "real importer creates the named instance and overrides")
                self.navigate("instances-button")
                self.click_ui(self.window.version_page.versions_page, "instance-row-" + identity)
                self.navigate("launcher-nav-home")
                self.check(self.window.started_page.controller.view["launchSubtitle"] == identity,
                           "imported instance can be selected from the real list immediately")
                self.screenshot_ui("download-imported-home-" + str(index))
        self.assert_no_qml_errors()
        self.finish_test()

    def test_import_cancel_corrupt_missing_manifest_and_invalid_names_recover(self):
        from client_ui_fixtures import archive_bytes
        host, controller = self.open_import()
        initial = controller.pack_path
        with patch("ui.pages.download.content_browser.QFileDialog.getOpenFileName", return_value=("", "")):
            self.click_ui(host, "choose-pack-file")
        self.check(controller.pack_path == initial, "canceling file selection preserves the inspected pack")
        broken = self.directory / "corrupt.zip"
        broken.write_bytes(b"not a zip")
        broken_mrpack = self.directory / "corrupt.mrpack"
        broken_mrpack.write_bytes(b"not a zip")
        empty = self.directory / "no-manifest.zip"
        empty.write_bytes(archive_bytes({"README.txt": "No modpack manifest"}))
        empty_mrpack = self.directory / "no-manifest.mrpack"
        empty_mrpack.write_bytes(archive_bytes({"README.txt": "No modpack manifest"}))
        resource = self.directory / "ordinary-resource.zip"
        resource.write_bytes(archive_bytes({"pack.mcmeta": '{"pack":{"pack_format":64,"description":"resource"}}'}))
        for archive in (broken, broken_mrpack, empty, empty_mrpack, resource):
            with self.subTest(archive=archive.name):
                with patch("ui.pages.download.content_browser.QFileDialog.getOpenFileName", return_value=(str(archive), "ZIP")):
                    self.click_ui(host, "choose-pack-file")
                self.wait_for(lambda: not controller.pack_inspecting, 'invalid pack inspection completes')
                self.check(bool(controller.pack_error) and not controller.pack_path
                           and not self.item(host, "start-pack-import").isEnabled(),
                           "unreadable or non-modpack ZIP shows an error and disables import")
        with patch("ui.pages.download.content_browser.QFileDialog.getOpenFileName", return_value=(str(self.fixtures.pack_path), "MRPACK")):
            self.click_ui(host, "choose-pack-file")
        self.wait_for(lambda: not controller.pack_inspecting, 'valid pack inspected after errors')
        for name in ("", "   ", "bad/name", "1.21.8"):
            with self.subTest(name=name):
                self.text_ui(host, "pack-instance-name", name)
                if not name.strip():
                    self.check(not self.item(host, "start-pack-import").isEnabled(), "blank instance name cannot be submitted")
                else:
                    self.click_ui(host, "start-pack-import")
                    if name == '1.21.8':
                        dialog = controller._import_conflict_dialog
                        self.check(dialog is not None and not self.window.download_page.tasks_page._tasks,
                                   'occupied name offers rename without starting a task')
                        self.click_ui(dialog, 'dialog-action-1')
                    else:
                        self.check(bool(controller.pack_error) and not self.window.download_page.tasks_page._tasks,
                                   "invalid instance name is rejected without a task")
        self.text_ui(host, "pack-instance-name", "recovered-name")
        self.click_ui(host, "start-pack-import")
        self.finished_task()
        self.screenshot_ui("download-import-name-recovered")
        host, controller = self.open_import()
        self.click_ui(host, "pack-import-back")
        self.check(controller.view == "browse" and self.window.download_page.stack.currentWidget() is self.window.download_page.games_page,
                   "Back exits import and returns to the visible downloads page")
        self.assert_no_qml_errors()
        self.finish_test()

    def test_drop_modpack_over_home_and_qml_controls_opens_inspected_form(self):
        for widget in (self.window, self.window.started_page.quick):
            with self.subTest(target=widget.__class__.__name__):
                self.navigate("launcher-nav-home")
                mime = QMimeData()
                mime.setUrls([QUrl.fromLocalFile(str(self.fixtures.pack_path))])
                enter = QDragEnterEvent(QPoint(100, 100), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
                drop = QDropEvent(QPointF(100, 100), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
                self.record("dragEnter", "launcher-modpack", str(self.fixtures.pack_path))
                QApplication.sendEvent(widget, enter)
                self.check(enter.isAccepted(), "launcher accepts a single local modpack drop")
                self.record("drop", "launcher-modpack", str(self.fixtures.pack_path))
                QApplication.sendEvent(widget, drop)
                self.wait_for(lambda: self.window.download_page.content_page.controller.view == "import"
                              and self.window.current_tab == 1, "drop opens the real import form")
                controller = self.window.download_page.content_page.controller
                self.wait_for(lambda: not controller.pack_inspecting, 'dropped pack inspection completes')
                self.check(controller.pack_path == str(self.fixtures.pack_path.resolve()) and bool(controller.pack_name),
                           "drop invokes production inspection and fills the instance name")
                self.text_ui(self.window.download_page.content_page, "pack-instance-name", "dropped-pack")
        self.click_ui(self.window.download_page.content_page, "start-pack-import")
        self.finished_task()
        self.check((self.game_dir / "versions/dropped-pack/config/ui-acceptance.json").is_file(),
                   "the dropped pack can be imported through its form")
        self.screenshot_ui("download-dropped-pack-installed")
        self.assert_no_qml_errors()
        self.finish_test()

    def test_duplicate_import_renames_without_overwriting_existing_instance(self):
        host, controller = self.open_import()
        original = self.game_dir / 'versions' / 'duplicate-pack'
        original.mkdir()
        marker = original / 'keep.txt'
        marker.write_text('original instance', encoding='utf-8')
        self.text_ui(host, 'pack-instance-name', 'duplicate-pack')
        self.click_ui(host, 'start-pack-import')
        dialog = controller._import_conflict_dialog
        self.check(dialog is not None and dialog.isVisible(), 'duplicate import offers a naming choice')
        self.check(dialog.controller.data['name'] == 'duplicate-pack-2', 'unused instance name is proposed')
        self.text_ui(dialog, 'import-conflict-name', 'duplicate-copy')
        self.click_ui(dialog, 'dialog-action-0')
        task = self.finished_task()
        self.check(task['version'] == 'duplicate-copy'
                   and (self.game_dir / 'versions/duplicate-copy/config/ui-acceptance.json').is_file(),
                   'renamed import executes the real importer')
        self.check(marker.read_text(encoding='utf-8') == 'original instance',
                   'duplicate import preserves the original instance')
        self.screenshot_ui('download-duplicate-import-completed')
        self.assert_no_qml_errors()
        self.finish_test()

    def test_duplicate_import_cancel_and_occupied_replacement_start_no_task(self):
        host, controller = self.open_import()
        markers = []
        for name in ('occupied-pack', 'occupied-pack-2'):
            directory = self.game_dir / 'versions' / name
            directory.mkdir()
            marker = directory / 'keep.txt'
            marker.write_text(name, encoding='utf-8')
            markers.append(marker)
        self.text_ui(host, 'pack-instance-name', 'occupied-pack')
        self.click_ui(host, 'start-pack-import')
        dialog = controller._import_conflict_dialog
        self.check(dialog.controller.data['name'] == 'occupied-pack-3', 'name proposal skips both existing instances')
        self.text_ui(dialog, 'import-conflict-name', 'occupied-pack-2')
        self.click_ui(dialog, 'dialog-action-0')
        self.check(dialog.isVisible() and '已存在' in dialog.controller.detail,
                   'occupied replacement is rejected inside the naming dialog')
        self.check(not self.window.download_page.tasks_page._workers, 'rejected name creates no install task')
        self.click_ui(dialog, 'dialog-action-1')
        self.wait_for(lambda: controller._import_conflict_dialog is None, 'cancel dismisses rename dialog')
        self.check(not self.window.download_page.tasks_page._workers, 'cancelling duplicate import creates no task')
        for marker in markers:
            self.check(marker.read_text(encoding='utf-8') == marker.parent.name, 'existing instance stays untouched')
        self.assert_no_qml_errors()
        self.finish_test()

    def test_import_failure_resume_reuses_same_task_and_preserves_existing_instances(self):
        self.fixtures.failures.add("client.jar")
        host, _controller = self.open_import()
        self.text_ui(host, "pack-instance-name", "resumable-pack")
        self.click_ui(host, "start-pack-import")
        task = self.finished_task(state="失败")
        self.check("404" in task["error"] and not (self.game_dir / "versions/resumable-pack").exists(),
                   "failed import retains the reason and does not publish an incomplete instance")
        self.fixtures.failures.clear()
        tasks = self.window.download_page.tasks_page
        self.click_ui(tasks, "task-action-" + task["id"])
        self.finished_task(task)
        self.check(len(tasks._tasks) == 1 and task.get("resumed_at")
                   and (self.game_dir / "versions/resumable-pack/config/ui-acceptance.json").is_file(),
                   "Continue installation resumes the original task and completes its instance")
        self.check((self.game_dir / "versions/1.20.1/1.20.1.json").is_file(), "resuming does not delete an unrelated existing instance")
        self.screenshot_ui("download-import-resumed")
        self.assert_no_qml_errors()
        self.finish_test()

    def exported_compact_pack(self):
        """Export with production code, then import that exact archive via QML."""
        from core.content_records import record_content
        from core.modpacks import export_pack
        source = self.directory / 'export-source'
        instance = source / 'versions/1.21.8'
        instance.mkdir(parents=True)
        (instance / '1.21.8.json').write_text(json.dumps(self.fixtures.metadata), encoding='utf-8')
        resources = {'mods/resume-mod.jar': b'verified mod bytes\n' * 32768,
                     'resourcepacks/resume-resources.zip': b'resource pack bytes' * 100,
                     'shaderpacks/resume-shader.zip': b'shader pack bytes' * 100}
        for relative, payload in resources.items():
            target = instance / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            record_content(instance, target, ['https://cdn.modrinth.com/data/fixture/' + target.name])
            self.fixtures.payloads[target.name] = payload
        (instance / 'config').mkdir()
        (instance / 'config/exported.txt').write_text('production export', encoding='utf-8')
        archive = self.directory / 'exported-compact.buggpack'
        export_pack(source, '1.21.8', archive)
        original_route = self.fixtures.route
        def route(downloader, url):
            if url.startswith('https://cdn.modrinth.com/data/fixture/'):
                return [f'http://127.0.0.1:{self.fixtures.server.server_port}/' + url.rsplit('/', 1)[-1]]
            return original_route(downloader, url)
        self._patch(patch('core.downloads.MinecraftDownloader.urls', route))
        return archive, resources

    def test_own_export_import_metadata_error_is_readable_and_ui_retry_completes(self):
        archive, resources = self.exported_compact_pack()
        original = self.fixtures.payloads['manifest.json']
        self.fixtures.payloads['manifest.json'] = b'<html>temporarily unavailable</html>'
        host, _ = self.open_import(archive)
        self.text_ui(host, 'pack-instance-name', 'own-pack-json-retry')
        self.click_ui(host, 'start-pack-import')
        task = self.finished_task(state='失败')
        self.check('Minecraft 版本列表' in task['error'] and '重试' in task['error']
                   and 'Expecting value' not in task['error'], 'metadata error names the failing item and offers retry')
        self.screenshot_ui('own-pack-readable-metadata-error')
        self.fixtures.payloads['manifest.json'] = original
        tasks = self.window.download_page.tasks_page
        self.click_ui(tasks, 'task-action-' + task['id'])
        self.finished_task(task)
        target = self.game_dir / 'versions/own-pack-json-retry'
        for name, payload in resources.items():
            self.check((target / name).read_bytes() == payload, 'own export resource restored: ' + name)
        self.check(len(tasks._tasks) == 1 and (target / 'config/exported.txt').is_file(),
                   'retry finishes the same task and publishes portable settings')
        self.assert_no_qml_errors()
        self.finish_test()

    def test_own_export_import_interrupted_resource_resumes_from_ui(self):
        archive, resources = self.exported_compact_pack()
        self.fixtures.truncations.add('resume-mod.jar')
        host, _ = self.open_import(archive)
        self.text_ui(host, 'pack-instance-name', 'own-pack-resume')
        self.click_ui(host, 'start-pack-import')
        task = self.finished_task(state='失败')
        partials = list(self.game_dir.rglob('resume-mod.jar.buggcraft-part'))
        self.check(len(partials) == 1 and 0 < partials[0].stat().st_size < len(resources['mods/resume-mod.jar']),
                   'interrupted import retains verified-identity partial bytes')
        offset = partials[0].stat().st_size
        self.fixtures.truncations.clear()
        tasks = self.window.download_page.tasks_page
        self.click_ui(tasks, 'task-action-' + task['id'])
        self.finished_task(task)
        requests = [row for row in self.fixtures.requests if row['file'] == 'resume-mod.jar']
        self.check(requests[-1]['range'] == f'bytes={offset}-', 'UI retry requests only the remaining resource bytes')
        target = self.game_dir / 'versions/own-pack-resume'
        for name, payload in resources.items():
            self.check((target / name).read_bytes() == payload, 'resumed resource verified: ' + name)
        self.check(len(tasks._tasks) == 1 and not partials[0].exists(), 'success clears checkpoint and keeps one history task')
        self.screenshot_ui('own-pack-import-resumed')
        self.assert_no_qml_errors()
        self.finish_test()

    def test_room_failed_download_history_button_reuses_task_and_file_rows(self):
        tasks = self.window.download_page.tasks_page
        calls = []
        def retry(task_id):
            calls.append(task_id)
            reused = tasks.track_room_preparation('Room configuration', self.game_dir, {'version': '1.21.8'}, Event(),
                                                   retry=retry, task_id=task_id)
            self.assertEqual(reused, task_id)
            tasks.room_preparation_event(task_id, dict(kind='manifest', files=[dict(name='mod.jar', key='mod.jar')]))
            tasks.room_preparation_event(task_id, dict(kind='download', name='mod.jar', key='mod.jar', state='verified', done=12, total=12))
            tasks.finish_room_preparation(task_id, True, '房间配置准备完成')
        task_id = tasks.track_room_preparation('Room configuration', self.game_dir, {'version': '1.21.8'}, Event(), retry=retry)
        tasks.room_preparation_event(task_id, dict(kind='manifest', files=[dict(name='old.jar', key='old.jar')]))
        tasks.room_preparation_event(task_id, dict(kind='download', name='old.jar', key='old.jar', state='failed'))
        tasks.finish_room_preparation(task_id, False, '下载中断，请重试')
        self.window.download_page.on_progress_clicked()
        self.check(self.item(tasks, 'task-action-' + task_id).property('text') == '重试下载', 'room failure exposes retry action')
        self.click_ui(tasks, 'task-action-' + task_id)
        self.check(calls == [task_id] and len(tasks._tasks) == 1, 'one UI click retries the existing room task')
        self.check(tasks._tasks[0]['state'] == '已完成' and tasks._tasks[0]['files'][0]['state'] == 'verified',
                   'retry updates new file rows and finishes successfully')
        self.assert_no_qml_errors()
        self.finish_test()

    def test_import_directory_permission_failure_keeps_instances_and_retries(self):
        import errno
        original_mkdir = Path.mkdir
        marker = self.game_dir / 'versions/1.20.1/keep-existing.txt'
        marker.write_text('existing instance', encoding='utf-8')
        host, _controller = self.open_import()
        self.text_ui(host, 'pack-instance-name', 'permission-retry-pack')

        def denied(path, *args, **kwargs):
            if path.parent.name == 'modpacks' and path.parent.parent.name == '.buggcraft-downloads':
                raise PermissionError(errno.EACCES, '整合包目录没有写入权限', str(path))
            return original_mkdir(path, *args, **kwargs)

        with patch.object(Path, 'mkdir', denied):
            self.click_ui(host, 'start-pack-import')
            task = self.finished_task(state='失败')
        self.check('没有写入权限' in task['error'] and not (self.game_dir / 'versions/permission-retry-pack').exists(),
                   'directory permission error reaches UI task without publishing a partial instance')
        tasks = self.window.download_page.tasks_page
        self.click_ui(tasks, 'task-log-' + task['id'])
        self.click_ui(tasks, 'log-text-tab')
        self.check('没有写入权限' in self.item(tasks, 'task-log-text').property('text'),
                   'import log retains the denied-directory cause')
        self.screenshot_ui('import-permission-denied-log')
        self.click_ui(tasks, 'task-log-close')
        self.click_ui(tasks, 'task-action-' + task['id'])
        self.finished_task(task)
        self.check((self.game_dir / 'versions/permission-retry-pack/config/ui-acceptance.json').is_file()
                   and marker.read_text(encoding='utf-8') == 'existing instance' and len(tasks._tasks) == 1,
                   'restoring permissions resumes original task and preserves unrelated instance')
        self.assert_no_qml_errors()
        self.finish_test()

    def test_api_choices_install_verified_files_in_selected_loader_instance(self):
        from types import SimpleNamespace
        from client_ui_fixtures import archive_bytes
        profiles = []
        for name in ('fabric-api.jar', 'qsl-qfapi.jar'):
            self.fixtures.payloads[name] = archive_bytes({'api-fixture.txt': name})

        def versions(_catalogue, project, game='', loader='', kind='mod', **kwargs):
            name = 'fabric-api.jar' if project['project_id'] == 'fabric-api' else 'qsl-qfapi.jar'
            record = dict(id=name, project_id=project['project_id'], name=name,
                          game_versions=[game], loaders=[loader], files=[self.fixtures.file(name)])
            return [record]

        def profile_response(url):
            profiles.append(url)
            loader = 'fabric' if 'fabricmc' in url else 'quilt'
            return SimpleNamespace(json=lambda: dict(id=loader + '-loader-0.16.9-1.21.8',
                inheritsFrom='1.21.8', mainClass='fixture.ApiLoader', libraries=[]))

        self._patch(patch('core.content.ContentCatalogue.versions', versions))
        self._patch(patch('core.loaders._response', profile_response))
        for loader, addons in (('Fabric', ('Fabric API',)), ('Quilt', ('Fabric API', 'QSL/QFAPI'))):
            page = self.seed_games()
            self.click_ui(page, 'install-1.21.8')
            self.reveal_control(page, 'component-' + loader)
            self.click_ui(page, 'component-' + loader)
            self.wait_for(lambda: not page.controller.loader_busy, 'loader choices arrive')
            self.click_ui(page, 'component-version-0')
            for addon in addons:
                self.reveal_control(page, 'component-' + addon)
                self.click_ui(page, 'component-' + addon)
                self.wait_for(lambda: not page.controller.loader_busy, 'compatible API versions arrive')
                self.click_ui(page, 'component-version-0')
            identity = loader.lower() + '-loader-0.16.9-1.21.8'
            self.click_ui(page, 'install-selected-game')
            task = self.finished_task()
            root = self.game_dir / 'versions' / identity
            expected = ['fabric-api.jar'] + (['qsl-qfapi.jar'] if loader == 'Quilt' else [])
            self.check(task['version'] == identity and (root / (identity + '.json')).is_file(),
                       'production loader installer publishes the selected loader instance')
            self.check(sorted(path.name for path in (root / 'mods').glob('*.jar')) == sorted(expected),
                       'only the selected APIs appear in the isolated loader mods directory')
            for name in expected:
                self.check((root / 'mods' / name).read_bytes() == self.fixtures.payloads[name],
                           'API content is actually downloaded and hash-verified: ' + loader + '/' + name)
                self.check(any(row['file'] == name for row in self.fixtures.requests),
                           'API file crosses real HTTP transport: ' + name)
            self.check(not (self.game_dir / 'mods').exists(), 'isolated API install does not write shared mods')
            self.screenshot_ui('installed-api-files-' + loader.lower())
        (self.output / 'api-profile-requests.json').write_text(json.dumps(profiles, indent=2), encoding='utf-8')
        self.assert_no_qml_errors()
        self.finish_test()

    def test_import_cancel_then_continue_installs_same_instance(self):
        started, release = Event(), Event()
        self.fixtures.pauses["client.jar"] = started, release
        host, _controller = self.open_import()
        self.text_ui(host, "pack-instance-name", "cancelled-pack")
        self.click_ui(host, "start-pack-import")
        tasks = self.window.download_page.tasks_page
        task = tasks._tasks[0]
        self.wait_for(started.is_set, "import is streaming its client dependency")
        self.click_ui(tasks, "task-action-" + task["id"])
        self.check(task["state"] == "正在取消", "import cancellation is visible")
        release.set()
        self.finished_task(task, "已取消")
        self.check(not (self.game_dir / "versions/cancelled-pack").exists(),
                   "canceling import does not publish a partial instance")
        self.fixtures.pauses.pop("client.jar")
        self.wait_for(lambda: self.item(tasks, "task-action-" + task["id"]).isEnabled(),
                      "Continue installation becomes available after cancellation")
        self.click_ui(tasks, "task-action-" + task["id"])
        self.finished_task(task)
        self.check(len(tasks._tasks) == 1, "Continue preserves the cancelled import's identity and history")
        self.navigate("instances-button")
        self.click_ui(self.window.version_page.versions_page, "instance-row-cancelled-pack")
        self.check((self.game_dir / "versions/cancelled-pack/config/ui-acceptance.json").is_file(),
                   "continued import completes its instance and appears in the list")
        self.screenshot_ui("download-import-cancel-continued")
        self.assert_no_qml_errors()
        self.finish_test()

    def test_downloaded_modpack_download_and_install_failures_resume_from_history(self):
        tasks = self.window.download_page.tasks_page
        for filename in ("ui-fixture-modpack.mrpack", "client.jar"):
            with self.subTest(stage=filename):
                if filename == "client.jar":
                    (self.game_dir / "versions/1.21.8/1.21.8.jar").unlink()
                self.fixtures.failures.add(filename)
                _page, _controller, dialog = self.content_dialog("modpack")
                self.click_ui(dialog, "content-download-confirm")
                task = self.finished_task(state="失败")
                self.check("404" in task["error"], "downloaded modpack failure retains its stage's HTTP error")
                self.click_ui(tasks, "task-log-" + task["id"])
                self.click_ui(tasks, "log-text-tab")
                self.check(filename in self.item(tasks, "task-log-text").property("text"),
                           "pack task log identifies the failed archive or client dependency")
                self.click_ui(tasks, "task-log-close")
                self.fixtures.failures.clear()
                self.click_ui(tasks, "task-action-" + task["id"])
                self.finished_task(task)
                self.check((self.game_dir / "versions" / task["version"] / "config/ui-acceptance.json").is_file(),
                           "Continue finishes the downloaded pack after either failure stage")
                self.screenshot_ui("download-pack-resumed-" + filename.replace(".", "-"))
        self.assert_no_qml_errors()
        self.finish_test()

    def test_version_file_failure_retries_first_page_for_every_kind(self):
        for kind in self.KINDS[1:]:
            with self.subTest(kind=kind):
                self.catalogue.version_error = True
                page, controller = self.open_project(kind)
                self.click_ui(page, "content-detail-tab-1")
                self.check(not controller.versions and "503" in controller.status,
                           "initial file list error remains visible")
                self.catalogue.version_error = False
                before = sum(call["action"] == "versions" for call in self.catalogue.calls)
                self.click_ui(page, "content-versions-retry")
                self.check(controller.busy or sum(call["action"] == "versions" for call in self.catalogue.calls) > before,
                           "Retry actually requests the initially failed file page")
                self.wait_for(lambda: not controller.busy and bool(controller.versions),
                              "file list retry recovers")
                self.click_ui(page, "content-version-0")
                self.check(controller.selected_version == 0, "recovered file is selectable")
                self.screenshot_ui("download-file-list-retry-" + kind)
        self.assert_no_qml_errors()
        self.finish_test()

    def test_hash_failure_disk_full_and_permission_error_reject_files_then_retry(self):
        import errno
        filename = "ui-fixture-shader.zip"
        original = self.fixtures.payloads[filename]
        for failure in ("hash", "disk-full", "permission"):
            with self.subTest(failure=failure):
                _page, _controller, dialog = self.content_dialog("shader")
                destination = Path(dialog.controller.data["target"]) / "shaderpacks" / filename
                destination.unlink(missing_ok=True)
                if failure == "hash":
                    self.fixtures.payloads[filename] = bytes([original[0] ^ 1]) + original[1:]
                    self.click_ui(dialog, "content-download-confirm")
                    task = self.finished_task(state="失败")
                    self.check("校验失败" in task["error"], "corrupt HTTP bytes fail production hash validation")
                    self.fixtures.payloads[filename] = original
                else:
                    original_open = Path.open
                    def fail_write(path, mode="r", *args, **kwargs):
                        if filename in path.name and "w" in mode:
                            if failure == "disk-full":
                                raise OSError(errno.ENOSPC, "No space left on device: fixture")
                            raise PermissionError(errno.EACCES, "Permission denied: fixture")
                        return original_open(path, mode, *args, **kwargs)
                    with patch.object(Path, "open", fail_write):
                        self.click_ui(dialog, "content-download-confirm")
                        task = self.finished_task(state="失败")
                    self.check(("space" if failure == "disk-full" else "Permission") in task["error"],
                               "filesystem failure reaches task history with its cause")
                self.check(not destination.exists(), "failed verification/write never publishes a final file")
                tasks = self.window.download_page.tasks_page
                self.click_ui(tasks, "task-action-" + task["id"])
                self.finished_task()
                self.check(destination.read_bytes() == original, "recovery retries into the correct verified final file")
                self.screenshot_ui("download-error-recovered-" + failure)
        self.assert_no_qml_errors()
        self.finish_test()

    def test_parallel_queue_duplicate_submission_and_clear_preserve_running_tasks(self):
        tasks = self.window.download_page.tasks_page
        tasks.pool.setMaxThreadCount(1)
        mod_started, mod_release = self.pause_file("ui-fixture-mod.jar")
        shader_started, shader_release = self.pause_file("ui-fixture-shader.zip")
        _page, _controller, dialog = self.content_dialog("mod")
        self.click_ui(dialog, "content-download-confirm")
        first = tasks._tasks[0]
        self.wait_for(mod_started.is_set, "first task is streaming")
        _page, _controller, dialog = self.content_dialog("shader")
        self.click_ui(dialog, "content-download-confirm")
        second = tasks._tasks[0]
        self.check(second["state"] == "等待中", "saturated worker pool queues a second real task")
        tasks.pool.setMaxThreadCount(2)
        self.wait_for(shader_started.is_set, "increasing capacity starts the queued task")
        self.check(first["state"] == second["state"] == "进行中",
                   "two independent HTTP downloads run concurrently")
        page, controller, duplicate = self.content_dialog("mod")
        self.click_ui(duplicate, "content-download-confirm")
        self.check(len(tasks._tasks) == 2 and "已存在" in duplicate.controller.data["error"],
                   "duplicate submission points to the active task without spawning another")
        self.click_ui(duplicate, "content-download-cancel")
        mod_release.set()
        self.finished_task(first)
        self.wait_for(shader_started.is_set, "queued task begins after the first finishes")
        self.navigate("launcher-nav-settings")
        self.navigate("launcher-nav-download")
        self.click_ui(self.window.download_page.tab_buttons_widget, "navigation-option-1")
        self.check(second["state"] == "进行中", "task remains active across page navigation")
        self.click_ui(tasks, "task-clear-ended")
        self.check([task["id"] for task in tasks._tasks] == [second["id"]],
                   "clearing ended history preserves the running task")
        shader_release.set()
        self.finished_task(second)
        self.choose_filter(tasks, 2)
        self.check(len(tasks.view_controller.tasks) == 1, "completed-task filter shows the remaining task")
        self.text_ui(tasks, "catalogue-query", "does-not-exist")
        self.check(not tasks.view_controller.tasks, "history search filters by task identity")
        self.text_ui(tasks, "catalogue-query", "")
        self.check(len(tasks.view_controller.tasks) == 1, "clearing history search restores matching tasks")
        self.click_ui(tasks, "task-clear-ended")
        self.check(not tasks._tasks and json.loads(Path(tasks.history_path).read_text(encoding="utf-8")) == [],
                   "clearing the last ended task also persists an empty history")
        self.screenshot_ui("download-history-cleared")
        self.assert_no_qml_errors()
        self.finish_test()

    def test_every_download_kind_passes_waiting_running_and_completed_with_real_files(self):
        from PySide6.QtCore import QRunnable

        tasks = self.window.download_page.tasks_page
        tasks.pool.setMaxThreadCount(1)
        gate_started, gate_release = Event(), Event()

        class QueueGate(QRunnable):
            def run(self):
                gate_started.set()
                gate_release.wait(60)

        self.addCleanup(gate_release.set)
        tasks.pool.start(QueueGate())
        self.wait_for(gate_started.is_set, "real Qt pool is occupied before submitting downloads")
        enqueued, barriers = [], {}
        files = {"game": "client.jar", **{kind: self.fixtures.version(kind)["filename"]
                                         for kind in self.KINDS[1:]}}
        try:
            for kind, filename in files.items():
                barriers[kind] = self.fixtures.pauses[filename] = Event(), Event()
            page = self.seed_games()
            self.click_ui(page, "install-1.21.8")
            self.click_ui(page, "install-selected-game")
            enqueued.append(("game", tasks._tasks[0]))
            for kind in self.KINDS[1:]:
                _page, _controller, dialog = self.content_dialog(kind)
                self.click_ui(dialog, "content-download-confirm")
                enqueued.append((kind, tasks._tasks[0]))
            self.check(len(tasks._tasks) == len(enqueued) == 5,
                       "each of the five UI actions creates one distinct download task")
            self.check(all(task["state"] == "等待中" for _kind, task in enqueued),
                       "all five kinds visibly remain queued while capacity is occupied")
            self.screenshot_ui("download-all-kinds-queued")
            gate_release.set()
            for kind, task in enqueued:
                started, release = barriers[kind]
                self.wait_for(started.is_set, kind + " begins actual loopback HTTP streaming")
                self.wait_for(lambda: task["state"] == "进行中", kind + " transitions to running")
                self.check(task["id"] in tasks._workers, "running row owns its real worker: " + kind)
                self.wait_for(lambda: task.get('speed', 0) > 0, kind + ' reports actual byte transfer speed')
                self.text_ui(tasks, 'catalogue-query', task['version'])
                self.pause_ui()
                speed = self.item(tasks, 'task-speed-' + task['id'])
                self.check(speed.isVisible() and 'iB/s' in speed.property('text'),
                           kind + ' speed is visible beside the real progress bar')
                self.screenshot_ui("download-all-kinds-running-" + kind)
                release.set()
                self.finished_task(task)
                self.text_ui(tasks, 'catalogue-query', '')
                if kind == "game":
                    installed = self.game_dir / "versions/1.21.8/1.21.8.jar"
                elif kind == "modpack":
                    installed = self.game_dir / "versions" / task["version"] / "config/ui-acceptance.json"
                    self.check(installed.read_text(encoding="utf-8") == '{"installedBy":"real importer"}',
                               "queued modpack completes real extraction, not just archive transfer")
                    continue
                else:
                    folder = {"mod": "mods", "resourcepack": "resourcepacks", "shader": "shaderpacks"}[kind]
                    installed = Path(task["content"]["target"]) / folder / files[kind]
                self.check(installed.read_bytes() == self.fixtures.payloads[files[kind]],
                           "completed task publishes the verified bytes: " + kind)
            self.check(all(task["state"] == "已完成" for _kind, task in enqueued),
                       "all five kinds complete after their real streaming transfers")
            self.screenshot_ui("download-all-kinds-completed")
        finally:
            gate_release.set()
            for _started, release in barriers.values():
                release.set()
        self.assert_no_qml_errors()
        self.finish_test()

    def test_content_confirmation_cancel_close_escape_and_outside_for_every_kind(self):
        for kind in self.KINDS[1:]:
            for action in ("cancel", "close", "escape"):
                with self.subTest(kind=kind, action=action):
                    _page, controller, dialog = self.content_dialog(kind)
                    before = len(self.window.download_page.tasks_page._tasks)
                    # The shipping confirmation is a modal dialog. An outside
                    # click must never accept it or trigger a background download.
                    self.record("mouseClick", "outside-content-confirmation", kind)
                    qt_mouse_click(self.window.title_bar.quick, QPoint(3, 3))
                    self.pause_ui()
                    self.check(dialog.isVisible() and len(self.window.download_page.tasks_page._tasks) == before,
                               "outside click cannot accept or dismiss the modal download confirmation")
                    if action == "escape":
                        self.key_ui(dialog, Qt.Key_Escape, "content-confirmation-escape")
                    else:
                        self.click_ui(dialog, "content-download-" + action)
                    import shiboken6
                    self.check((not shiboken6.isValid(dialog) or not dialog.isVisible())
                               and len(self.window.download_page.tasks_page._tasks) == before,
                               "dismissal never starts a download: " + kind + " / " + action)
                    self.check(controller.view == "detail", "dismissal returns to the usable detail page")
            _page, _controller, dialog = self.content_dialog(kind)
            self.click_ui(dialog, "content-download-confirm")
            self.finished_task()
        self.screenshot_ui("download-confirmations-dismiss-and-retry")
        self.assert_no_qml_errors()
        self.finish_test()

    def test_import_name_invalid_paths_reserved_names_and_exact_length_boundaries(self):
        from utils.path_helper import filesystem_path
        from utils.instances import installed_instance_ids
        import shutil
        self.addCleanup(shutil.rmtree, filesystem_path(self.directory), ignore_errors=True)
        host, controller = self.open_import()
        tasks = self.window.download_page.tasks_page
        original = set((self.game_dir / "versions").iterdir())
        invalid = ("", "   ", ".", "..", "../escape", "nested/name", "nested\\name",
                   "C:drive", "bad<name", "bad>name", 'bad"name', "bad|name", "bad?name",
                   "bad*name", "CON", "nul.txt", "COM1", "LPT9.cfg", "trailing.", "x" * 101)
        for name in invalid:
            self.text_ui(host, "pack-instance-name", name)
            self.check(controller.pack_name == name.strip(), "invalid input reaches validation: " + repr((name, controller.pack_name)))
            self.click_ui(host, "start-pack-import")
            self.check(controller.view == "import"
                       and (bool(controller.pack_error) or not self.item(host, "start-pack-import").isEnabled())
                       and not tasks._tasks,
                       "invalid instance name is rejected before scheduling any worker: " + repr(name))
            self.check(set((self.game_dir / "versions").iterdir()) == original,
                       "invalid name cannot create directories or change existing instances")
        for raw_name in ("  a  ", "n" * 100):
            host.quick.setFocus()
            self.item(host, 'pack-instance-name').forceActiveFocus()
            self.text_ui(host, "pack-instance-name", raw_name)
            self.screenshot_ui("import-boundary-before-submit")
            self.check(controller.pack_name == raw_name.strip(),
                       "valid name reaches importer: " + repr((controller.pack_name,
                       self.item(host, "pack-instance-name").property("text"),
                       self.item(host, "pack-instance-name").property("activeFocus"))))
            self.click_ui(host, "start-pack-import")
            self.check(bool(tasks._tasks), "valid name submits an import: " + repr(controller.pack_error))
            task = self.finished_task()
            self.check(task["version"] == raw_name.strip(), "leading/trailing whitespace is normalized")
            self.check(filesystem_path(self.game_dir / "versions" / raw_name.strip() / "config/ui-acceptance.json").is_file(),
                       "valid 1/100-character boundary actually installs in the exact destination")
            self.check(raw_name.strip() in installed_instance_ids(self.game_dir),
                       "the newly installed boundary name is discoverable by production instance scanning")
            host, controller = self.open_import()
        self.check(original <= set((self.game_dir / "versions").iterdir()),
                   "boundary imports preserve every existing instance")
        self.screenshot_ui("download-import-name-boundaries")
        self.assert_no_qml_errors()
        self.finish_test()

    def test_history_reopens_from_disk_and_completed_content_can_reinstall(self):
        _page, _controller, dialog = self.content_dialog("resourcepack")
        self.click_ui(dialog, "content-download-confirm")
        completed = self.finished_task()
        tasks = self.window.download_page.tasks_page
        self.click_ui(tasks, "task-action-" + completed["id"])
        self.finished_task()
        self.check(len(tasks._tasks) == 2, "completed ordinary content offers a working reinstall action")
        # Simulate the durable record left by an abrupt previous termination;
        # the new window must classify it as interrupted and offer retry.
        original_save = tasks._save_history
        def save_with_interrupted_record():
            original_save()
            history = json.loads(Path(tasks.history_path).read_text(encoding="utf-8"))
            if not any(row["id"] == "f" * 32 for row in history):
                unfinished = deepcopy(history[0])
                unfinished.update(id="f" * 32, state="进行中", status="Transfer was interrupted")
                history.append(unfinished)
            Path(tasks.history_path).write_text(json.dumps(history), encoding="utf-8")
        # Recreate the complete production window and settings from these files.
        from test_home_ui import HomeChecklistUiTests
        with patch.object(tasks, "_save_history", side_effect=save_with_interrupted_record):
            HomeChecklistUiTests.restart(self)
        tasks = self.window.download_page.tasks_page
        self.navigate("launcher-nav-download")
        self.click_ui(self.window.download_page.tab_buttons_widget, "navigation-option-1")
        self.check(len(tasks._tasks) == 3 and sum(row["state"] == "已完成" for row in tasks._tasks) == 2
                   and any(row["id"] == completed["id"] for row in tasks._tasks),
                   "window restart restores the persisted completed-task history")
        interrupted = next(row for row in tasks._tasks if row["id"] == "f" * 32)
        self.check(interrupted["state"] == "已中断", "unfinished records are recovered as interrupted, never as running or completed")
        self.click_ui(tasks, "task-log-" + tasks._tasks[0]["id"])
        self.click_ui(tasks, "log-text-tab")
        self.check(bool(self.item(tasks, "task-log-text").property("text")), "persisted task logs remain readable after restart")
        self.click_ui(tasks, "task-log-close")
        self.click_ui(tasks, "task-action-" + interrupted["id"])
        self.finished_task()
        self.check(len(tasks._tasks) == 4, "recovered interrupted task can be retried from the UI")
        self.screenshot_ui("download-history-restored")
        self.assert_no_qml_errors()
        self.finish_test()

    def test_fabric_quilt_api_versions_replace_remove_and_reset(self):
        self.catalogue.many_files = True
        page = self.seed_games()
        self.click_ui(page, "install-1.21.8")
        for loader in ("Fabric", "Quilt"):
            with self.subTest(loader=loader):
                self.reveal_control(page, "component-" + loader)
                self.click_ui(page, "component-" + loader)
                self.wait_for(lambda: not page.controller.loader_busy, "loader metadata arrives")
                self.click_ui(page, "component-version-0")
                for addon in (("Fabric API",) if loader == "Fabric" else ("Fabric API", "QSL/QFAPI")):
                    self.reveal_control(page, "component-" + addon)
                    self.click_ui(page, "component-" + addon)
                    self.wait_for(lambda: not page.controller.loader_busy, "API list arrives")
                    self.click_ui(page, "component-version-0")
                    self.check(addon in page.controller.addons, "API choice is associated with the selected loader")
                    self.reveal_control(page, "component-" + addon)
                    self.click_ui(page, "component-" + addon)
                    self.wait_for(lambda: not page.controller.loader_busy, "API version selection reopens")
                    self.click_ui(page, "component-version-1")
                    self.check(page.controller.addons[addon]["id"] == "file-1", "API version replacement takes effect")
                    self.reveal_control(page, "component-" + addon + "-remove")
                    self.click_ui(page, "component-" + addon + "-remove")
                    self.check(addon not in page.controller.addons, "API can be independently removed")
                self.reveal_control(page, "component-" + loader + "-remove")
                self.click_ui(page, "component-" + loader + "-remove")
                self.check(not page.controller.addons, "loader removal clears its API choices")
        self.click_ui(page, "game-install-back")
        self.click_ui(page, "install-1.20.1")
        self.reveal_control(page, "component-Fabric")
        self.click_ui(page, "component-Fabric")
        self.wait_for(lambda: not page.controller.loader_busy, "new game loader choices arrive")
        self.click_ui(page, "component-version-0")
        self.reveal_control(page, "component-Fabric API")
        self.click_ui(page, "component-Fabric API")
        self.wait_for(lambda: not page.controller.loader_busy, "new game's API choices arrive")
        self.click_ui(page, "component-version-0")
        self.check(page.controller.game == "1.20.1"
                   and page.controller.addons["Fabric API"]["game_versions"] == ["1.20.1"]
                   and self.catalogue.calls[-1]["game"] == "1.20.1",
                   "changing Minecraft version requests and selects the corresponding API")
        self.screenshot_ui("download-api-choices-reset")
        self.assert_no_qml_errors()
        self.finish_test()

    def test_interrupted_transfer_and_unavailable_first_source_recover(self):
        filename = "ui-fixture-resourcepack.zip"
        self.fixtures.truncations.add(filename)
        _page, _controller, dialog = self.content_dialog("resourcepack")
        target = Path(dialog.controller.data["target"]) / "resourcepacks" / filename
        self.click_ui(dialog, "content-download-confirm")
        failed = self.finished_task(state="失败")
        self.check(not target.exists() and bool(failed["error"]),
                   "an abruptly closed stream never publishes an incomplete resource file")
        self.fixtures.truncations.clear()
        original_route = self.fixtures.route
        def fallback(downloader, url):
            candidates = original_route(downloader, url)
            if url.endswith("/" + filename):
                return [f"http://localhost:{self.fixtures.server.server_port}/missing-source"] + candidates
            return candidates
        with patch("core.downloads.MinecraftDownloader.urls", fallback):
            self.click_ui(self.window.download_page.tasks_page, "task-action-" + failed["id"])
            recovered = self.finished_task()
        requests = [row["file"] for row in self.fixtures.requests]
        self.check("missing-source" in requests and requests[-1] == filename
                   and target.read_bytes() == self.fixtures.payloads[filename],
                   "a failed first source falls through to a working HTTP source and verifies its bytes")
        self.check(any("localhost" in line for line in recovered["logs"])
                   and any("127.0.0.1" in line for line in recovered["logs"]),
                   "task log identifies both the attempted source and the successful source")
        self.screenshot_ui("download-transfer-fallback-recovered")
        self.assert_no_qml_errors()
        self.finish_test()

    def test_confirmation_target_compatibility_and_deleted_instance(self):
        for kind in ("mod", "resourcepack", "shader"):
            with self.subTest(kind=kind):
                page, controller = self.open_project(kind)
                header = self.window.title_bar
                self.click_ui(header, "version-picker")
                index = header.controller.versions.index("1.20.1")
                self.click_ui(header._picker.host, "choice-option-" + str(index))
                self.click_ui(page, "content-detail-tab-1")
                self.click_ui(page, "download-content-version")
                dialog = controller._download_dialog
                self.check(dialog.controller.data["instance"] == "1.20.1"
                           and not dialog.controller.data["targetValid"]
                           and "不支持" in dialog.controller.data["compatibility"]
                           and not self.item(dialog, "content-download-confirm").isEnabled(),
                           "changing the header target updates the incompatible download confirmation")
                self.click_ui(dialog, "content-download-target-toggle")
                self.choose_filter(dialog, dialog.controller.data["instances"].index("1.21.8"),
                                   "content-download-target")
                self.check(dialog.controller.data["targetValid"]
                           and self.item(dialog, "content-download-confirm").isEnabled()
                           and dialog.controller.data["instance"] == "1.21.8",
                           "choosing a compatible instance recalculates advice and enables download")
                self.screenshot_ui("download-target-compatible-" + kind, dialog)
                self.click_ui(dialog, "content-download-cancel")
        _page, _controller, dialog = self.content_dialog("modpack")
        self.check(dialog.controller.data["targetValid"]
                   and dialog.controller.data["environment"] == "独立游戏实例"
                   and Path(dialog.controller.data["target"]) == self.game_dir / "downloads",
                   "modpacks keep an independent destination when the Home target is switched")
        self.click_ui(dialog, "content-download-cancel")
        _page, controller, dialog = self.content_dialog("resourcepack")
        self.click_ui(dialog, "content-download-target-toggle")
        self.choose_filter(dialog, dialog.controller.data["instances"].index("1.21.8"),
                           "content-download-target")
        selected = dialog.controller.data["instance"]
        original_target = Path(dialog.controller.data["target"])
        # This is an isolated fixture file, simulating concurrent instance removal.
        metadata = self.game_dir / "versions" / selected / (selected + ".json")
        original_metadata = metadata.read_bytes()
        metadata.unlink()
        self.click_ui(dialog, "content-download-confirm")
        self.check(not dialog.controller.data["targetValid"]
                   and "已不存在" in dialog.controller.data["compatibility"]
                   and not self.window.download_page.tasks_page._tasks,
                   "confirmation revalidates a removed target instead of downloading elsewhere")
        # Restore only the test-owned instance, then reselect through the UI.
        metadata.write_bytes(original_metadata)
        self.choose_filter(dialog, dialog.controller.data["instances"].index("1.20.1"),
                           "content-download-target")
        self.choose_filter(dialog, dialog.controller.data["instances"].index(selected),
                           "content-download-target")
        self.check(dialog.controller.data["targetValid"]
                   and self.item(dialog, "content-download-confirm").isEnabled()
                   and Path(dialog.controller.data["target"]) == original_target,
                   "reselecting an available compatible instance recovers a previously missing target")
        self.click_ui(dialog, "content-download-close")
        self.assert_no_qml_errors()
        self.finish_test()

    def test_parallel_search_ignores_stale_results_for_every_kind(self):
        for kind in self.KINDS[1:]:
            with self.subTest(kind=kind):
                page, controller = self.open_kind(kind)
                self.catalogue.slow_started.clear()
                self.catalogue.release_slow.clear()
                self.text_ui(page, "catalogue-query", "slow")
                self.key_ui(page, Qt.Key_Return, "slow-search")
                self.wait_for(self.catalogue.slow_started.is_set, "older slow request is running")
                self.text_ui(page, "catalogue-query", "latest")
                self.key_ui(page, Qt.Key_Return, "replacement-search")
                self.wait_for(lambda: not controller.busy and controller.query == "latest"
                              and controller.results and controller.results[0]["title"] == "latest",
                              "newer request completes first")
                self.catalogue.release_slow.set()
                self.wait_for(lambda: controller.pool.activeThreadCount() == 0, "older response is delivered")
                self.pause_ui()
                self.check(controller.query == "latest" and controller.results[0]["title"] == "latest",
                           "older search completion never overwrites newer results: " + kind)

                self.catalogue.slow_source = controller.source
                self.catalogue.slow_started.clear()
                self.catalogue.release_slow.clear()
                self.text_ui(page, "catalogue-query", "slow")
                self.key_ui(page, Qt.Key_Return, "slow-search-before-source-switch")
                self.wait_for(self.catalogue.slow_started.is_set, "old source request is held in flight")
                self.choose_filter(page, 2 if controller.source != "CurseForge" else 1, "content-source")
                self.wait_for(lambda: not controller.busy and controller.source != self.catalogue.slow_source
                              and controller.results and controller.results[0]["source"] == controller.source,
                              "new source completes before the old response")
                self.check(controller.results[0]["source"] == controller.source,
                           "new source supplies the current rows")
                self.catalogue.release_slow.set()
                self.wait_for(lambda: controller.pool.activeThreadCount() == 0, "old source response is delivered")
                self.pause_ui()
                self.check(controller.results[0]["source"] == controller.source,
                           "late prior-source response cannot overwrite current rows: " + kind)
                self.catalogue.slow_source = None

                # A category change is a separate user-visible branch from typing a
                # replacement query: its new request must invalidate the old one too.
                self.catalogue.slow_kind = kind
                self.catalogue.slow_started.clear()
                self.catalogue.release_slow.clear()
                self.text_ui(page, "catalogue-query", "slow")
                self.key_ui(page, Qt.Key_Return, "slow-search-before-category-switch")
                self.wait_for(self.catalogue.slow_started.is_set, "category-switch request is held in flight")
                next_index = self.KINDS.index(kind) + 1
                if next_index >= len(self.KINDS):
                    next_index = 1
                next_kind = self.KINDS[next_index]
                self.click_ui(page, "content-kind-" + str(next_index))
                self.wait_for(lambda: not controller.busy and bool(controller.results),
                              "new category results arrive before the old response")
                self.check(controller.kind == next_kind
                           and controller.results[0]["project_id"].startswith("fixture-" + next_kind + "-"),
                           "category switch loads rows for the selected category: " + kind)
                self.catalogue.release_slow.set()
                self.wait_for(lambda: controller.pool.activeThreadCount() == 0,
                              "late response from previous category is delivered")
                self.pause_ui()
                self.check(controller.kind == next_kind
                           and controller.results[0]["project_id"].startswith("fixture-" + next_kind + "-"),
                           "late prior-category response cannot overwrite current rows: " + kind)
                self.screenshot_ui("download-late-response-" + kind)
                self.catalogue.slow_kind = None
        self.assert_no_qml_errors()
        self.finish_test()

    def test_back_from_loading_project_discards_late_success_and_error_for_every_kind(self):
        for kind in self.KINDS[1:]:
            for failed in (False, True):
                with self.subTest(kind=kind, failed=failed):
                    page, controller = self.open_kind(kind)
                    original_rows = deepcopy(controller.results)
                    tasks_before = len(self.window.download_page.tasks_page._tasks)
                    self.catalogue.versions_started.clear()
                    self.catalogue.project_started.clear()
                    self.catalogue.release_project.clear()
                    self.catalogue.hold_project = True
                    self.catalogue.version_error = self.catalogue.project_error = failed
                    try:
                        self.click_ui(page, "content-project-0")
                        self.wait_for(lambda: self.catalogue.versions_started.is_set()
                                      and self.catalogue.project_started.is_set(),
                                      "project details and version requests are both held in flight")
                        self.check(controller.busy and controller.details_busy,
                                   "detail loading state is active before returning")
                        self.click_ui(page, "content-back")
                        self.check(controller.view == "browse" and not controller.busy
                                   and not controller.details_busy and controller.selected_project is None,
                                   "Back immediately restores a usable project list")
                    finally:
                        self.catalogue.hold_project = False
                        self.catalogue.release_project.set()
                    self.wait_for(lambda: controller.pool.activeThreadCount() == 0,
                                  "obsolete detail and file responses finish after returning")
                    self.pause_ui()
                    self.check(controller.view == "browse" and controller.selected_project is None
                               and not controller.busy and not controller.details_busy
                               and controller.results == original_rows and not controller.versions
                               and not controller.status,
                               "late success/error cannot restore cancelled details or replace list status")
                    self.check(len(self.window.download_page.tasks_page._tasks) == tasks_before,
                               "leaving a loading project cannot create a download task")
                    self.catalogue.version_error = self.catalogue.project_error = False
                    self.click_ui(page, "content-project-0")
                    self.wait_for(lambda: not controller.busy and not controller.details_busy,
                                  "project can be opened again after obsolete responses finish")
                    self.check(controller.view == "detail" and bool(controller.versions)
                               and bool(controller.selected_project) and not controller.status,
                               "reopening obtains usable project details and downloadable files")
                    self.screenshot_ui("download-reopened-project-" + kind + ("-error" if failed else "-success"))
        self.assert_no_qml_errors()
        self.finish_test()

    def test_translation_original_and_versions_tabs_for_every_kind(self):
        translations = dict(status="Fixture translation complete", pending=False, translations={"0":{
            "summary": {"text": "资源简介译文", "format": "text"},
            "body": {"text": "资源详情译文", "format": "text"}}})
        from test_settings_ui import ClientUiSettingsTests
        with patch("ui.pages.download.content_browser.TranslationClient.resolve", return_value=translations):
            self.navigate("launcher-nav-settings")
            settings = self.window.settings_page.general_page
            settings.ensure_loaded()
            ClientUiSettingsTests.scroll_control(self, settings, "setting-toggle-translation.enabled")
            self.click_ui(settings, "setting-toggle-translation.enabled")
            self.check(self.manager.get_setting("translation.enabled"), "translation is enabled through Settings UI")
            for kind in self.KINDS[1:]:
                with self.subTest(kind=kind):
                    page, controller = self.open_project(kind)
                    self.wait_for(lambda: controller.selected_project.get("translated_body") == "资源详情译文",
                                  "translation result reaches the current project")
                    self.check(self.item(page, "content-body-text").property("text") == "资源详情译文",
                               "project introduction renders the translated body")
                    self.click_ui(page, "content-toggle-original")
                    self.check(self.item(page, "content-body-text").property("text") == "Original resource body",
                               "original text remains available after translation")
                    self.click_ui(page, "content-toggle-original")
                    self.click_ui(page, "content-detail-tab-1")
                    self.check(self.item(page, "content-version-list").isVisible(), "file list opens after translated introduction")
                    self.click_ui(page, "content-detail-tab-0")
                    self.screenshot_ui("download-translated-introduction-" + kind)
        self.assert_no_qml_errors()
        self.finish_test()

    def test_streaming_progress_cancel_log_tabs_and_retry(self):
        filename = "ui-fixture-mod.jar"
        started, release = self.pause_file(filename)
        _page, _controller, dialog = self.content_dialog("mod")
        target = Path(dialog.controller.data["target"]) / "mods" / filename
        self.click_ui(dialog, "content-download-confirm")
        tasks = self.window.download_page.tasks_page
        task = tasks._tasks[0]
        self.wait_for(lambda: started.is_set() and task["state"] == "进行中"
                      and any(0 < f.get("done", 0) < f.get("total", 0) for f in task.get("files", [])),
                      "real HTTP stream reports intermediate file progress")
        self.click_ui(tasks, "task-log-" + task["id"])
        self.check(self.item(tasks, "task-log-files").isVisible()
                   and bool(tasks.view_controller.currentFiles), "file progress log opens for the running task")
        self.click_ui(tasks, "log-text-tab")
        self.check("下载" in self.item(tasks, "task-log-text").property("text"),
                   "text log contains production downloader status")
        self.click_ui(tasks, "log-files-tab")
        self.screenshot_ui("download-live-file-progress", tasks)
        self.click_ui(tasks, "task-log-close")
        self.click_ui(tasks, "task-action-" + task["id"])
        self.check(task["state"] == "正在取消", "cancel visibly enters the canceling state")
        release.set()
        self.finished_task(task, "已取消")
        self.check(not target.exists(), "cancel does not publish an unverified partial file")
        self.fixtures.pauses.pop(filename)
        self.wait_for(lambda: self.item(tasks, "task-action-" + task["id"]).isEnabled()
                      and self.item(tasks, "task-action-" + task["id"]).property("text") == "重试",
                      "retry button reflects the canceled task before the next click")
        self.click_ui(tasks, "task-action-" + task["id"])
        self.wait_for(lambda: len(tasks._tasks) == 2, "Retry actually queues a new content task")
        completed = self.finished_task()
        self.check(completed["id"] != task["id"] and target.read_bytes() == self.fixtures.payloads[filename],
                   "retry creates a new task and publishes the verified full file")
        self.screenshot_ui("download-cancel-retry-complete", tasks)
        self.assert_no_qml_errors()
        self.finish_test()

    def test_failed_download_visible_error_log_and_recovery(self):
        self.fixtures.failures.add("ui-fixture-resourcepack.zip")
        _page, _controller, dialog = self.content_dialog("resourcepack")
        self.click_ui(dialog, "content-download-confirm")
        task = self.finished_task(state="失败")
        self.check("404" in task["error"], "history exposes the actual HTTP failure")
        tasks = self.window.download_page.tasks_page
        self.click_ui(tasks, "task-log-" + task["id"])
        self.screenshot_ui("download-log-open-diagnostic", tasks)
        self.check(bool(tasks.quick.rootObject().property("logOpen")),
                   "task log dialog is open: " + repr(self.messages[-12:]))
        self.click_ui(tasks, "log-text-tab")
        self.check("404" in self.item(tasks, "task-log-text").property("text"),
                   "failed download log retains the failing HTTP status")
        self.screenshot_ui("download-http-failed-log", tasks)
        self.click_ui(tasks, "task-log-close")
        self.fixtures.failures.clear()
        self.click_ui(tasks, "task-action-" + task["id"])
        self.finished_task()
        self.check(len(tasks._tasks) == 2, "retry preserves the failed task for diagnosis")
        self.assert_no_qml_errors()
        self.finish_test()

    def test_modpack_download_installs_new_instance_without_replacing_existing(self):
        page = self.seed_games()
        self.click_ui(page, "install-1.21.8")
        self.click_ui(page, "install-selected-game")
        self.finished_task()
        old = self.game_dir / "versions/1.21.8/1.21.8.json"
        original = old.read_bytes()
        _page, _controller, dialog = self.content_dialog("modpack")
        self.check(dialog.controller.data["environment"] == "独立游戏实例", "modpack explicitly creates its own instance")
        self.click_ui(dialog, "content-download-confirm")
        task = self.finished_task()
        identity = task["version"]
        installed = self.game_dir / "versions" / identity
        self.check(identity != "1.21.8" and (installed / (identity + ".json")).is_file()
                   and (installed / "config/ui-acceptance.json").is_file(),
                   "verified pack download runs the real importer and writes a separate instance")
        self.check(old.read_bytes() == original, "pack installation preserves the previously installed instance")
        self.navigate("instances-button")
        self.click_ui(self.window.version_page.versions_page, "instance-row-" + identity)
        self.navigate("launcher-nav-home")
        self.check(self.window.launcher.minecraft_version == identity
                   and self.window.started_page.controller.view["launchSubtitle"] == identity,
                   "new modpack can be selected as the Home target immediately")
        self.screenshot_ui("download-modpack-new-instance")
        self.assert_no_qml_errors()
        self.finish_test()

    def test_game_catalogue_network_error_retry_and_cache_write(self):
        self.fixtures.failures.add("manifest.json")
        with patch.object(GameCatalogueController, "refresh", REAL_GAME_REFRESH):
            page = self.open_downloads()
            self.wait_for(lambda: not page.controller.busy and "获取失败" in page.controller.status,
                          "failed HTTP catalogue response is displayed", timeout=25000)
            self.check("404" in page.controller.status, "catalogue preserves the HTTP error reason")
            self.screenshot_ui("download-game-catalogue-error")
            self.fixtures.failures.clear()
            self.click_ui(page, "catalogue-retry")
            self.wait_for(lambda: not page.controller.busy and bool(page.controller.versions),
                          "retry recovers through the production manifest downloader")
            self.check(page.controller.versions[0]["id"] == "1.21.8"
                       and json.loads(page.controller.cache.read_text(encoding="utf-8"))[0]["id"] == "1.21.8",
                       "successful manifest response is rendered and persisted as cache")
        self.assert_no_qml_errors()
        self.finish_test()

    def test_vanilla_install_refreshes_instances_header_and_home_target(self):
        page = self.seed_games()
        self.click_ui(page, "install-1.21.8")
        self.check(not page.controller.loader and not page.controller.addons,
                   "vanilla installation starts without a loader or API")
        self.click_ui(page, "install-selected-game")
        self.finished_task()
        archive = self.game_dir / "versions/1.21.8/1.21.8.jar"
        self.check(archive.read_bytes() == self.fixtures.payloads["client.jar"],
                   "vanilla client bytes were downloaded and installed")
        self.navigate("instances-button")
        instances = self.window.version_page.versions_page
        self.click_ui(instances, "instance-row-1.21.8")
        self.navigate("launcher-nav-home")
        self.check(self.window.launcher.minecraft_version == "1.21.8"
                   and self.window.title_bar.controller.selected == "1.21.8"
                   and self.window.started_page.controller.view["launchSubtitle"] == "1.21.8",
                   "installed version reaches instance list, header and Home without restart")
        self.screenshot_ui("download-vanilla-home")
        self.assert_no_qml_errors()
        self.finish_test()

    def test_loader_versions_replace_remove_incompatibility_and_new_game(self):
        page = self.seed_games()
        self.click_ui(page, "install-1.21.8")
        with patch("core.loaders.available_versions", return_value=["loader-a", "loader-b"]):
            for loader in ("Forge", "NeoForge", "Fabric", "Quilt"):
                with self.subTest(loader=loader):
                    self.reveal_control(page, "component-" + loader)
                    self.click_ui(page, "component-" + loader)
                    self.wait_for(lambda: not page.controller.loader_busy, "loader versions arrive")
                    self.click_ui(page, "component-version-0")
                    self.check(page.controller.loader == loader and page.controller.loader_version == "loader-a",
                               "selected loader version committed: " + loader)
                    other = "Quilt" if loader != "Quilt" else "Forge"
                    self.check(not self.item(page, "component-" + other).property("available"),
                               "mutually exclusive loader cannot be chosen")
                    self.reveal_control(page, "component-" + loader)
                    self.click_ui(page, "component-" + loader)
                    self.wait_for(lambda: not page.controller.loader_busy, "loader version list reopens")
                    self.click_ui(page, "component-version-1")
                    self.check(page.controller.loader_version == "loader-b", "changing loader version updates the form")
                    self.screenshot_ui("download-loader-" + loader)
                    self.reveal_control(page, "component-" + loader + "-remove")
                    self.click_ui(page, "component-" + loader + "-remove")
                    self.check(not page.controller.loader and not page.controller.addons,
                               "removing loader also clears dependent API selections")
        self.reveal_control(page, "component-OptiFine")
        optifine = self.item(page, "component-OptiFine")
        self.check(not optifine.property("available") and optifine.property("description") == "需官方安装器",
                   "OptiFine explains its unsupported automatic installation")
        self.click_ui(page, "game-install-back")
        self.click_ui(page, "install-1.20.1")
        self.check(page.controller.game == "1.20.1" and not page.controller.loader
                   and not page.controller.addons, "switching Minecraft version resets component choices")
        self.assert_no_qml_errors()
        self.finish_test()

    def test_loader_empty_failed_list_retry_and_back(self):
        page = self.seed_games()
        self.click_ui(page, "install-1.21.8")
        with patch("core.loaders.available_versions", side_effect=[[], ConnectionError("loader fixture 503"), ["recovered"]]):
            self.click_ui(page, "component-Forge")
            self.wait_for(lambda: not page.controller.loader_busy, "empty loader list finishes")
            self.check(not page.controller.component_versions and "暂无可用" in page.controller.loader_status,
                       "no loader versions has a distinct empty result")
            self.click_ui(page, "component-reload")
            self.wait_for(lambda: not page.controller.loader_busy, "failed loader list finishes")
            self.check("503" in page.controller.loader_status, "loader error reason stays visible")
            self.click_ui(page, "component-reload")
            self.wait_for(lambda: not page.controller.loader_busy, "loader list recovers")
            self.check(page.controller.component_versions[0]["name"] == "recovered",
                       "reload retries the same selected loader")
            self.click_ui(page, "game-install-cancel")
            self.check(page.controller.install_view == "components" and not page.controller.loader,
                       "returning without choosing does not install a loader")
        self.screenshot_ui("download-loader-recovered")
        self.assert_no_qml_errors()
        self.finish_test()

    def test_projects_and_version_files_append_by_mouse_wheel_for_every_kind(self):
        self.catalogue.many_files = True
        for kind in self.KINDS[1:]:
            with self.subTest(kind=kind):
                page, controller = self.open_kind(kind)
                self.search_content(page, controller, "pages")
                self.check(len(controller.results) == 20, "first project page has twenty rows")
                self.scroll_list_to_end(page, "content-project-list", lambda: len(controller.results) == 25)
                self.check(len({r["project_id"] for r in controller.results}) == 25,
                           "project append does not duplicate existing rows")
                # Use the first row after scrolling back with actual wheel input.
                self.search_content(page, controller, "one")
                self.click_ui(page, "content-project-0")
                self.wait_for(lambda: not controller.busy, "version list arrives")
                self.click_ui(page, "content-detail-tab-1")
                self.check(len(controller.versions) == 30, "first file page is bounded")
                self.scroll_list_to_end(page, "content-version-list", lambda: len(controller.versions) == 45)
                self.text_ui(page, "content-file-query", "Build 44")
                self.click_ui(page, "content-version-0")
                self.check(controller.versions[controller.selected_version]["id"] == "file-44",
                           "a file from the appended page remains searchable and selectable")
                self.screenshot_ui("download-pagination-" + kind)
        self.assert_no_qml_errors()
        self.finish_test()

    def test_content_sources_search_clear_empty_error_and_retry_for_every_kind(self):
        for kind in self.KINDS[1:]:
            with self.subTest(kind=kind):
                page, controller = self.open_kind(kind)
                for index, source in enumerate(("自动", "Modrinth", "CurseForge")):
                    self.choose_filter(page, index, "content-source")
                    self.wait_for(lambda: not controller.busy, "source search finishes")
                    self.check(controller.source == source and bool(controller.results),
                               kind + " selected source produces results: " + source)
                    self.check(all(row["source"] == ("Modrinth" if source == "自动" else source)
                                   for row in controller.results), "results expose their actual content platform")
                    self.search_content(page, controller, "source-" + str(index))
                    self.click_ui(page, "content-project-0")
                    self.wait_for(lambda: not controller.busy and not controller.details_busy,
                                  "selected source project details finish")
                    self.check(controller.selected_project["source"] == ("Modrinth" if source == "自动" else source),
                               "search and project selection retain the chosen source")
                    self.click_ui(page, "content-back")
                self.search_content(page, controller, "needle")
                self.check(controller.results[0]["title"] == "needle", "Return submits the typed query")
                self.search_content(page, controller, "", enter=False)
                self.check(bool(controller.results), "search button accepts an empty query and restores results")
                self.search_content(page, controller, "empty")
                self.check(not controller.results and not controller.status.startswith("获取失败"),
                           "zero results are distinguished from request errors")
                self.search_content(page, controller, "error")
                self.check("503" in controller.status and not controller.results,
                           "catalogue failures show the real error without stale successes")
                self.text_ui(page, "catalogue-query", "recovered")
                self.click_ui(page, "catalogue-retry")
                self.wait_for(lambda: not controller.busy, "retry completes")
                self.check(controller.results[0]["title"] == "recovered", "retry uses the edited query")
                self.catalogue.failed_sources.add("CurseForge")
                self.search_content(page, controller, "outage")
                self.check("CurseForge" in controller.status, "unavailable source is named")
                self.choose_filter(page, 1, "content-source")
                self.wait_for(lambda: not controller.busy, "switching source recovers the list")
                self.check(controller.source == "Modrinth" and bool(controller.results),
                           "another source remains usable after one provider fails")
                self.catalogue.failed_sources.clear()
                self.screenshot_ui("download-search-source-" + kind)
        self.assert_no_qml_errors()
        self.finish_test()

    def test_project_details_files_search_selection_and_cancel_for_every_kind(self):
        self.catalogue.many_files = True
        for kind in self.KINDS[1:]:
            with self.subTest(kind=kind):
                page, controller = self.open_project(kind)
                self.wait_for(lambda: not controller.details_busy, "project introduction arrives")
                self.check(controller.selected_project.get("authors") == ["Fixture Author"]
                           and controller.selected_project["body_text"] == "Original resource body",
                           "details display project authors and original body")
                self.click_ui(page, "content-detail-tab-1")
                self.text_ui(page, "content-file-query", "Build 07")
                self.check(len(controller.versions) == 1 and controller.versions[0]["id"] == "file-7",
                           "file search filters the selected project's actual versions")
                self.click_ui(page, "content-version-0")
                self.click_ui(page, "download-content-version")
                dialog = controller._download_dialog
                self.check(dialog is not None and dialog.controller.data["version"] == "Build 07",
                           "confirmation names the specific selected file")
                self.click_ui(dialog, "content-download-cancel")
                self.check(controller._download_dialog is None, "Cancel dismisses confirmation")
                self.click_ui(page, "download-content-version")
                self.click_ui(controller._download_dialog, "content-download-close")
                self.check(controller._download_dialog is None and not self.window.download_page.tasks_page._tasks,
                           "closing confirmation does not enqueue any download")
                self.text_ui(page, "content-file-query", "no-such-file")
                self.check(not controller.versions and controller.selected_version == -1,
                           "no matching files clears the selection")
                self.text_ui(page, "content-file-query", "")
                self.check(len(controller.versions) >= 30, "clearing file search restores file rows")
                self.click_ui(page, "content-detail-tab-0")
                self.check(self.item(page, "content-description").isVisible(), "Introduction tab reopens")
                self.screenshot_ui("download-details-" + kind)
                self.click_ui(page, "content-back")
                self.check(controller.view == "browse", "Back returns to this category's results")
        self.assert_no_qml_errors()
        self.finish_test()

    def test_content_downloads_write_verified_files_to_selected_instance(self):
        folders = {"mod": "mods", "resourcepack": "resourcepacks", "shader": "shaderpacks"}
        for kind, folder in folders.items():
            with self.subTest(kind=kind):
                _page, controller, dialog = self.content_dialog(kind)
                self.click_ui(dialog, "content-download-target-toggle")
                self.choose_filter(dialog, dialog.controller.data["instances"].index("1.21.8"),
                                   "content-download-target")
                target = Path(dialog.controller.data["target"])
                self.check(self.game_dir == target or self.game_dir in target.parents,
                           "download destination stays inside this test's game directory")
                self.check(dialog.controller.data["instance"] == "1.21.8"
                           and dialog.controller.data["targetValid"], "selected target is valid")
                self.click_ui(dialog, "content-download-confirm")
                task = self.finished_task()
                filename = self.fixtures.version(kind)["filename"]
                installed = target / folder / filename
                self.check(installed.read_bytes() == self.fixtures.payloads[filename],
                           kind + " file bytes match the verified HTTP artifact")
                self.check(task["content"]["target"] == str(target)
                           and task["downloaded_files"] == [str(installed)],
                           "history records the selected instance path and installed file")
                self.screenshot_ui("download-installed-" + kind)
        self.assert_no_qml_errors()
        self.finish_test()

    def test_download_category_navigation_history_and_detail_return(self):
        page = self.open_downloads()
        for index, kind in enumerate(self.KINDS):
            self.click_ui(page, "content-kind-" + str(index))
            self.check(page.controller.category == kind, "category button selects " + kind)
            if kind != "game":
                controller = self.window.download_page.content_page.controller
                self.wait_for(lambda: not controller.busy, kind + " results ready")
                self.click_ui(page, "content-project-0")
                self.wait_for(lambda: not controller.busy, kind + " details ready")
                self.check(controller.view == "detail", "real detail opens for " + kind)
                self.click_ui(page, "content-back")
                self.check(controller.view == "browse" and bool(controller.results),
                           "detail returns to the previous result list for " + kind)
            self.screenshot_ui("download-category-" + kind)
        navigation = self.window.download_page.tab_buttons_widget
        self.click_ui(navigation, "navigation-option-1")
        self.check(self.window.download_page.stack.currentWidget() is self.window.download_page.tasks_page,
                   "download history opens from the sidebar")
        self.click_ui(navigation, "navigation-option-0")
        self.check(self.window.download_page.stack.currentWidget() is page,
                   "sidebar returns to downloads without losing the category")
        self.click_ui(page, "content-kind-1")
        controller = self.window.download_page.content_page.controller
        self.wait_for(lambda: not controller.busy, "previous category reopens")
        self.check(controller.kind == "mod" and bool(controller.results),
                   "switching away and back restores a usable project list")
        self.assert_no_qml_errors()
        self.finish_test()

    def test_game_filters_search_empty_clear_and_install_return(self):
        page = self.seed_games()
        for index, expected in enumerate((2, 1, 2, 5)):
            self.choose_filter(page, index)
            self.check(len(page.controller.view["versions"]) == expected,
                       "game release/snapshot/legacy/all filter: " + str(index))
        self.text_ui(page, "catalogue-query", "does-not-exist")
        self.key_ui(page, Qt.Key_Return, "game-search-no-results")
        self.check(not page.controller.view["versions"], "no match shows an empty game list")
        self.text_ui(page, "catalogue-query", "")
        self.click_ui(page, "catalogue-search")
        self.check(len(page.controller.view["versions"]) == 5, "clearing search restores every game")
        self.text_ui(page, "catalogue-query", "1.21")
        self.click_ui(page, "catalogue-search")
        self.click_ui(page, "install-1.21.8")
        self.check(page.controller.game == "1.21.8" and page.controller.install_view == "components",
                   "game row enters the selected game's installation form")
        self.click_ui(page, "game-install-back")
        self.click_ui(page, "install-1.21.8")
        self.click_ui(page, "game-install-cancel")
        self.check(page.controller.install_view == "catalogue" and not self.window.download_page.tasks_page._tasks,
                   "both back and cancel return without submitting a task")
        self.screenshot_ui("download-game-filter-search")
        self.assert_no_qml_errors()
        self.finish_test()
