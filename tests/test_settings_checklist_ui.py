"""Settings checklist: actual QML input, saved preferences and real workers.

Remote update/catalogue responses use local fixtures. Actual Minecraft cases
live in test_game_launch_live.py and are explicitly enabled with a game root.
"""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
from threading import Event
from unittest.mock import patch
from urllib.parse import urlsplit

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication

from _qml_test_support import QTest, qt_mouse_drag
import test_home_ui as home_ui
import test_settings_ui as settings_ui
import test_download_ui as download_ui
from core import downloads
from config.settings import SettingsManager


REAL_DOWNLOAD_URLS = downloads.MinecraftDownloader.urls
REAL_HTTP_GET = downloads._DownloadSession.get


class SettingsChecklistUiTests(settings_ui.ClientUiSettingsTests):
    # Reused inherited tests are collected only in their original module.
    test_general_download_sources_multi_open_and_saved_controls = None
    test_global_and_instance_memory_java_and_launch_preferences = None
    test_custom_java_cancel_invalid_file_and_real_runtime_registration = None
    restart = home_ui.HomeChecklistUiTests.restart
    social = home_ui.HomeChecklistUiTests.social
    KINDS = download_ui.DownloadChecklistUiTests.KINDS
    open_downloads = download_ui.DownloadChecklistUiTests.open_downloads
    seed_games = download_ui.DownloadChecklistUiTests.seed_games
    open_kind = download_ui.DownloadChecklistUiTests.open_kind
    open_project = download_ui.DownloadChecklistUiTests.open_project
    content_dialog = download_ui.DownloadChecklistUiTests.content_dialog
    finished_task = download_ui.DownloadChecklistUiTests.finished_task

    def tearDown(self):
        tasks = self.window.download_page.tasks_page
        try:
            for worker in list(tasks._workers.values()):
                worker.cancel_event.set()
            self.wait_for(lambda: not tasks._workers, 'settings download workers finish')
            (self.output / 'http-requests.json').write_text(
                json.dumps(self.fixtures.requests, ensure_ascii=False, indent=2), encoding='utf-8')
            if hasattr(self, 'route_requests'):
                (self.output / 'download-routes.json').write_text(
                    json.dumps(self.route_requests, ensure_ascii=False, indent=2), encoding='utf-8')
        finally:
            super().tearDown()

    @contextmanager
    def subTest(self, *args, **kwargs):
        with super().subTest(*args, **kwargs):
            try:
                yield
            except BaseException:
                self._subtest_failed = True
                raise

    def finish_test(self):
        self.check(not getattr(self, '_subtest_failed', False), 'all settings subcases passed')
        super().finish_test()

    def use_production_download_routes(self):
        """Keep production URL selection; redirect only HTTP transport to loopback."""
        self.route_requests, self.route_failures = [], set()
        original_file = self.fixtures.file

        def file(name):
            data = original_file(name)
            if name == 'client.jar':
                data['url'] = 'https://piston-data.mojang.com/v1/objects/' + data['sha1'] + '/' + name
            elif name.startswith('ui-fixture-'):
                data['url'] = 'https://cdn.modrinth.com/data/ui-acceptance/' + name
            return data

        self._patch(patch.object(self.fixtures, 'file', file))
        self.fixtures.metadata['downloads']['client'] = file('client.jar')
        self.fixtures.payloads['1.21.8.json'] = json.dumps(self.fixtures.metadata).encode()
        self.fixtures.payloads['manifest.json'] = json.dumps({'versions': [dict(
            id='1.21.8', type='release', releaseTime='2026-01-01T00:00:00Z',
            **file('1.21.8.json'))]}).encode()
        trusted = {urlsplit(value).hostname for value in (
            downloads.MANIFEST_URL, downloads.MIRROR, downloads.CONTENT_MIRROR,
            self.fixtures.ORIGIN, 'https://piston-data.mojang.com', 'https://cdn.modrinth.com')}

        def get(session, url, **kwargs):
            parsed = urlsplit(url)
            if parsed.hostname not in trusted:
                raise AssertionError('Unexpected external download in isolated source test: ' + url)
            name = Path(parsed.path).name
            if name == 'version_manifest_v2.json':
                name = 'manifest.json'
            unavailable = (parsed.hostname, name) in self.route_failures
            self.route_requests.append(dict(url=url, host=parsed.hostname, file=name, unavailable=unavailable))
            local = 'http://127.0.0.1:%d/%s%s' % (
                self.fixtures.server.server_port, 'missing/' if unavailable else '', name)
            return REAL_HTTP_GET(session, local, **kwargs)

        self._patch(patch.object(downloads.MinecraftDownloader, 'urls', REAL_DOWNLOAD_URLS))
        self._patch(patch.object(downloads._DownloadSession, 'get', get))
        # Deterministic probe results exercise the real ranking policy. They
        # make no claim about current public MCIM/CDN throughput.
        downloads._CONTENT_ROUTE_CACHE.clear()
        self.addCleanup(downloads._CONTENT_ROUTE_CACHE.clear)
        self._patch(patch.object(downloads, '_CONTENT_HEALTH', downloads._MirrorHealth()))
        self._patch(patch.object(downloads, '_measure_content_route',
                                lambda url: 900_000 if urlsplit(url).hostname ==
                                urlsplit(downloads.CONTENT_MIRROR).hostname else 1_000_000))

    def test_settings_entry_all_tabs_sidebar_and_return(self):
        for index, kind in ((0, 'general'), (1, 'global'), (2, 'java'), (3, 'about')):
            page = self.settings_tab(index)
            self.check((getattr(page.controller, 'scope', None) or page.controller.kind) == kind,
                       'settings navigation opens the intended subpage: ' + kind)
            for collapsed in (True, False):
                self.click_ui(self.window.title_bar, 'toggle-launcher-sidebar')
                self.check(self.window.menu_collapsed == collapsed, 'sidebar changes on ' + kind)
            self.screenshot_ui('settings-tab-' + kind)
        general = self.settings_tab(0)
        self.setting_click(general, 'setting-toggle-launcher.allow_multiple')
        self.navigate('launcher-nav-home')
        general = self.settings_tab(0)
        self.check(self.item(general, 'setting-toggle-launcher.allow_multiple').property('checked'),
                   'returning from Home retains the changed setting in its visible control')
        self.assert_no_qml_errors()
        self.finish_test()

    def test_download_concurrency_control_saves_and_limits_values(self):
        general = self.settings_tab(0)
        control_name = 'setting-select-downloads.concurrency'
        options = self.item(general, control_name).property('model')
        self.check(len(options) == 7, 'download concurrency offers seven bounded worker counts')
        for index, expected in enumerate((1, 2, 4, 8, 16, 32, 64)):
            general = self.settings_tab(0)
            self.select_choice(general, 'downloads.concurrency', index)
            persisted = SettingsManager(self.directory / 'config')
            self.check(persisted.get_setting('downloads.concurrency') == expected,
                       'download worker count is saved from visible control: ' + str(expected))
            from core.downloads import MinecraftDownloader
            self.check(MinecraftDownloader(self.game_dir).workers == expected,
                       'new download tasks use the selected worker count: ' + str(expected))
            if expected in (1, 4):
                libraries, gates = [], []
                for number in range(8):
                    name = f'concurrency-{expected}-{number}.jar'
                    self.fixtures.payloads[name] = (f'UI concurrency {expected} file {number}\n' * 400).encode()
                    self.fixtures.pauses[name] = (Event(), Event())
                    gates.append((name, *self.fixtures.pauses[name]))
                    libraries.append(dict(name=f'ui:concurrency-{expected}-{number}:1.0',
                                          downloads=dict(artifact=dict(self.fixtures.file(name), path=name))))
                self.fixtures.metadata['libraries'] = libraries
                self.fixtures.payloads['1.21.8.json'] = json.dumps(self.fixtures.metadata).encode()
                self.fixtures.payloads['manifest.json'] = json.dumps(dict(versions=[dict(
                    id='1.21.8', type='release', **self.fixtures.file('1.21.8.json'))])).encode()
                try:
                    page = self.seed_games()
                    self.click_ui(page, 'install-1.21.8')
                    self.click_ui(page, 'install-selected-game')
                    self.wait_for(lambda: sum(started.is_set() for _, started, _ in gates) >= expected,
                                  'real HTTP downloads reach the UI selected limit: ' + str(expected))
                    self.pump(250)
                    self.check(sum(started.is_set() for _, started, _ in gates) == expected,
                               'waiting HTTP files never exceed the UI selected limit: ' + str(expected))
                    self.screenshot_ui('download-concurrency-active-' + str(expected))
                finally:
                    for _, _, release in gates:
                        release.set()
                self.finished_task()
                for name, _, _ in gates:
                    self.check((self.game_dir / 'libraries' / name).read_bytes() == self.fixtures.payloads[name],
                               'UI install publishes verified library: ' + name)
                general = self.settings_tab(0)
        general.controller.setValue('downloads.concurrency', 0)
        self.check(self.manager.get_setting('downloads.concurrency') == 1,
                   'invalid worker count is clamped at one')
        general.controller.setValue('downloads.concurrency', 999)
        self.check(self.manager.get_setting('downloads.concurrency') == 64,
                   'worker count is clamped at the safe maximum')
        general.controller.setValue('downloads.concurrency', 8)
        self.screenshot_ui('settings-download-concurrency')
        self.assert_no_qml_errors()
        self.finish_test()

    def test_game_download_source_preferences_reach_real_install_tasks(self):
        self.use_production_download_routes()
        sources = ('自动（官方优先，失败切换镜像）', '官方', 'BMCLAPI')
        mirror = urlsplit(downloads.MIRROR).hostname
        for index, fail_official in ((0, False), (1, False), (2, False), (0, True), (1, True)):
            source = sources[index]
            with self.subTest(source=source, official_unavailable=fail_official):
                general = self.settings_tab(0)
                self.select_choice(general, 'settings.general.mirrors', index)
                archive = self.game_dir / 'versions/1.21.8/1.21.8.jar'
                archive.unlink(missing_ok=True)
                self.route_failures = {('piston-data.mojang.com', 'client.jar')} if fail_official else set()
                before = len(self.route_requests)
                page = self.seed_games()
                self.click_ui(page, 'install-1.21.8')
                self.click_ui(page, 'install-selected-game')
                rejected = fail_official and index == 1
                task = self.finished_task(state='失败' if rejected else '已完成')
                self.check(task['source'] == source, 'selected game policy reaches production download worker')
                hosts = [row['host'] for row in self.route_requests[before:] if row['file'] == 'client.jar']
                self.check(hosts and hosts[0] == (mirror if index == 2 else 'piston-data.mojang.com'),
                           'actual first HTTP host follows the selected game source: ' + repr(hosts))
                if rejected:
                    self.check(set(hosts) == {'piston-data.mojang.com'}, 'official-only mode never contacts the mirror')
                    self.check(not archive.exists(), 'unavailable official source cannot publish a client archive')
                    continue
                if fail_official:
                    self.check(hosts[-1] == mirror, 'automatic mode falls back to the mirror after official HTTP failure')
                self.check(archive.read_bytes() == self.fixtures.payloads['client.jar'],
                           'game download produces the verified client bytes')
        self.screenshot_ui('settings-game-source-downloads')
        self.assert_no_qml_errors()
        self.finish_test()

    def test_content_source_preferences_reach_search_and_all_content_downloads(self):
        self.use_production_download_routes()
        from download_ui_fixtures import DownloadCatalogueFixtures
        catalogue = DownloadCatalogueFixtures(self.fixtures)
        self.addCleanup(catalogue.close)
        self._patch(patch('core.content.ContentCatalogue.search',
                          lambda _client, *args, **kwargs: catalogue.search(*args, **kwargs)))
        self._patch(patch('core.content.ContentCatalogue.versions',
                          lambda _client, *args, **kwargs: catalogue.versions(*args, **kwargs)))
        self._patch(patch('core.content.ContentCatalogue.project',
                          lambda _client, *args, **kwargs: catalogue.project(*args, **kwargs)))
        folders = dict(mod='mods', resourcepack='resourcepacks', shader='shaderpacks')
        for index, source in enumerate(('自动测速', 'MCIM', '官方')):
            for kind in self.KINDS[1:]:
                with self.subTest(source=source, kind=kind):
                    general = self.settings_tab(0)
                    self.select_choice(general, 'settings.general.content_mirror', index)
                    global_page = self.settings_tab(1)
                    self.setting_click(global_page, 'setting-option-minecraft.isolation-' + str(int(index != 0)))
                    _page, controller, dialog = self.content_dialog(kind)
                    self.check(all(client.mirror == source for client in controller.catalogue.clients.values()),
                               'content search clients receive the selected transport policy')
                    target = Path(dialog.controller.data['target'])
                    filename = self.fixtures.version(kind)['filename']
                    if kind in folders:
                        expected = Path(self.manager.get_minecraft_isolation_directory())
                        self.check(target == expected, 'content destination follows actual shared/independent isolation')
                        destination = target / folders[kind] / filename
                        destination.unlink(missing_ok=True)
                    else:
                        destination = target / 'modpacks' / filename
                        self.check(destination.resolve().is_relative_to(self.directory.resolve()),
                                   'only remove the isolated test archive to force each source transfer')
                        destination.unlink(missing_ok=True)
                    before = len(self.route_requests)
                    self.click_ui(dialog, 'content-download-confirm')
                    task = self.finished_task()
                    self.check(task['content_source'] == source,
                               'content download worker receives selected transport policy')
                    if kind in folders:
                        self.check(destination.read_bytes() == self.fixtures.payloads[filename],
                                   'download verifies and publishes the selected content file')
                    else:
                        self.check(destination.read_bytes() == self.fixtures.payloads[filename],
                                   'modpack archive is downloaded and verified for each selected source')
                        self.check((self.game_dir / 'versions' / task['version'] /
                                    'config/ui-acceptance.json').is_file(),
                                   'downloaded modpack runs the real importer')
                    requests = self.route_requests[before:]
                    self.check(any(row['file'] == filename for row in requests),
                               'source selection is followed by actual HTTP content transfer')
                    content_hosts = [row['host'] for row in requests if row['file'] == filename]
                    self.check(bool(content_hosts), 'the selected archive is downloaded through the production router')
                    self.check(content_hosts[0] == (urlsplit(downloads.CONTENT_MIRROR).hostname
                               if source == 'MCIM' else 'cdn.modrinth.com'),
                               'actual content HTTP host follows the source and measured ranking: ' + repr(content_hosts))
        self.screenshot_ui('settings-content-source-downloads')
        self.assert_no_qml_errors()
        self.finish_test()

    def test_opacity_drag_min_middle_max_navigation_and_restart(self):
        general = self.settings_tab(0)
        for ratio in (0.0, 0.5, 1.0):
            slider = self.scroll_control(general, 'setting-opacity-slider')
            start = slider.mapToScene(QPoint(int(slider.width() * slider.property('position')),
                                            int(slider.height() / 2))).toPoint()
            end = slider.mapToScene(QPoint(int(8 + (slider.width() - 16) * ratio),
                                          int(slider.height() / 2))).toPoint()
            self.record('mouseDrag', 'setting-opacity-slider', str(ratio))
            qt_mouse_drag(general.quick, start, end)
            self.pause_ui()
            value = self.manager.get_setting('launcher.opacity')
            self.check(abs(value - (35 + 65 * ratio)) <= 2, 'drag sets the requested opacity')
            self.check(abs(self.window.windowOpacity() - value / 100) < 0.02,
                       'real launcher window applies opacity immediately')
            self.navigate('launcher-nav-home')
            general = self.settings_tab(0)
            self.check(self.item(general, 'setting-opacity-slider').property('value') == value,
                       'opacity survives leaving and returning')
            self.restart()
            general = self.settings_tab(0)
            self.check(self.manager.get_setting('launcher.opacity') == value,
                       'new launcher reads the dragged opacity from disk')
        self.screenshot_ui('settings-opacity-after-restart')
        self.assert_no_qml_errors()
        self.finish_test()

    def test_cache_path_disabled_and_language_cancel_and_save(self):
        general = self.settings_tab(0)
        group = self.scroll_control(general, 'setting-group-cache')
        self.check(str(self.manager.config_path) in group.property('summary'), 'actual cache path is displayed')
        self.check('尚未接入' in self.item(general, 'setting-description-cache').property('text'),
                   'cache migration explains its unavailable implementation')
        before = self.manager.get_setting('settings.general.download.cache')
        for index in range(3):
            item = self.scroll_control(general, 'setting-option-cache-' + str(index))
            self.check(not item.isEnabled(), 'cache choice is disabled: ' + str(index))
            self.click_ui(general, 'setting-option-cache-' + str(index))
        self.check(self.manager.get_setting('settings.general.download.cache') == before,
                   'disabled cache controls cannot change the saved path')
        original = self.manager.get_setting('game.language')
        self.choose_box(general, 'setting-select-game-language', 3, commit=False)
        self.check(self.manager.get_setting('game.language') == original, 'Escape does not commit language')
        self.choose_box(general, 'setting-select-game-language', 3)
        self.check(self.persisted().get_setting('game.language') == 'en_us', 'language commits to disk')
        self.screenshot_ui('settings-cache-and-language')
        self.assert_no_qml_errors()
        self.finish_test()

    def test_all_launch_preferences_and_auto_memory_controls(self):
        page = self.settings_tab(1)
        self.check(not self.scroll_control(page, 'setting-memory-slider').isEnabled(),
                   'automatic memory disables manual editing')
        self.setting_click(page, 'setting-toggle-minecraft.auto_allocate_memory')
        self.check(self.item(page, 'setting-memory-slider').isEnabled(), 'manual memory enables its slider')
        for key in ('launcher.visibility', 'launcher.window_size'):
            options = next(g for g in page.controller.groups if g['key'] == key)['options']
            for index, option in enumerate(options):
                self.select_choice(page, key, index)
                self.check(self.persisted().get_version_setting(key) == option['value'],
                           'launch preference persists: ' + str(option['value']))
        for key in ('launcher.process_priority', 'launcher.debug'):
            options = next(g for g in page.controller.groups if g['key'] == key)['options']
            for index, option in enumerate(options):
                self.setting_click(page, 'setting-option-' + key + '-' + str(index))
                self.check(self.persisted().get_version_setting(key) == option['value'],
                           'radio preference persists: ' + str(option['value']))
        self.setting_click(page, 'setting-toggle-minecraft.auto_allocate_memory')
        self.check(not self.item(page, 'setting-memory-slider').isEnabled(), 'automatic memory can be restored')
        self.screenshot_ui('settings-launch-preferences')
        self.assert_no_qml_errors()
        self.finish_test()

    def test_java_add_cancel_invalid_duplicate_refresh_and_remove(self):
        java = shutil.which('java')
        if not java:
            self.skipTest('An installed Java is required for executable validation')
        java = os.path.realpath(java)
        page = self.settings_tab(2)
        original = list(self.manager.get_setting('java.installations'))
        for selected in ('', str(self.directory / 'missing-java.exe'), java, java):
            with patch('ui.pages.qml_lists.QFileDialog.getOpenFileName', return_value=(selected, '')):
                self.setting_click(page, 'java-action-添加')
            if selected == '':
                self.check(self.manager.get_setting('java.installations') == original, 'Add Java cancel preserves list')
            elif 'missing-java' in selected:
                self.check('无法添加' in page.controller.view['status'], 'invalid executable shows an error')
            else:
                self.check(sum(row[0] == java for row in self.manager.get_setting('java.installations')) == 1,
                           'real Java is probed, added once and deduplicated')
        self.screenshot_ui('settings-java-added')
        # Refresh runs the production asynchronous Java scanner.
        self.setting_click(page, 'java-action-刷新')
        self.wait_for(lambda: not page.controller.busy, 'asynchronous Java discovery finishes', timeout=60000)
        self.pause_ui()  # Let the new Repeater delegates finish their layout.
        self.check(any(row['id'] == java and row['version']
                       for row in page.controller.view['records']), 'scanner finds the installed Java version')
        self.screenshot_ui('settings-java-refreshed')
        with patch('ui.pages.qml_lists.open_folder', return_value=True) as opened:
            self.setting_click(page, 'java-folder-' + java)
        opened.assert_called_once_with(os.path.dirname(java))
        self.setting_click(page, 'java-remove-' + java)
        global_page = self.settings_tab(1)
        options = next(g for g in global_page.controller.groups if g['key'] == 'java.path')['options']
        self.check(not any(option['value'].endswith(' · ' + java) for option in options),
                   'removed Java disappears from global launch choices')
        instance_page = self.instance_settings('1.21.8')
        options = next(g for g in instance_page.controller.groups if g['key'] == 'java.path')['options']
        self.check(not any(option['value'].endswith(' · ' + java) for option in options),
                   'removed Java disappears from instance launch choices')
        self.assert_no_qml_errors()
        self.finish_test()

    def test_java_catalog_major_source_failure_and_retry(self):
        requests = []

        def unavailable(major, source):
            requests.append((major, source))
            if len(requests) == 1:
                raise RuntimeError('UI Java catalogue connection failed')
            return []

        page = self.settings_tab(2)
        with patch('ui.pages.qml_lists.catalogue', side_effect=unavailable):
            self.setting_click(page, 'java-catalog-back')
            self.wait_for(lambda: not page.controller.busy, 'failed Java catalogue request finishes')
            self.check('connection failed' in page.controller.view['status'], 'Java list failure is visible')
            self.setting_click(page, 'java-catalog-search')
            self.wait_for(lambda: not page.controller.busy, 'Java catalogue retry finishes')
            self.check('没有找到' in page.controller.view['status'], 'empty catalogue has an explicit message')
            for index, major in enumerate((8, 11, 16, 17, 21, 25)):
                self.choose_box(page, 'java-catalog-major', index)
                self.check(page.controller.view['javaMajor'] == major, 'Java major selection works: ' + str(major))
                self.wait_for(lambda: self.item(page, 'java-catalog-search').isEnabled(),
                              'catalogue search is ready after selecting Java major')
                before = len(requests)
                self.setting_click(page, 'java-catalog-search')
                self.wait_for(lambda: len(requests) > before and not page.controller.busy,
                              'selected Java major reaches a completed catalogue query')
                self.check(requests[-1] == (major, page.controller.view['javaSource']),
                           'catalogue query uses the selected Java major: ' + repr(requests[-1]))
            for index, source in enumerate(page.controller.view['javaSources']):
                self.choose_box(page, 'java-catalog-source', index)
                self.check(page.controller.view['javaSource'] == source,
                           'source selection is committed before requesting: ' + source)
                self.wait_for(lambda: self.item(page, 'java-catalog-search').isEnabled(),
                              'catalogue request button becomes enabled')
                before = len(requests)
                self.setting_click(page, 'java-catalog-search')
                self.wait_for(lambda: len(requests) > before,
                              'click starts a new catalogue request')
                self.wait_for(lambda: not page.controller.busy, 'catalogue request uses selected source')
                self.check(requests[-1] == (25, source),
                           'major and source reach the catalogue boundary: ' + repr(requests[-1]))
                self.check(self.persisted().get_setting('java.download_source') == source, 'source persists')
        self.screenshot_ui('settings-java-catalogue')
        self.setting_click(page, 'java-catalog-back')
        self.check(not page.controller.view['javaCatalogOpen'], 'Java catalogue returns to installed list')
        self.assert_no_qml_errors()
        self.finish_test()

    def test_about_information_sections_links_and_return(self):
        page = self.settings_tab(3)
        self.check(page.controller.view['launcherVersion'] in self.item(page, 'about-launcher-version').property('text'),
                   'About displays the running launcher version')
        self.check(self.item(page, 'about-description-当前游戏实例').property('text') == '1.21.8',
                   'About displays the selected instance')
        for section in ('鸣谢', '依赖', '法律声明'):
            self.scroll_control(page, 'about-section-' + section + '-header')
            if not self.item(page, 'about-section-' + section).property('expanded'):
                self.setting_click(page, 'about-section-' + section + '-header')
            self.check(self.item(page, 'about-section-' + section).property('expanded'), 'About section expands: ' + section)
        with patch('ui.pages.qml_lists.QDesktopServices.openUrl', return_value=True) as opened:
            for record in page.controller.view['records']:
                if not record['actions']:
                    continue
                self.setting_click(page, 'about-link-' + record['title'])
                self.check(opened.call_args.args[0].toString() == record['id'],
                           'About link dispatches its intended browser URL: ' + record['title'])
            for name, url in (
                    ('官方网站', 'https://bugg.icu/'),
                    ('使用帮助', 'https://github.com/vdjango/buggcraft#通过节点联机'),
                    ('问题反馈', 'https://github.com/vdjango/buggcraft/issues')):
                self.setting_click(page, 'about-quick-link-' + name)
                self.check(opened.call_args.args[0].toString() == url,
                           'quick link dispatches the intended destination: ' + name)
        self.screenshot_ui('settings-about-expanded')
        self.navigate('launcher-nav-home')
        self.check(self.window.current_tab == 0, 'launcher remains usable after About links')
        self.assert_no_qml_errors()
        self.finish_test()

    def instance_settings(self, version):
        self.click_ui(self.window.title_bar, 'instances-button')
        instances = self.window.version_page.versions_page
        self.click_ui(instances, 'instance-row-' + version)
        self.click_ui(instances, 'instance-settings-' + version)
        return self.window.version_page.settings_page

    def test_instances_inherit_global_changes_and_restore_overrides_after_restart(self):
        page = self.instance_settings('1.21.8')
        self.check(not self.item(page, 'setting-option-minecraft.isolation-1').isEnabled(),
                   'instance without independent settings inherits global values')
        self.setting_click(page, 'setting-toggle-instance.enable')
        self.setting_click(page, 'setting-option-launcher.process_priority-0')
        page = self.settings_tab(1)
        self.setting_click(page, 'setting-option-launcher.process_priority-2')
        page = self.instance_settings('1.20.1')
        self.check(self.manager.get_version_setting('launcher.process_priority') == '系统流畅优先',
                   'other instance inherits the changed global priority')
        page = self.instance_settings('1.21.8')
        self.check(self.manager.get_version_setting('launcher.process_priority') == '游戏性能优先',
                   'independent instance keeps its saved priority after switching versions')
        self.setting_click(page, 'setting-toggle-instance.enable')
        self.check(self.manager.get_version_setting('launcher.process_priority') == '系统流畅优先',
                   'disabling independent settings applies global priority')
        self.setting_click(page, 'setting-toggle-instance.enable')
        self.restart()
        page = self.instance_settings('1.21.8')
        self.check(self.item(page, 'setting-toggle-instance.enable').property('checked')
                   and self.manager.get_version_setting('launcher.process_priority') == '游戏性能优先',
                   'restart preserves enabled override and its original value')
        self.screenshot_ui('settings-inheritance-after-restart')
        self.assert_no_qml_errors()
        self.finish_test()
