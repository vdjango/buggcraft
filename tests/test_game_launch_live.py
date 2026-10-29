"""Opt-in Windows acceptance using an installed, unmodified Minecraft client.

BUGGCRAFT_LIVE_GAME_DIR points to a complete game root (assets/libraries/versions).
No command, JVM, native library, installation check or game output is mocked.
Only immutable installation files are linked into an isolated test directory.
"""
import ctypes
from ctypes import wintypes
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import unittest
import zipfile
from threading import Event
from unittest.mock import patch

import psutil
from PySide6.QtCore import Qt

from test_client_ui_acceptance import ClientUiAcceptanceCase as _UiCase
import test_home_ui as home_ui
import test_settings_ui as settings_ui
import test_download_ui as download_ui
from core.loaders import available_versions as REAL_LOADER_VERSIONS
from core.downloads import MinecraftDownloader, MANIFEST_URL
from utils.diagnostics import SafeFormatter

REAL_DOWNLOAD_URLS = MinecraftDownloader.urls


@unittest.skipUnless(os.name == 'nt' and os.environ.get('BUGGCRAFT_LIVE_GAME_DIR'),
                     'Set BUGGCRAFT_LIVE_GAME_DIR for real Windows Minecraft acceptance')
class RealMinecraftUiTests(_UiCase):
    offline_login = home_ui.HomeChecklistUiTests.offline_login
    settings_tab = settings_ui.ClientUiSettingsTests.settings_tab
    scroll_control = settings_ui.ClientUiSettingsTests.scroll_control
    setting_click = settings_ui.ClientUiSettingsTests.setting_click
    select_choice = settings_ui.ClientUiSettingsTests.select_choice
    choose_box = settings_ui.ClientUiSettingsTests.choose_box
    slider_limit = settings_ui.ClientUiSettingsTests.slider_limit
    open_downloads = download_ui.DownloadChecklistUiTests.open_downloads
    KINDS = download_ui.DownloadChecklistUiTests.KINDS
    open_kind = download_ui.DownloadChecklistUiTests.open_kind
    open_project = download_ui.DownloadChecklistUiTests.open_project
    content_dialog = download_ui.DownloadChecklistUiTests.content_dialog
    open_import = download_ui.DownloadChecklistUiTests.open_import
    reveal_control = download_ui.DownloadChecklistUiTests.reveal_control

    def setUp(self):
        super().setUp()
        self.lines, self.exits, self.errors, self.launches = [], [], [], []
        (self.output / 'game-output.log').write_text('', encoding='utf-8')
        source = Path(os.environ['BUGGCRAFT_LIVE_GAME_DIR']).resolve()
        self.version = os.environ.get('BUGGCRAFT_LIVE_GAME_VERSION', '1.21.8')
        self.assertTrue((source / 'versions' / self.version / (self.version + '.jar')).is_file())

        def link_file(src, dst):
            try:
                os.link(src, dst)
            except OSError:
                shutil.copy2(src, dst)
            return dst

        # Copy writable metadata; never link options, logs, saves or user caches.
        for name in ('assets', 'libraries'):
            shutil.copytree(source / name, self.game_dir / name, copy_function=link_file)
        target = self.game_dir / 'versions' / self.version
        target.mkdir(parents=True, exist_ok=True)
        for suffix in ('.json', '.jar'):
            shutil.copy2(source / 'versions' / self.version / (self.version + suffix),
                         target / (self.version + suffix))
        receipt = source / 'versions' / self.version / '.buggcraft-complete.json'
        shutil.copy2(receipt, target / receipt.name)
        if (source / 'versions' / self.version / 'natives').is_dir():
            shutil.copytree(source / 'versions' / self.version / 'natives', target / 'natives',
                            copy_function=link_file)
        from core.downloads import verified_installation
        self.assertTrue(verified_installation(self.game_dir, self.version),
                        'Copied real installation must pass production verification before launching')
        print('Real game installation verified:', self.game_dir, flush=True)
        java = os.environ.get('BUGGCRAFT_LIVE_JAVA') or shutil.which('java')
        self.assertTrue(java, 'A real Java runtime is required')
        self.java = os.path.realpath(java)
        from config.javafinder import JavaPathFinder
        raw, parsed = JavaPathFinder()._get_java_version(self.java)
        self.assertTrue(raw and parsed, self.java)
        self.manager.set_setting('java.installations', [[self.java, raw, list(parsed)]])
        self.manager.set_setting('java.path', self.java)
        self.manager.set_setting('minecraft.version.enable', self.version)
        self.manager.set_setting('minecraft.auto_allocate_memory', False)
        self.manager.set_setting('memory.allocation', 2048)
        self.manager.set_setting('minecraft.isolation', True)
        self.manager.set_setting('launcher.visibility', '游戏启动后保持不变')
        self.manager.set_setting('launcher.debug', '否（推荐）')
        # Discard the inherited fake Python runtime, retaining actual Java detection.
        self.window.settings_page.global_version_page.controller.reload()
        self.sessions = self.window.started_page.launcher
        self.sessions.signals.output.connect(self.capture_output)
        self.sessions.signals.stopped.connect(self.exits.append)
        self.sessions.signals.error.connect(self.errors.append)
        self.log_handler = logging.FileHandler(self.output / 'launcher.log', mode='w', encoding='utf-8')
        self.log_handler.setFormatter(SafeFormatter('%(asctime)s %(levelname)s %(name)s %(message)s'))
        self.root_logger = logging.getLogger()
        self.previous_level = self.root_logger.level
        self.root_logger.setLevel(logging.INFO)
        self.root_logger.addHandler(self.log_handler)
        self.addCleanup(self.close_log)
        self.offline_login('Live_Settings')

    def close_log(self):
        self.root_logger.removeHandler(self.log_handler)
        self.root_logger.setLevel(self.previous_level)
        self.log_handler.close()

    def capture_output(self, message):
        self.lines.append(message)
        with (self.output / 'game-output.log').open('a', encoding='utf-8') as stream:
            stream.write(message + '\n')

    def game_windows(self, pid):
        user32 = ctypes.windll.user32
        found = []
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        @callback_type
        def visit(hwnd, _):
            owner = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value == pid and user32.IsWindowVisible(hwnd):
                title = ctypes.create_unicode_buffer(512)
                user32.GetWindowTextW(hwnd, title, 512)
                rect = wintypes.RECT()
                user32.GetClientRect(hwnd, ctypes.byref(rect))
                if rect.right > 100 and rect.bottom > 100:
                    found.append(dict(handle=int(hwnd), title=title.value,
                                      width=rect.right, height=rect.bottom))
            return True

        user32.EnumWindows(visit, 0)
        return found

    def launch_game(self, label):
        self.navigate('launcher-nav-home')
        self.lines.clear()
        self.exits.clear()
        self.errors.clear()
        self.click_ui(self.window.started_page, 'launch-game')

        def created():
            if self.errors:
                self.fail('Real Minecraft launch failed: ' + '\n'.join(self.errors))
            return self.sessions.selected and self.sessions.selected['launcher'].process is not None

        self.wait_for(created, 'real Minecraft Java process is created', timeout=90000)
        self.process = self.sessions.selected['launcher'].process
        self.wait_for(lambda: self.game_windows(self.process.pid)
                      and any('textures/atlas/gui.png-atlas' in line for line in self.lines),
                      'real Minecraft creates a visible window and renders its GUI atlas', timeout=120000)
        self.pump(2500)
        self.check(self.process.poll() is None, 'Minecraft stays alive after resource loading')
        windows = self.game_windows(self.process.pid)
        hwnd = windows[0]['handle']
        ctypes.windll.user32.ShowWindow(hwnd, 9)
        ctypes.windll.user32.SetForegroundWindow(hwnd)
        self.pump(500)
        picture = self.app.primaryScreen().grabWindow(hwnd)
        path = self.screens / (label + '-minecraft.png')
        self.check(not picture.isNull() and picture.save(str(path)), 'capture actual Minecraft window')
        command = psutil.Process(self.process.pid).cmdline()
        self.check(Path(command[0]).samefile(self.java), 'actual process executes the configured Java')
        isolation = Path(self.manager.get_minecraft_isolation_directory())
        log = isolation / 'logs/latest.log'
        self.check(log.is_file(), 'Minecraft creates its own latest.log in the selected directory')
        shutil.copy2(log, self.output / (label + '-latest.log'))
        self.check('textures/atlas/gui.png-atlas' in log.read_text(encoding='utf-8'),
                   'fresh game log confirms GUI resources loaded')
        self.launches.append(dict(label=label, pid=self.process.pid, windows=windows,
                                  executable=command[0], command=command, directory=str(isolation),
                                  screenshot=str(path), priority=int(psutil.Process(self.process.pid).nice())))
        self.record('realMinecraft', str(self.process.pid), label)
        return command, isolation

    def close_game(self, label):
        pid = self.process.pid
        for window in self.game_windows(pid):
            ctypes.windll.user32.PostMessageW(window['handle'], 0x0010, 0, 0)  # WM_CLOSE
        self.record('closeGameWindow', str(pid), 'WM_CLOSE requests Minecraft normal shutdown')
        self.wait_for(lambda: not self.sessions._sessions, 'Minecraft exits and worker is reaped', timeout=30000)
        self.check(self.exits == [0], 'Minecraft exits normally with code zero')
        self.check(self.process.poll() == 0, 'actual JVM return code is zero on normal window close')
        self.check(not psutil.pid_exists(pid), 'no orphan Java process remains')
        self.launches[-1]['exit_codes'] = list(self.exits)
        self.launches[-1]['actual_returncode'] = self.process.returncode
        source = Path(self.launches[-1]['directory']) / 'logs/latest.log'
        shutil.copy2(source, self.output / (label + '-latest.log'))
        self.check(any('Stopping!' in line for line in self.lines), 'launcher retains the final game shutdown line')
        if self.window.isVisible():
            self.screenshot_ui(label + '-launcher-after-exit')

    def tearDown(self):
        if hasattr(self, 'sessions'):
            try:
                for row in list(self.sessions.sessions):
                    self.sessions.selected_id = row['id']
                    self.sessions.stop(force=True)
                self.wait_for(lambda: not self.sessions._sessions, 'all real Java workers finish', timeout=60000)
            finally:
                (self.output / 'real-game-report.json').write_text(json.dumps(dict(
                    version=self.version, launches=self.launches, errors=self.errors,
                    game_output_lines=len(self.lines)), ensure_ascii=False, indent=2), encoding='utf-8')
                # Preserve failure logs as well as successful-run evidence.
                for log in self.game_dir.rglob('latest.log'):
                    shutil.copy2(log, self.output / ('final-' + log.parent.parent.name + '-latest.log'))
                for log in self.game_dir.rglob('*installer*.log'):
                    shutil.copy2(log, self.output / log.name)
        super().tearDown()

    def test_home_real_minecraft_offline_launch_exit_and_relaunch(self):
        for label in ('first-launch', 'relaunch'):
            command, _ = self.launch_game(label)
            self.check('net.minecraft.client.main.Main' in command, 'production Minecraft main class runs')
            self.check('Live_Settings' in command, 'offline UI account reaches the game process')
            self.close_game(label)
        self.assert_no_qml_errors()
        self.finish_test()

    def use_real_game_download_payload(self):
        """Serve the original real client via HTTP; reuse verified shared assets."""
        source = Path(os.environ['BUGGCRAFT_LIVE_GAME_DIR'])
        root = source / 'versions' / self.version
        metadata = json.loads((root / (self.version + '.json')).read_text(encoding='utf-8'))
        self.fixtures.payloads['client.jar'] = (root / (self.version + '.jar')).read_bytes()
        metadata['downloads']['client'] = self.fixtures.file('client.jar')
        name = self.version + '.json'
        self.fixtures.payloads[name] = json.dumps(metadata).encode()
        self.fixtures.payloads['manifest.json'] = json.dumps({'versions': [dict(
            id=self.version, type='release', releaseTime=metadata['releaseTime'],
            **self.fixtures.file(name))]}).encode()
        return metadata

    def install_and_launch_real_loader(self, loader):
        """Keep real catalogue, installer, Maven files and JVM for each loader."""
        if loader == 'NeoForge':
            # Exercise the selected public mirror end to end. Source fallback
            # and official-only failure are separate deterministic HTTP tests.
            general = self.settings_tab(0)
            self.select_choice(general, 'settings.general.mirrors', 2)
        self.use_real_game_download_payload()
        # Third-party Forge/NeoForge installers consume this metadata too, and
        # some own their HTTP routing. Preserve the actual Mojang client URL;
        # the verified base client is already cached in this isolated root.
        original = Path(os.environ['BUGGCRAFT_LIVE_GAME_DIR']) / 'versions' / self.version / (self.version + '.json')
        metadata = json.loads(original.read_text(encoding='utf-8'))
        self.fixtures.payloads[self.version + '.json'] = json.dumps(metadata).encode()
        self.fixtures.payloads['manifest.json'] = json.dumps({'versions': [dict(
            id=self.version, type='release', releaseTime=metadata['releaseTime'],
            **self.fixtures.file(self.version + '.json'))]}).encode()
        # The existing client is served locally, all loader metadata/artifacts
        # use the production public routes. Never turn a fake JAR into a pass.
        def routes(downloader, url):
            if url == MANIFEST_URL or url.startswith(self.fixtures.ORIGIN + '/'):
                return self.fixtures.route(downloader, url)
            return REAL_DOWNLOAD_URLS(downloader, url)
        self._patch(patch.object(MinecraftDownloader, 'urls', routes))
        real_download_urls = __import__('core.loaders', fromlist=['_download_urls'])._download_urls
        def loader_routes(url, source):
            if url.startswith(self.fixtures.ORIGIN + '/'):
                return self.fixtures.route(None, url)
            return real_download_urls(url, source)
        self._patch(patch('core.loaders._download_urls', loader_routes))
        self._patch(patch('core.loaders.available_versions', REAL_LOADER_VERSIONS))
        page = self.open_downloads()
        page.controller.versions = [dict(id=self.version, type='release')]
        page.controller.changed.emit()
        self.pause_ui()
        self.click_ui(page, 'install-' + self.version)
        self.reveal_control(page, 'component-' + loader)
        self.click_ui(page, 'component-' + loader)
        self.wait_for(lambda: not page.controller.loader_busy,
                      'public loader catalogue responds: ' + loader, timeout=120000)
        self.check(bool(page.controller.component_versions),
                   'real compatible loader versions are available: ' + page.controller.loader_status)
        # Use the numerically newest stable version, not service iteration order.
        import re
        choices = page.controller.component_versions
        stable = [i for i, row in enumerate(choices) if not any(
            marker in row['name'].lower() for marker in ('beta', 'alpha', 'snapshot'))]
        index = max(stable or range(len(choices)), key=lambda i: tuple(
            int(part) for part in re.findall(r'\d+', choices[i]['name'])))
        # Scroll the actual ListView to the chosen row before clicking it.
        from PySide6.QtCore import QMetaObject, Q_ARG
        listing = self.item(page, 'component-version-list')
        QMetaObject.invokeMethod(listing, 'positionViewAtIndex', Qt.DirectConnection,
                                 Q_ARG(int, index), Q_ARG(int, 1))
        self.pause_ui()
        chosen = choices[index]['name']
        self.click_ui(page, 'component-version-' + str(index))
        self.check(page.controller.loader_version == chosen, 'UI commits real loader version')
        self.click_ui(page, 'install-selected-game')
        tasks = self.window.download_page.tasks_page
        task = tasks._tasks[0]
        self.wait_for(lambda: task['id'] not in tasks._workers,
                      'real loader installer completes: ' + loader, timeout=600000)
        self.check(task['state'] == '已完成', loader + ': ' + task.get('error', ''))
        self.navigate('instances-button')
        self.click_ui(self.window.version_page.versions_page, 'instance-row-' + task['version'])
        command, isolation = self.launch_game('real-' + loader.lower())
        log = (isolation / 'logs/latest.log').read_text(encoding='utf-8')
        evidence = ('Fabric Loader' in log if loader == 'Fabric' else
                    'Quilt Loader' in log if loader == 'Quilt' else
                    any(loader.lower() in str(value).lower() for value in command))
        self.check(evidence, 'actual Java/Minecraft uses installed loader: ' + loader)
        self.close_game('real-' + loader.lower())
        if loader == 'Fabric':
            self.download_and_load_actual_mod_with_dependency(task['version'])
        self.assert_no_qml_errors()
        self.finish_test()

    def download_and_load_actual_mod_with_dependency(self, identity):
        """Install a valid metadata-only mod plus a required nested dependency."""
        from client_ui_fixtures import archive_bytes
        dependency = archive_bytes({'fabric.mod.json': json.dumps(dict(
            schemaVersion=1, id='acceptance_dependency', version='1.0.0',
            name='Functional acceptance dependency', environment='*'))})
        mod = archive_bytes({'fabric.mod.json': json.dumps(dict(
            schemaVersion=1, id='ui_fixture', version='1.0.0',
            name='Functional acceptance mod', environment='*',
            depends={'fabricloader': '>=0.16.0', 'minecraft': self.version,
                     'java': '>=21', 'acceptance_dependency': '*'},
            jars=[{'file': 'META-INF/jars/acceptance-dependency.jar'}])),
            'META-INF/jars/acceptance-dependency.jar': dependency})
        self.fixtures.payloads['ui-fixture-mod.jar'] = mod
        _page, _controller, dialog = self.content_dialog('mod')
        self.click_ui(dialog, 'content-download-confirm')
        tasks = self.window.download_page.tasks_page
        task = tasks._tasks[0]
        self.wait_for(lambda: task['id'] not in tasks._workers, 'real mod download finishes')
        self.check(task['state'] == '已完成', 'downloaded mod task completes')
        expected = self.game_dir / 'versions' / identity / 'mods/ui-fixture-mod.jar'
        self.check(expected.read_bytes() == mod, 'downloaded mod bytes reach selected Fabric instance')
        _command, isolation = self.launch_game('fabric-downloaded-mod-with-dependency')
        log = (isolation / 'logs/latest.log').read_text(encoding='utf-8')
        self.check('ui_fixture 1.0.0' in log and 'acceptance_dependency 1.0.0' in log,
                   'real Fabric loader resolves the downloaded mod and required dependency')
        self.close_game('fabric-downloaded-mod-with-dependency')

    def test_download_real_fabric_install_and_launch(self):
        self.install_and_launch_real_loader('Fabric')

    def test_download_real_quilt_install_and_launch(self):
        self.install_and_launch_real_loader('Quilt')

    def test_download_real_forge_install_and_launch(self):
        self.install_and_launch_real_loader('Forge')

    def test_download_real_neoforge_install_and_launch(self):
        self.install_and_launch_real_loader('NeoForge')

    def test_download_vanilla_installs_real_client_and_launches_from_instance_list(self):
        self.use_real_game_download_payload()
        target = self.game_dir / 'versions' / self.version
        for name in (self.version + '.jar', self.version + '.json', '.buggcraft-complete.json'):
            (target / name).unlink()
        page = self.open_downloads()
        page.controller.versions = [dict(id=self.version, type='release')]
        page.controller.changed.emit()
        self.pause_ui()
        self.click_ui(page, 'install-' + self.version)
        self.click_ui(page, 'install-selected-game')
        tasks = self.window.download_page.tasks_page
        task = tasks._tasks[0]
        self.wait_for(lambda: task['id'] not in tasks._workers, 'real vanilla installation finishes', timeout=120000)
        self.check(task['state'] == '已完成', 'vanilla task completes: ' + task.get('error', ''))
        self.check((target / (self.version + '.jar')).read_bytes() == self.fixtures.payloads['client.jar'],
                   'fresh installation publishes the original Minecraft client bytes')
        self.check(any(row['file'] == 'client.jar' for row in self.fixtures.requests),
                   'real client was transferred over HTTP during this UI installation')
        self.navigate('instances-button')
        self.click_ui(self.window.version_page.versions_page, 'instance-row-' + self.version)
        self.check(self.manager.get_setting('minecraft.version.enable') == self.version,
                   'new installation is selectable through the refreshed instance list')
        self.launch_game('downloaded-real-vanilla')
        self.close_game('downloaded-real-vanilla')
        self.assert_no_qml_errors()
        self.finish_test()

    def test_real_jvm_failure_and_game_abnormal_exit_keep_logs_and_allow_relaunch(self):
        home = self.window.started_page
        self.manager.set_version_setting('game.launch_jvm_args', '-XX:BUGGCRAFTInvalidOptionForRegression')
        self.manager.save_settings()
        self.click_ui(home, 'launch-game')
        self.wait_for(lambda: self.window._launch_error_dialog is not None
                      and self.window._launch_error_dialog.isVisible() and not self.sessions._sessions,
                      'actual JVM rejects invalid option and produces a visible failure', timeout=60000)
        self.check(any('BUGGCRAFTInvalidOptionForRegression' in line and 'Unrecognized' in line
                       for line in self.window._debug_output),
                   'launcher retains the actual JVM failure reason')
        self.click_ui(self.window._launch_error_dialog, 'dialog-action-0')
        self.check(self.window._debug_dialog.isVisible(), 'View log opens retained JVM failure output')
        self.screenshot_ui('real-jvm-failure-log', self.window._debug_dialog)
        self.key_ui(self.window._debug_dialog, Qt.Key_Escape, 'close-real-jvm-failure-log')
        self.manager.set_version_setting('game.launch_jvm_args', '')
        self.manager.save_settings()
        self.launch_game('after-jvm-option-repair')
        victim = self.process
        # Terminate only the exact Java child created and recorded by this test.
        victim.kill()
        self.wait_for(lambda: victim.poll() is not None and not self.sessions._sessions
                      and self.window._launch_error_dialog.isVisible(),
                      'unexpected real Minecraft exit restores Home and reports abnormal exit', timeout=30000)
        self.check(victim.returncode != 0 and self.exits and self.exits[-1] != 0,
                   'actual nonzero process exit is retained')
        self.launches[-1].update(actual_returncode=victim.returncode, externally_terminated=True)
        self.click_ui(self.window._launch_error_dialog, 'dialog-action-0')
        self.check(any(str(self.exits[-1]) in line for line in self.window._debug_output),
                   'diagnostic output contains the actual abnormal exit code')
        self.screenshot_ui('real-abnormal-exit-log', self.window._debug_dialog)
        self.key_ui(self.window._debug_dialog, Qt.Key_Escape, 'close-real-abnormal-exit-log')
        self.launch_game('after-real-abnormal-exit')
        self.close_game('after-real-abnormal-exit')
        self.assert_no_qml_errors()
        self.finish_test()

    def test_downloaded_and_imported_runnable_pack_preserve_instances_and_load_resources(self):
        from client_ui_fixtures import archive_bytes
        self.use_real_game_download_payload()
        source = Path(os.environ['BUGGCRAFT_LIVE_GAME_DIR']) / 'versions' / self.version / (self.version + '.jar')
        with zipfile.ZipFile(source) as client:
            pack_format = json.loads(client.read('version.json'))['pack_version']['resource']
        resource = archive_bytes({'pack.mcmeta': json.dumps({'pack': {
            'pack_format': pack_format, 'description': 'Functional acceptance resource pack'}})})
        pack = archive_bytes({'modrinth.index.json': json.dumps({
            'formatVersion': 1, 'game': 'minecraft', 'versionId': '1.0.0',
            'name': 'Runnable acceptance pack', 'files': [], 'dependencies': {'minecraft': self.version}}),
            'overrides/config/acceptance-marker.json': '{"installed":true}',
            'overrides/resourcepacks/functional-acceptance.zip': resource,
            'overrides/options.txt': 'lang:en_us\nresourcePacks:["vanilla","file/functional-acceptance.zip"]\n'})
        self.fixtures.payloads['ui-fixture-modpack.mrpack'] = pack
        self.fixtures.pack_path.write_bytes(pack)
        original = {p.name for p in (self.game_dir / 'versions').iterdir()}
        tasks = self.window.download_page.tasks_page
        for mode in ('download', 'import'):
            if mode == 'download':
                _page, _controller, dialog = self.content_dialog('modpack')
                self.click_ui(dialog, 'content-download-confirm')
            else:
                host, _controller = self.open_import()
                self.text_ui(host, 'pack-instance-name', 'runnable-import-pack')
                self.click_ui(host, 'start-pack-import')
            task = tasks._tasks[0]
            self.wait_for(lambda: task['id'] not in tasks._workers,
                          'runnable pack installation completes: ' + mode, timeout=120000)
            self.check(task['state'] == '已完成', 'runnable pack installed: ' + task.get('error', ''))
            self.check(original <= {p.name for p in (self.game_dir / 'versions').iterdir()},
                       'runnable pack never replaces preexisting instances')
            self.navigate('instances-button')
            instances = self.window.version_page.versions_page
            self.click_ui(instances, 'instance-row-' + task['version'])
            self.check(self.manager.get_setting('minecraft.version.enable') == task['version'],
                       'installed pack can be selected from refreshed instance list')
            _command, isolation = self.launch_game('runnable-pack-' + mode)
            log = (isolation / 'logs/latest.log').read_text(encoding='utf-8')
            self.check('functional-acceptance.zip' in log and 'Reloading ResourceManager' in log,
                       'actual Minecraft resource manager loads the installed pack resource')
            self.check((isolation / 'config/acceptance-marker.json').is_file(),
                       'game runs in the installed pack directory with its overrides')
            self.close_game('runnable-pack-' + mode)
        self.assert_no_qml_errors()
        self.finish_test()

    def test_settings_multiple_games_four_real_clients_and_stop_isolation(self):
        home = self.window.started_page
        self.launch_game('single-disabled')
        first = self.process
        self.click_ui(home, 'launch-game')
        self.wait_for(lambda: not self.sessions._sessions, 'single-mode Stop reaps actual Minecraft', timeout=30000)
        self.check(first.poll() is not None and self.sessions._sequence == 1,
                   'single mode stops its game instead of launching a second JVM')
        self.launches[-1].update(stop_requested=True, exit_codes=list(self.exits),
                                 actual_returncode=first.returncode)
        general = self.settings_tab(0)
        self.setting_click(general, 'setting-toggle-launcher.allow_multiple')
        children = []
        for count in range(1, 5):
            self.launch_game('multi-' + str(count))
            children.append(self.process)
            self.check(len(self.sessions.sessions) == count and
                       all(process.poll() is None for process in children),
                       'all real Minecraft clients stay alive: ' + str(count))
        self.check(len({process.pid for process in children}) == 4,
                   'four distinct real Java processes render their own Minecraft windows')
        self.screenshot_ui('four-real-game-sessions')
        self.click_ui(home, 'game-session-picker')
        self.key_ui(home, Qt.Key_Home, 'select-first-real-game')
        self.key_ui(home, Qt.Key_Return, 'confirm-first-real-game')
        self.check(self.sessions.selected['launcher'].process is children[0],
                   'session picker selects the first real game')
        for remaining in (3, 2, 1, 0):
            victim = self.sessions.selected['launcher'].process
            self.click_ui(home, 'game-session-actions')
            self.click_ui(home, 'stop-current-game')
            self.wait_for(lambda: len(self.sessions._sessions) == remaining,
                          'UI Stop reaps only selected real game: ' + str(victim.pid), timeout=30000)
            self.check(victim.poll() is not None, 'selected real JVM exits after UI Stop')
            record = next(row for row in self.launches if row['pid'] == victim.pid)
            record.update(stop_requested=True, actual_returncode=victim.returncode)
            self.check(all(row['launcher'].process.poll() is None for row in self.sessions.sessions),
                       'other real Minecraft clients remain running after stopping selected game')
            self.check(self.window._launch_error_dialog is None,
                       'intentional UI stopping is not reported as a game crash')
        self.check(home.controller.view['launchTitle'] == '启动游戏',
                   'stopping the last real game restores Home')
        self.assert_no_qml_errors()
        self.finish_test()

    def test_buggpack_export_both_modes_import_and_launch_real_game(self):
        from client_ui_fixtures import archive_bytes
        from core.content_records import record_content
        self.use_real_game_download_payload()
        instance = self.game_dir / 'versions' / self.version
        with zipfile.ZipFile(instance / (self.version + '.jar')) as client:
            pack_format = json.loads(client.read('version.json'))['pack_version']['resource']
        resource = instance / 'resourcepacks' / 'buggpack-acceptance.zip'
        resource.parent.mkdir(exist_ok=True)
        resource.write_bytes(archive_bytes({'pack.mcmeta': json.dumps({'pack': {
            'pack_format': pack_format, 'description': 'Buggcraft export roundtrip acceptance'}})}))
        (instance / 'config').mkdir(exist_ok=True)
        (instance / 'config/roundtrip.json').write_text('{"roundtrip":true}')
        (instance / 'options.txt').write_text(
            'lang:en_us\nresourcePacks:["vanilla","file/buggpack-acceptance.zip"]\n')
        url = 'https://cdn.modrinth.com/data/acceptance/buggpack-acceptance.zip'
        self.fixtures.payloads['buggpack-acceptance.zip'] = resource.read_bytes()
        route = self.fixtures.route
        self._patch(patch.object(self.fixtures, 'route', lambda downloader, value:
            ['http://127.0.0.1:%d/buggpack-acceptance.zip' % self.fixtures.server.server_port]
            if value == url else route(downloader, value)))
        record_content(instance, resource, [url])
        original = {path.name for path in (self.game_dir / 'versions').iterdir()}
        for mode, button in (('compact', 0), ('standard', 1)):
            self.navigate('instances-button')
            page = self.window.version_page.versions_page
            archive = self.output / (mode + '.buggpack')
            archive.unlink(missing_ok=True)
            with patch('ui.pages.qml_instances.QFileDialog.getSaveFileName', return_value=(str(archive), '')):
                self.click_ui(page, 'instance-export-' + self.version)
                self.click_ui(page.controller._export_dialog.host, 'dialog-action-' + str(button))
                self.wait_for(lambda: page.controller._export_worker is None, 'UI exports ' + mode + ' package', timeout=120000)
                self.check(page.controller._export_dialog.controller.data['phase'] == 'complete',
                           'export succeeds: ' + page.controller._export_dialog.controller.detail)
                self.check(page.controller._export_dialog.isVisible(), 'completed export awaits manual close')
                self.click_ui(page.controller._export_dialog, 'dialog-action-0')
            with zipfile.ZipFile(archive) as exported:
                manifest = json.loads(exported.read('buggcraft.pack.json'))
            selected = next(row for row in manifest['files'] if row['path'] == 'resourcepacks/' + resource.name)
            self.check(selected['embedded'] is (mode == 'standard'), 'selected export mode reaches real archive')
            self.check(selected['sha1'] == hashlib.sha1(self.fixtures.payloads[resource.name]).hexdigest(),
                       'export manifest matches the exact resource served by HTTP')
            host, import_controller = self.open_import(archive)
            self.check(Path(import_controller.pack_path) == archive.resolve(), 'UI imports the exported buggpack archive')
            self.text_ui(host, 'pack-instance-name', 'roundtrip-' + mode)
            self.click_ui(host, 'start-pack-import')
            tasks = self.window.download_page.tasks_page
            task = tasks._tasks[0]
            self.wait_for(lambda: task['id'] not in tasks._workers, 'real buggpack import completes', timeout=120000)
            self.check(task['state'] == '已完成', 'import success: ' + task.get('error', ''))
            self.check(original <= {p.name for p in (self.game_dir / 'versions').iterdir()}, 'existing versions retained')
            self.navigate('instances-button')
            self.click_ui(page, 'instance-row-' + task['version'])
            self.manager.set_setting('launcher.debug', '是')
            _command, isolation = self.launch_game('buggpack-' + mode)
            self.check((isolation / 'config/roundtrip.json').is_file(), 'pack configuration survives export and import')
            self.check((isolation / 'resourcepacks' / resource.name).read_bytes() == resource.read_bytes(), 'resource byte integrity')
            self.check(resource.name in (isolation / 'logs/latest.log').read_text(encoding='utf-8'), 'Minecraft loads imported resource pack')
            self.check(self.window._debug_dialog.isVisible() and self.window._debug_dialog.logs.rowCount() > 0,
                       'debug setting displays actual game output in filterable console')
            self.screenshot_ui('buggpack-' + mode + '-game-log', self.window._debug_dialog)
            self.click_ui(self.window._debug_dialog.host, 'dialog-action-0')
            self.close_game('buggpack-' + mode)
        self.assert_no_qml_errors()
        self.finish_test()

    def test_settings_real_window_visibility_resolution_priority_debug_and_custom_java(self):
        # The last mode closes the launcher after the final game exits.
        profiles = ((0, 0, 1, False), (1, 1, 0, True),
                    (2, 2, 2, False), (3, 0, 1, False))
        for visibility, resolution, priority, automatic in profiles:
            page = self.settings_tab(1)
            self.select_choice(page, 'launcher.visibility', visibility)
            self.select_choice(page, 'launcher.window_size', resolution)
            self.setting_click(page, 'setting-option-launcher.process_priority-' + str(priority))
            self.setting_click(page, 'setting-option-launcher.debug-' + str(0 if automatic else 1))
            if self.manager.get_version_setting('minecraft.auto_allocate_memory') != automatic:
                self.setting_click(page, 'setting-toggle-minecraft.auto_allocate_memory')
            # Select an executable through the real custom-Java UI, not by
            # substituting the command builder or its runtime validation.
            options = next(g for g in page.controller.groups if g['key'] == 'java.path')['options']
            with patch('ui.pages.qml_settings.QFileDialog.getOpenFileName', return_value=(self.java, '')):
                self.setting_click(page, 'setting-option-java.path-' + str(len(options) - 1))
            label = 'visibility-' + str(visibility)
            command, _ = self.launch_game(label)
            if visibility == 0:
                self.check(self.window.isVisible() and not self.window.isMinimized(), 'keep-visible mode')
            elif visibility == 1:
                self.check(self.window.isMinimized(), 'launcher minimizes while Minecraft is running')
            else:
                self.check(not self.window.isVisible(), 'launcher hides while Minecraft is running')
            actual = self.launches[-1]['windows'][0]
            if resolution == 2:
                self.check('--fullscreen' in command, 'fullscreen option reaches actual game command')
                self.check(actual['width'] >= 1280 and actual['height'] >= 720, 'actual fullscreen game window')
            else:
                width = int(command[command.index('--width') + 1])
                height = int(command[command.index('--height') + 1])
                self.check((actual['width'], actual['height']) == (width, height),
                           'actual game client area matches the selected resolution')
                if resolution == 0:
                    self.check((width, height) == (854, 480), 'default game resolution is 854 by 480')
                else:
                    from utils.helpers import get_physical_resolution
                    expected = get_physical_resolution(self.window.width(), self.window.height())
                    self.check((width, height) == tuple(map(int, expected)), 'launcher-size resolution')
            expected_priority = (psutil.HIGH_PRIORITY_CLASS, psutil.NORMAL_PRIORITY_CLASS,
                                 psutil.BELOW_NORMAL_PRIORITY_CLASS)[priority]
            self.check(psutil.Process(self.process.pid).nice() == expected_priority,
                       'actual Windows game process has the selected priority')
            if automatic:
                self.check(any('自动分配内存:' in line for line in self.lines), 'automatic memory is logged')
                self.check(any(arg.startswith('-Xmx') for arg in command), 'automatic memory reaches Java')
                debug = self.window._debug_dialog
                self.check(debug is not None and debug.isVisible(), 'debug mode opens the actual output window')
                self.check('textures/atlas/gui.png-atlas' in debug.controller.log, 'debug window receives real game output')
                self.screenshot_ui(label + '-debug-output', debug)
                self.click_ui(debug.host, 'dialog-action-0')
            else:
                debug = self.window._debug_dialog
                self.check(debug is None or not debug.isVisible(), 'debug-off mode leaves the output window closed')
            self.close_game(label)
            if visibility == 3:
                self.wait_for(lambda: self.window._closing, 'close-after-game mode closes the launcher')
                self.check(not self.window.isVisible(), 'launcher stays closed after game exit')
            else:
                self.wait_for(lambda: self.window.isVisible() and not self.window.isMinimized(),
                              'launcher restores after normal game exit')
        self.assert_no_qml_errors()
        self.finish_test()

    def test_settings_language_isolation_java_and_manual_memory_reach_game(self):
        for index, language in ((3, 'en_us'), (0, 'zh_cn')):
            general = self.settings_tab(0)
            self.choose_box(general, 'setting-select-game-language', index)
            self.check(self.manager.get_setting('game.language') == language, 'language chosen through UI')
            global_page = self.settings_tab(1)
            self.setting_click(global_page, 'setting-option-minecraft.isolation-' + str(index == 0 and 1 or 0))
            self.setting_click(global_page, 'setting-option-java.path-' + str(1 if index else 0))
            command, isolation = self.launch_game(language)
            self.check(f'lang:{language}' in (isolation / 'options.txt').read_text(encoding='utf-8'),
                       'Minecraft loads the language saved by Settings')
            self.check('-Xmx2048M' in command, 'manual memory reaches actual Java command')
            self.check(psutil.Process(self.process.pid).cwd() == str(isolation), 'real process uses selected isolation')
            self.close_game(language)
        self.assert_no_qml_errors()
        self.finish_test()

    def test_instance_independent_java_memory_isolation_reach_real_game(self):
        self.click_ui(self.window.title_bar, 'instances-button')
        instances = self.window.version_page.versions_page
        self.click_ui(instances, 'instance-row-' + self.version)
        self.click_ui(instances, 'instance-settings-' + self.version)
        page = self.window.version_page.settings_page
        self.setting_click(page, 'setting-toggle-instance.enable')
        self.setting_click(page, 'setting-option-minecraft.isolation-0')
        self.setting_click(page, 'setting-option-java.path-1')
        if self.manager.get_version_setting('minecraft.auto_allocate_memory'):
            self.setting_click(page, 'setting-toggle-minecraft.auto_allocate_memory')
        self.slider_limit(page, 'setting-memory-slider', False)
        for _ in range(2):
            self.key_ui(page, Qt.Key_Right, 'instance-memory-increment')
        self.check(self.manager.get_version_setting('memory.allocation') == 1536,
                   'instance memory changed through its actual slider')
        self.check(self.manager.get_setting('memory.allocation') == 2048,
                   'instance override leaves global memory unchanged')
        command, isolation = self.launch_game('independent-instance')
        self.check('-Xmx1536M' in command, 'instance memory reaches real Java')
        self.check(isolation == self.game_dir and psutil.Process(self.process.pid).cwd() == str(self.game_dir),
                   'instance isolation override reaches actual game directory')
        self.close_game('independent-instance')
        self.assert_no_qml_errors()
        self.finish_test()

    def test_settings_download_real_java_failure_retry_install_and_launch(self):
        from core.java_downloads import JavaPackage, java_platform
        runtime = Path(self.java).parent.parent
        archive = self.output / 'real-java-runtime.zip'
        # Repackage the installed, unmodified runtime for a controlled HTTP
        # download. The production installer executes its Java version probe.
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=1) as bundle:
            for directory in ('bin', 'lib', 'conf'):
                for path in (runtime / directory).rglob('*'):
                    if path.is_file() and path.suffix != '.jsa':
                        bundle.write(path, 'runtime/' + path.relative_to(runtime).as_posix())
            bundle.write(runtime / 'release', 'runtime/release')
        filename = archive.name
        payload = archive.read_bytes()
        self.fixtures.payloads[filename] = payload
        system, architecture = java_platform()
        entry = self.manager.get_setting('java.installations')[0]
        major = int(entry[2][0])
        package = JavaPackage('Local verified Java', major, '.'.join(map(str, entry[2])),
                              system, architecture, 'jre', filename,
                              hashlib.sha256(payload).hexdigest(), len(payload),
                              ('http://127.0.0.1:%d/%s' % (self.fixtures.server.server_port, filename),))
        private_root = self.directory / 'private-launcher'
        attempts = []

        def catalogue(major, source):
            attempts.append((major, source))
            if len(attempts) == 1:
                raise RuntimeError('local Java catalogue HTTP 503')
            return [package]

        page = self.settings_tab(2)
        with patch('ui.pages.qml_lists.catalogue', side_effect=catalogue), \
             patch('ui.pages.qml_lists.get_launcher_directory', return_value=private_root):
            self.setting_click(page, 'java-catalog-back')
            self.wait_for(lambda: not page.controller.busy, 'Java catalogue failure finishes')
            self.check('503' in page.controller.view['status'], 'Java catalogue failure is visible')
            self.setting_click(page, 'java-catalog-search')
            self.wait_for(lambda: not page.controller.busy, 'Java catalogue retry returns a package')
            self.check(len(page.controller.view['javaPackages']) == 1, 'real Java archive is listed')
            button = 'java-install-' + package.checksum
            for failure in ('http', 'hash'):
                if failure == 'http':
                    self.fixtures.failures.add(filename)
                else:
                    self.fixtures.failures.clear()
                    self.fixtures.payloads[filename] = bytes([payload[0] ^ 1]) + payload[1:]
                self.setting_click(page, button)
                self.wait_for(lambda: not page.controller.busy, 'Java download failure finishes', timeout=60000)
                status = page.controller.view['status']
                self.check('安装失败' in status and ('404' if failure == 'http' else '校验失败') in status,
                           'real HTTP/hash failure is reported without publishing Java')
                self.check(not (private_root / '.buggcraft/java' / package.checksum).exists(),
                           'failed runtime is never published')
                self.screenshot_ui('java-download-failure-' + failure)
            self.fixtures.payloads[filename] = payload
            started, release = Event(), Event()
            self.fixtures.pauses[filename] = (started, release)
            try:
                self.setting_click(page, button)
                self.wait_for(started.is_set, 'real Java download streams from local HTTP')
                self.check(page.controller.busy and not self.item(page, button).isEnabled(),
                           'download progress prevents duplicate Java installation')
                self.screenshot_ui('java-download-progress')
            finally:
                release.set()
            self.wait_for(lambda: not page.controller.busy, 'real Java is verified, extracted and executed', timeout=90000)
            self.check('已安装、校验并添加' in page.controller.view['status'], 'Java installation succeeds after retry')
            self.setting_click(page, 'java-catalog-back')
        installed = next(row[0] for row in self.manager.get_setting('java.installations')
                         if str(private_root) in row[0])
        self.check(Path(installed).is_file(), 'installed Java executable exists in the private directory')
        self.screenshot_ui('java-installed-list')
        page = self.settings_tab(1)
        options = next(g for g in page.controller.groups if g['key'] == 'java.path')['options']
        index = next(i for i, option in enumerate(options) if option['value'].endswith(' · ' + installed))
        self.setting_click(page, 'setting-option-java.path-' + str(index))
        self.java = installed
        self.launch_game('downloaded-java')
        self.close_game('downloaded-java')
        self.assert_no_qml_errors()
        self.finish_test()
