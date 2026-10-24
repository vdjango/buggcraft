"""Player report mc2: malformed versions, progress, concurrency and native windows."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
import zipfile
from unittest.mock import Mock, patch

from _qml_test_support import LauncherQmlCase
from config.settings import SettingsManager
from core import loaders
from utils.install_progress import InstallProgress
from utils.instances import installed_instance_ids


class LocalVersionSafetyTests(unittest.TestCase):
    def test_missing_optional_fields_and_corrupt_neighbor_do_not_block_startup(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            fixtures = {
                '1.20.1': {'id': '1.20.1', 'type': 'release', 'releaseTime': '2023-06-12T12:00:00Z'},
                'Forge': {'id': 'Forge', 'inheritsFrom': '1.20.1'},
                '永生-公测V1.1d': {'id': '永生-公测V1.1d', 'inheritsFrom': 'Forge', 'jar': '1.20.1'},
                'broken': '{unfinished', 'array': [],
            }
            for name, data in fixtures.items():
                target = root / 'versions' / name / (name + '.json')
                target.parent.mkdir(parents=True)
                target.write_text(data if isinstance(data, str) else json.dumps(data), encoding='utf-8')
            before = {p: p.read_bytes() for p in root.rglob('*.json')}
            with patch('config.settings.get_default_minecraft_dir', return_value=root), \
                    patch('minecraft_launcher_lib.utils.get_installed_versions', side_effect=AssertionError('unsafe scanner')):
                settings = SettingsManager(root / 'settings')
            expected = ['1.20.1', 'Forge', '永生-公测V1.1d']
            self.assertEqual(settings.get_setting('minecraft.version.installed'), expected)
            self.assertEqual(installed_instance_ids(root), expected)
            self.assertEqual({p: p.read_bytes() for p in before}, before)

    def test_installer_progress_changes_units_and_never_exceeds_percentage(self):
        values = []
        progress = InstallProgress(values.append)
        progress.set_progress(500)
        progress.set_max(5 * 1024 ** 3)
        progress.set_progress(4 * 1024 ** 3)
        self.assertEqual(values[-1], 80)
        progress.set_max(2)
        self.assertEqual(values[-1], 0)
        progress.set_progress(5000)
        progress.set_max(0)
        progress.set_progress(-1)
        self.assertTrue(all(0 <= value <= 100 for value in values))
        self.assertEqual(values[-1], 0)

    def test_forge_dependency_subprocess_is_quiet_and_global_module_unchanged(self):
        original = loaders.minecraft_launcher_lib.forge.subprocess
        with patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, b'processor output')) as run:
            with loaders._use_download_source('官方'):
                scoped = loaders.minecraft_launcher_lib.forge.subprocess
                self.assertIsNot(scoped, subprocess)
                scoped.run(['java', '-cp', 'fixture', 'Processor'])
                self.assertIs(loaders.subprocess, subprocess)
                kwargs = run.call_args.kwargs
                if os.name == 'nt':
                    self.assertTrue(kwargs['creationflags'] & subprocess.CREATE_NO_WINDOW)
                self.assertEqual(kwargs['stdin'], subprocess.DEVNULL)
                self.assertEqual(kwargs['stdout'], subprocess.PIPE)
                self.assertTrue(kwargs['check'])
        self.assertIs(loaders.minecraft_launcher_lib.forge.subprocess, original)

    @unittest.skipUnless(os.name == 'nt', 'Windows console behavior')
    def test_real_dependency_child_has_no_windows_console(self):
        with loaders._use_download_source('官方'):
            result = loaders.minecraft_launcher_lib.forge.subprocess.run([
                sys.executable, '-c', 'import ctypes; print(ctypes.windll.kernel32.GetConsoleWindow())'])
        self.assertEqual(result.stdout.strip(), b'0')

    def test_forge_processor_failure_keeps_error_and_restores_patches(self):
        original = loaders.minecraft_launcher_lib.forge.subprocess
        with patch.object(subprocess, 'run', side_effect=subprocess.CalledProcessError(9, ['java'], output=b'missing patch input')):
            with self.assertRaisesRegex(RuntimeError, 'missing patch input'):
                with loaders._use_download_source('官方'):
                    loaders.minecraft_launcher_lib.forge.subprocess.run(['java'])
        self.assertIs(loaders.minecraft_launcher_lib.forge.subprocess, original)


class ReportedUiTests(LauncherQmlCase):
    def test_online_pack_retry_reuses_archive_and_original_task_after_install_failure(self):
        page = self.window.download_page.tasks_page
        archive = self.directory / 'OnlinePack.zip'
        with zipfile.ZipFile(archive, 'w') as bundle:
            bundle.writestr('manifest.json', json.dumps(dict(manifestType='minecraftModpack', manifestVersion=1,
                name='Online pack', version='1', files=[], overrides='overrides',
                minecraft=dict(version='1.20.1', modLoaders=[dict(id='forge-47.4.0')]))))
            bundle.writestr('overrides/config/fixture.txt', 'online pack configuration')
        content = dict(kind='modpack', target=str(self.game_dir / 'downloads'),
                       version=dict(files=[dict(filename=archive.name)]))
        def install(*args, **kwargs):
            metadata = self.game_dir / 'versions/1.20.1/1.20.1.json'
            metadata.write_text(json.dumps(dict(id='1.20.1')), encoding='utf-8')
            metadata.with_suffix('.jar').write_bytes(b'fixture client jar')
            return '1.20.1'
        with patch('core.content.download_content', return_value=[str(archive)]) as download:
            with patch('core.modpacks.install_loader', side_effect=RuntimeError('temporary install failure')):
                page.start_install('online-download', str(self.game_dir), content=content)
                self.wait_until(lambda: not page._workers)
            task = page._tasks[0]
            self.assertEqual(task['state'], '失败')
            self.assertEqual(task['modpack'], str(archive))
            self.assertTrue(task['archive_sha256'])
            original_id, identity = task['id'], task['version']
            with patch('core.modpacks.install_loader', side_effect=install):
                page.task_action(original_id)
                self.wait_until(lambda: not page._workers)
            self.assertEqual(download.call_count, 1)
        self.assertEqual(task['state'], '已完成')
        self.assertEqual(task['id'], original_id)
        self.assertEqual(task['version'], identity)
        self.assertEqual(len(page._tasks), 1)
        self.assertEqual((self.game_dir / 'versions' / identity / 'config/fixture.txt').read_text(), 'online pack configuration')

    def test_legacy_download_only_task_can_continue_installing_without_duplicate_history(self):
        page = self.window.download_page.tasks_page
        content = dict(kind='modpack', target=str(self.game_dir / 'downloads'),
                       version=dict(files=[dict(filename='Existing.zip')]))
        (self.game_dir / 'versions/Existing').mkdir()
        task = dict(id='legacy-download', version='old-download-label', game_dir=str(self.game_dir),
                    state='已完成', content=content, status='内容下载完成', logs=[], created_at='', progress=1, maximum=1)
        page._tasks = [task]
        with patch.object(page, '_start_worker') as start:
            page.task_action(task['id'])
        start.assert_called_once_with(task)
        self.assertEqual(task['state'], '等待中')
        self.assertEqual(task['version'], 'Existing-2')
        self.assertEqual(len(page._tasks), 1)

    def test_modpack_retry_resumes_same_task_without_opening_import_page(self):
        page = self.window.download_page.tasks_page
        archive = self.directory / 'resume.zip'
        manifest = dict(manifestType='minecraftModpack', manifestVersion=1, name='Retry fixture',
                        version='1', overrides='overrides', files=[],
                        minecraft=dict(version='1.20.1', modLoaders=[dict(id='forge-47.4.0')]))
        with zipfile.ZipFile(archive, 'w') as bundle:
            bundle.writestr('manifest.json', json.dumps(manifest))
            bundle.writestr('overrides/config/fixture.txt', 'original content')

        def recovered(*args, **kwargs):
            for identity, metadata in [('1.20.1', {'id': '1.20.1'}),
                                       ('forge-fixture', {'id': 'forge-fixture', 'inheritsFrom': '1.20.1'})]:
                target = self.game_dir / 'versions' / identity / (identity + '.json')
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(metadata), encoding='utf-8')
            (self.game_dir / 'versions/1.20.1/1.20.1.jar').write_bytes(b'fixture client jar')
            return 'forge-fixture'

        with patch('core.modpacks.install_loader', side_effect=RuntimeError('temporary processor failure')):
            self.assertTrue(page.start_install('RetryPack', str(self.game_dir), modpack=str(archive)))
            self.wait_until(lambda: not page._workers)
        self.assertEqual(page._tasks[0]['state'], '失败')
        task_id = page._tasks[0]['id']
        self.assertFalse((self.game_dir / 'versions/RetryPack').exists())
        with patch('core.modpacks.install_loader', side_effect=recovered), patch.object(page, 'import_modpack') as import_page:
            page.task_action(task_id)
            self.wait_until(lambda: not page._workers)
            import_page.assert_not_called()
        self.assertEqual(len(page._tasks), 1)
        self.assertEqual(page._tasks[0]['id'], task_id)
        self.assertEqual(page._tasks[0]['state'], '已完成')
        self.assertTrue(any('恢复' in line for line in page._tasks[0]['logs']))
        target = self.game_dir / 'versions/RetryPack/config/fixture.txt'
        self.assertEqual(target.read_text(encoding='utf-8'), 'original content')
        target.write_text('player changes', encoding='utf-8')
        with patch('core.modpacks.install_loader') as install:
            page.task_action(task_id)
            install.assert_not_called()
        self.assertEqual(target.read_text(encoding='utf-8'), 'player changes')
        self.assert_no_qml_errors()

    def test_modpack_retry_with_missing_archive_keeps_original_history_and_shows_failure(self):
        page = self.window.download_page.tasks_page
        task = dict(id='missing-pack', version='MissingPack', game_dir=str(self.game_dir),
                    modpack=str(self.directory / 'moved.zip'), state='已中断', progress=0, maximum=0,
                    created_at='', status='', error='', logs=['original error'])
        page._tasks = [task]
        page.task_action(task['id'])
        self.wait_until(lambda: not page._workers)
        self.assertEqual(task['state'], '失败')
        self.assertTrue(task['error'])
        self.assertEqual(task['logs'][0], 'original error')
        self.assertEqual(len(page._tasks), 1)
        self.assertFalse((self.game_dir / 'versions/MissingPack').exists())

    def test_retry_rejects_replaced_archive_before_loading_or_creating_instance(self):
        page = self.window.download_page.tasks_page
        archive = self.directory / 'replaced.zip'
        with zipfile.ZipFile(archive, 'w') as bundle:
            bundle.writestr('manifest.json', json.dumps(dict(manifestType='minecraftModpack', manifestVersion=1,
                name='Replacement', version='1', files=[], overrides='overrides',
                minecraft=dict(version='1.20.1', modLoaders=[]))))
        task = dict(id='replaced-pack', version='ReplacedPack', game_dir=str(self.game_dir), modpack=str(archive),
                    state='失败', progress=0, maximum=0, created_at='', status='', logs=[], archive_sha256='0' * 64)
        page._tasks = [task]
        with patch('core.modpacks.MinecraftDownloader.install') as install:
            page.task_action(task['id'])
            self.wait_until(lambda: not page._workers)
            install.assert_not_called()
        self.assertEqual(task['state'], '失败')
        self.assertIn('已被替换', task['error'])
        self.assertFalse((self.game_dir / 'versions/ReplacedPack').exists())

    def test_multiple_downloads_start_before_first_finishes_and_duplicates_do_not(self):
        page = self.window.download_page.tasks_page
        release = threading.Event()
        started = set()
        guard = threading.Lock()

        def download(version, target, *args, **kwargs):
            with guard:
                started.add(version['name'])
            if not release.wait(5):
                raise RuntimeError('concurrent downloads never started')
            return []

        try:
            with patch('core.content.download_content', side_effect=download):
                for index in range(3):
                    content = dict(kind='resourcepack', target=str(self.game_dir), version={'name': str(index)})
                    self.assertTrue(page.start_install('resource-' + str(index), str(self.game_dir), content=content))
                self.assertFalse(page.start_install('resource-0', str(self.game_dir), content=content))
                self.wait_until(lambda: len(started) == 3)
                self.assertEqual(len(page._workers), 3)
                release.set()
                self.wait_until(lambda: not page._workers)
                self.assertEqual([task['state'] for task in page._tasks], ['已完成'] * 3)
        finally:
            release.set()
            page.pool.waitForDone(5000)

    def test_stage_progress_handles_large_byte_counts_and_qml_clamps_old_history(self):
        page = self.window.download_page.tasks_page
        task = dict(id='progress-fixture', version='pack', game_dir=str(self.game_dir),
                    state='进行中', progress=0, maximum=0, created_at='', status='')
        page._tasks = [task]
        from ui.pages.download.tasks import DownloadWorker
        worker = DownloadWorker('progress-fixture', 'pack', str(self.game_dir), '官方')
        worker.signals.progress.connect(page.update_progress)
        worker.signals.progress.emit('progress-fixture', 4 * 1024 ** 3, 5 * 1024 ** 3)
        self.assertEqual(task['progress'], 4 * 1024 ** 3)
        page.update_progress(task['id'], -1, 4)
        self.assertEqual(task['progress'], 0)
        page.update_progress(task['id'], 55555, -1)
        self.assertEqual(task['progress'], 4)
        # Old persisted data can already contain an oversized counter.
        task['progress'] = 55555
        page.refresh_tasks()
        self.window.download_page.on_progress_clicked()
        self.pump(120)
        self.assertEqual(self.item(page, 'task-progress-progress-fixture').property('text'), '阶段进度 100%')
        self.assert_no_qml_errors()

    def test_lobby_is_not_owned_by_launcher_and_retains_instance_context(self):
        start = self.window.started_page
        start.show_multiplayer_dialog()
        lobby = start._multiplayer_dialog
        self.pump()
        self.assertIsNone(lobby.parentWidget())
        self.assertIsNone(lobby.windowHandle().transientParent())
        if os.name == 'nt' and os.environ.get('QT_QPA_PLATFORM') == 'windows':
            import ctypes
            ctypes.windll.user32.GetWindow.restype = ctypes.c_void_p
            self.assertFalse(ctypes.windll.user32.GetWindow(ctypes.c_void_p(int(lobby.winId())), 4))
        self.assertIs(lobby.backend.launcher_page, start)
        self.assertEqual(lobby.backend.view['instanceId'], '1.21.8')
        self.window.showMinimized()
        self.pump(100)
        self.assertTrue(lobby.isVisible())
        self.assertFalse(lobby.isMinimized())
        lobby.showMinimized()
        start.show_multiplayer_dialog()
        self.pump()
        self.assertFalse(lobby.isMinimized())
        lobby.shutdown()
        self.assertTrue(lobby.backend.closed)
        self.assert_no_qml_errors()

    def test_friend_notifications_queue_and_skip_expired_invitations(self):
        lobby = self.window.started_page._ensure_multiplayer_dialog()
        first = dict(id='first', account='a' * 32 + '.' + 'b' * 32, username='Alice')
        second = dict(id='second', account='c' * 32 + '.' + 'd' * 32, username='Bob')
        lobby.backend.patch(socialReady=True, friendInvitations=[first, second])
        lobby.show_friend_invitation(first)
        lobby.show_friend_invitation(second)
        lobby.show_friend_invitation(second)
        self.assertEqual(lobby._invitation['id'], 'first')
        self.assertEqual(len(lobby._invitation_queue), 1)
        lobby.invitation_action('查看邀请')
        self.pump(60)
        self.assertTrue(lobby.friends_window.isVisible())
        self.assertTrue(self.item(lobby.friends_window, 'join-friend-invite').isVisible())
        self.assertEqual(lobby._invitation['id'], 'second')
        lobby.backend.patch(friendInvitations=[])
        self.pump(60)
        self.assertIsNone(lobby.invitation_dialog)
        lobby.shutdown()
        self.assert_no_qml_errors()

    def test_personal_node_starts_background_friend_reception_without_opening_hall(self):
        start = self.window.started_page
        store = Mock(data={'nodes': ['anonymous.json', 'personal.json']})
        dialog = Mock()
        with patch('hookup.storage.LobbyStore', return_value=store), \
                patch('hookup.profiles.RelayProfile.load', side_effect=[Mock(token='guest'), Mock(token='acct1.fixture')]), \
                patch.object(start, '_ensure_multiplayer_dialog', return_value=dialog):
            start._start_background_social()
        dialog.backend.reload_store.assert_called_once_with(select='personal.json')
        dialog.show.assert_not_called()
