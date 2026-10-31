"""Click the real missing-mod dialog and finish/cancel production imports."""
import hashlib
import json
import os
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QTimer, Qt

from test_client_ui_acceptance import ClientUiAcceptanceCase as _UiCase
import test_download_ui as download_ui


class MissingModsUiTests(_UiCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if os.name == 'nt' and cls.app.platformName() == 'offscreen':
            from PySide6.QtGui import QFontDatabase, QFont
            QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
            cls.app.setFont(QFont('Microsoft YaHei'))

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
                    downloads=['https://edge.forgecdn.net/files/123/4/' + name])
        archive = self.directory / 'missing-mods.buggpack'
        with patch('core.modpack_sources.find_public_mod_downloads', return_value=public):
            export_pack(source, 'Source', archive)
        original_route = self.fixtures.route
        def route(downloader, url):
            if url.startswith('https://edge.forgecdn.net/files/123/4/'):
                return [f'http://127.0.0.1:{self.fixtures.server.server_port}/' + url.rsplit('/', 1)[-1]]
            return original_route(downloader, url)
        self._patch(patch('core.downloads.MinecraftDownloader.urls', route))
        if missing:
            self.fixtures.failures.add('private.jar')
        return archive, contents

    def start(self, failure_status=None):
        archive, contents = self.pack()
        if failure_status:
            self.fixtures.failure_statuses = {'private.jar': failure_status}
        host, _ = self.open_import(archive)
        self.text_ui(host, 'pack-instance-name', 'Missing-Mods')
        self.click_ui(host, 'start-pack-import')
        tasks = self.window.download_page.tasks_page
        self.wait_for(lambda: tasks._mod_prompts.dialog is not None, 'missing public mod opens decision dialog')
        dialog = tasks._mod_prompts.dialog
        self.wait_for(dialog.isVisible, 'missing mod dialog is visible')
        return tasks, dialog, contents

    def test_retry_download_entry_and_export_list_keep_successful_files(self):
        from PySide6.QtWidgets import QApplication
        tasks, dialog, contents = self.start()
        self.click_ui(dialog, 'missing-mod-copy')
        self.wait_for(lambda: 'private.jar' in QApplication.clipboard().text(), 'copy real missing-file list')
        copied = QApplication.clipboard().text()
        self.check('https://edge.forgecdn.net/files/123/4/private.jar' in copied,
                   'manual list includes the exact file URL')
        self.check(hashlib.sha256(contents['private.jar']).hexdigest() in copied,
                   'manual list includes the original integrity requirement')
        report = self.directory / 'manual-downloads.txt'
        with patch('ui.dialog.modpack_missing.QFileDialog.getSaveFileName', return_value=(str(report), 'txt')):
            self.click_ui(dialog, 'missing-mod-save')
        self.check(report.read_text(encoding='utf-8') == copied, 'save produces a usable text checklist')
        with patch('ui.dialog.modpack_missing.QDesktopServices.openUrl', return_value=True) as opened:
            self.click_ui(dialog, 'missing-mod-download-0')
        self.check(opened.call_args.args[0].toString().endswith('/private.jar'), 'button opens the exact download')
        before = sum(row['file'] == 'public.jar' for row in self.fixtures.requests)
        self.fixtures.failures.clear()
        self.click_ui(dialog, 'missing-mod-retry')
        task = self.finished_task()
        self.check((self.game_dir / 'versions/Missing-Mods/mods/private.jar').read_bytes() == contents['private.jar'],
                   'retry really fetches missing bytes and finishes the original import')
        self.check(before == sum(row['file'] == 'public.jar' for row in self.fixtures.requests),
                   'retry leaves successful mods in cache')
        self.check('已跳过' not in task['status'], 'repair is reported as a full import')
        self.assert_no_qml_errors()
        self.finish_test()

    def test_manual_repair_rejects_wrong_file_then_accepts_exact_file(self):
        tasks, dialog, contents = self.start()
        wrong, correct = self.directory / 'wrong.jar', self.directory / 'correct.jar'
        wrong.write_bytes(b'X' * len(contents['private.jar']))
        correct.write_bytes(contents['private.jar'])
        with patch('ui.dialog.modpack_missing.QFileDialog.getOpenFileName', return_value=(str(wrong), 'jar')):
            self.click_ui(dialog, 'missing-mod-supply-0')
        self.wait_for(lambda: tasks._mod_prompts.dialog is not None and tasks._mod_prompts.dialog is not dialog,
                      'wrong manual download reopens the checklist without failing the task')
        repaired = tasks._mod_prompts.dialog
        self.wait_for(repaired.isVisible, 'manual checksum feedback is visible')
        self.check('校验不匹配' in repaired.controller.data['mods'][0]['reason'],
                   'same-size wrong file cannot be installed')
        self.check(not (self.game_dir / 'versions/Missing-Mods').exists(), 'wrong file never publishes an instance')
        self.screenshot_ui('missing-mods-wrong-manual-file', repaired)
        with patch('ui.dialog.modpack_missing.QFileDialog.getOpenFileName', return_value=(str(correct), 'jar')):
            self.click_ui(repaired, 'missing-mod-supply-0')
        self.finished_task()
        target = self.game_dir / 'versions/Missing-Mods'
        self.check((target / 'mods/private.jar').read_bytes() == contents['private.jar'],
                   'the exact manually supplied file is installed')
        self.check(correct.read_bytes() == contents['private.jar'], 'manual source remains available to the user')
        self.check(not (target / '缺失模组清单.txt').exists(), 'completed repairs do not retain a stale missing list')
        self.assert_no_qml_errors()
        self.finish_test()

    def test_network_failure_can_continue_and_retains_manual_checklist(self):
        tasks, dialog, contents = self.start(failure_status=503)
        self.check('503' in dialog.controller.data['mods'][0]['reason'],
                   'server failures display a concise cause instead of raw JSON')
        self.screenshot_ui('missing-mods-network-failure', dialog)
        self.click_ui(dialog, 'missing-mod-continue')
        self.finished_task()
        target = self.game_dir / 'versions/Missing-Mods'
        report = (target / '缺失模组清单.txt').read_text(encoding='utf-8')
        self.check('private.jar' in report and hashlib.sha256(contents['private.jar']).hexdigest() in report,
                   'after choosing continue the user can still find exact manual downloads')
        self.check((target / 'mods/public.jar').read_bytes() == contents['public.jar'],
                   'working files remain installed after a server failure')
        self.assert_no_qml_errors()
        self.finish_test()

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
