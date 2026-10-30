"""Click the real missing-mod dialog and finish/cancel production imports."""
import hashlib
import json
from unittest.mock import patch

from PySide6.QtCore import QTimer, Qt

from test_client_ui_acceptance import ClientUiAcceptanceCase as _UiCase
import test_download_ui as download_ui


class MissingModsUiTests(_UiCase):
    open_downloads = download_ui.DownloadChecklistUiTests.open_downloads
    open_import = download_ui.DownloadChecklistUiTests.open_import
    finished_task = download_ui.DownloadChecklistUiTests.finished_task

    def tearDown(self):
        tasks = self.window.download_page.tasks_page
        tasks._mod_prompts.close()
        for worker in list(tasks._workers.values()):
            worker.cancel_event.set()
        self.wait_for(lambda: not tasks._workers, 'all import workers release before destroying Qt')
        # The Qt finished signal can be delivered just before QRunnable.run
        # returns. Join that final turn before removing its cache directory.
        self.assertTrue(tasks.pool.waitForDone(5000), 'all import QRunnables exit before fixture cleanup')
        super().tearDown()

    def pack(self, *, missing=True):
        from core.modpacks import export_pack
        source = self.directory / 'private-source'
        instance = source / 'versions/Source'
        (instance / 'mods').mkdir(parents=True)
        (instance / 'Source.json').write_text(json.dumps(self.fixtures.metadata), encoding='utf-8')
        contents = {'private.jar': b'private unpublished mod', 'public.jar': b'public mod bytes'}
        public = {}
        for name, payload in contents.items():
            (instance / 'mods' / name).write_bytes(payload)
            self.fixtures.payloads[name] = payload
            if missing or name != 'private.jar':
                public['mods/' + name] = dict(sha1=hashlib.sha1(payload).hexdigest(), size=len(payload),
                    downloads=['https://cdn.modrinth.com/data/fixture/' + name])
        archive = self.directory / 'missing-mods.buggpack'
        with patch('core.modpack_sources.find_public_mod_downloads', return_value=public):
            export_pack(source, 'Source', archive)
        original_route = self.fixtures.route
        def route(downloader, url):
            if url.startswith('https://cdn.modrinth.com/data/fixture/'):
                return [f'http://127.0.0.1:{self.fixtures.server.server_port}/' + url.rsplit('/', 1)[-1]]
            return original_route(downloader, url)
        self._patch(patch('core.downloads.MinecraftDownloader.urls', route))
        if missing:
            self.fixtures.failures.add('private.jar')
        return archive, contents

    def start(self):
        archive, contents = self.pack()
        host, _ = self.open_import(archive)
        self.text_ui(host, 'pack-instance-name', 'Missing-Mods')
        self.click_ui(host, 'start-pack-import')
        tasks = self.window.download_page.tasks_page
        self.wait_for(lambda: tasks._mod_prompts.dialog is not None, 'missing public mod opens decision dialog')
        dialog = tasks._mod_prompts.dialog
        self.wait_for(dialog.isVisible, 'missing mod dialog is visible')
        return tasks, dialog, contents

    def test_skip_choice_keeps_ui_responsive_and_publishes_with_warning(self):
        tasks, dialog, contents = self.start()
        ticks = []
        timer = QTimer(self.window)
        timer.setInterval(10)
        timer.timeout.connect(lambda: ticks.append(True))
        timer.start()
        self.wait_for(lambda: len(ticks) >= 4, 'UI timer keeps running while installer waits for consent')
        timer.stop()
        help_text = self.item(dialog, 'missing-mod-multiplayer-help').property('text')
        self.check('向房主索要' in help_text and '房主没有使用的模组无需补齐' in help_text,
                   'dialog explains the host-dependent multiplayer requirement')
        self.check('缺少必需模组' in self.item(dialog, 'missing-mod-warning').property('text'),
                   'skipping cannot silently promise a runnable modded game')
        self.check(not (self.game_dir / 'versions/Missing-Mods').exists(), 'instance is not published before choice')
        self.screenshot_ui('missing-mods-before-choice', dialog)
        self.click_ui(dialog, 'missing-mod-continue')
        task = self.finished_task()
        target = self.game_dir / 'versions/Missing-Mods'
        self.check((target / 'mods/public.jar').read_bytes() == contents['public.jar'], 'other mod bytes installed')
        self.check(not (target / 'mods/private.jar').exists(), 'only the approved missing mod is skipped')
        self.check('已跳过 1 个模组' in task['status'] and task['skipped_mods'][0]['name'] == 'private.jar',
                   'completion and history retain the skipped-mod warning')
        metadata = json.loads((target / 'buggcraft-modpack.json').read_text(encoding='utf-8'))
        self.check(metadata['skippedMods'][0]['path'] == 'mods/private.jar', 'instance retains missing-mod receipt')
        self.wait_for(lambda: tasks._mod_prompts.dialog is None, 'decision dialog closes after skip')
        self.screenshot_ui('missing-mods-import-completed')
        self.assert_no_qml_errors()
        self.finish_test()

    def test_stop_then_retry_gets_republished_mod_without_skipping(self):
        tasks, dialog, contents = self.start()
        self.click_ui(dialog, 'missing-mod-stop')
        task = self.finished_task(state='已取消')
        self.check(not (self.game_dir / 'versions/Missing-Mods').exists(), 'stop leaves no incomplete instance')
        self.fixtures.failures.clear()
        self.click_ui(tasks, 'task-action-' + task['id'])
        self.finished_task(task)
        self.check((self.game_dir / 'versions/Missing-Mods/mods/private.jar').read_bytes() == contents['private.jar'],
                   'retry really downloads the newly available mod')
        self.check('已跳过' not in task['status'] and tasks._mod_prompts.dialog is None,
                   'available file needs no second skip decision')
        self.assert_no_qml_errors()
        self.finish_test()

    def test_escape_stops_import_without_implicit_skip(self):
        tasks, dialog, _contents = self.start()
        self.key_ui(dialog, Qt.Key_Escape, 'missing-mod-escape')
        self.finished_task(state='已取消')
        self.check(not (self.game_dir / 'versions/Missing-Mods').exists(), 'Escape never approves a missing mod')
        self.assert_no_qml_errors()
        self.finish_test()

    def test_shutdown_releases_import_waiting_for_user(self):
        tasks, _dialog, _contents = self.start()
        tasks.shutdown()
        self.wait_for(lambda: not tasks._workers, 'shutdown cancels consent wait without hanging')
        self.check(tasks._mod_prompts.dialog is None and not tasks._mod_prompts.pending,
                   'shutdown closes pending dialogs')
        self.check(not (self.game_dir / 'versions/Missing-Mods').exists(), 'shutdown never silently skips')
        self.assert_no_qml_errors()
        self.finish_test()

    def test_two_imports_queue_separate_decisions(self):
        tasks, first, _contents = self.start()
        archive = tasks._tasks[0]['modpack']
        second_game = self.directory / 'second-game'
        tasks.start_install('Second-Missing', str(second_game), modpack=archive)
        self.wait_for(lambda: len(tasks._mod_prompts.pending) == 1,
                      'second import queues its decision while first dialog is visible')
        self.check(tasks._mod_prompts.dialog is first, 'pending imports cannot replace an unanswered dialog')
        self.click_ui(first, 'missing-mod-continue')
        self.wait_for(lambda: tasks._mod_prompts.dialog is not None and tasks._mod_prompts.dialog is not first,
                      'second missing-mod decision opens after first is answered')
        second = tasks._mod_prompts.dialog
        self.wait_for(second.isVisible, 'second import has its own visible dialog')
        self.check(second.controller.data['instance'] == 'Second-Missing', 'decision belongs to the correct instance')
        self.click_ui(second, 'missing-mod-stop')
        for task in tasks._tasks:
            self.finished_task(task, state='已取消' if task['version'] == 'Second-Missing' else '已完成')
        self.check(not (second_game / 'versions/Second-Missing').exists(), 'second stop does not inherit first consent')
        self.assert_no_qml_errors()
        self.finish_test()

    def test_local_unpublished_mod_is_installed_from_archive_without_dialog(self):
        archive, contents = self.pack(missing=False)
        host, _ = self.open_import(archive)
        self.text_ui(host, 'pack-instance-name', 'Local-Private')
        self.click_ui(host, 'start-pack-import')
        self.finished_task()
        self.check((self.game_dir / 'versions/Local-Private/mods/private.jar').read_bytes() == contents['private.jar'],
                   'unpublished mod bundled by production exporter imports directly')
        self.check(self.window.download_page.tasks_page._mod_prompts.dialog is None,
                   'a bundled local mod does not request unnecessary consent')
        self.assert_no_qml_errors()
        self.finish_test()
