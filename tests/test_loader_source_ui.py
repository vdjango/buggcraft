"""Click settings and install real profiles through production source routing.

Only the HTTP transport is redirected to loopback. Profiles and library bytes
are deterministic fixtures, so these checks do not claim a runnable loader.
The separate opt-in game suite installs public loader artifacts and launches.
"""
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit
from unittest.mock import patch

from test_client_ui_acceptance import ClientUiAcceptanceCase as _UiCase
import test_download_ui as download_ui
import test_settings_ui as settings_ui
from core import downloads, loaders

REAL_URLS = downloads.MinecraftDownloader.urls
REAL_GET = downloads._DownloadSession.get


class LoaderSourceUiTests(_UiCase):
    settings_tab = settings_ui.ClientUiSettingsTests.settings_tab
    select_choice = settings_ui.ClientUiSettingsTests.select_choice
    choose_box = settings_ui.ClientUiSettingsTests.choose_box
    setting_click = settings_ui.ClientUiSettingsTests.setting_click
    scroll_control = settings_ui.ClientUiSettingsTests.scroll_control
    open_downloads = download_ui.DownloadChecklistUiTests.open_downloads
    seed_games = download_ui.DownloadChecklistUiTests.seed_games
    reveal_control = download_ui.DownloadChecklistUiTests.reveal_control
    finished_task = download_ui.DownloadChecklistUiTests.finished_task

    def tearDown(self):
        tasks = self.window.download_page.tasks_page
        for worker in list(tasks._workers.values()):
            worker.cancel_event.set()
        self.wait_for(lambda: not tasks._workers, 'loader workers finish before closing the window')
        (self.output / 'loader-http-routes.json').write_text(
            json.dumps(getattr(self, 'routes', []), indent=2), encoding='utf-8')
        super().tearDown()

    def test_loader_source_choices_drive_profile_and_library_http_with_fallback(self):
        self.routes, self.unavailable = [], set()
        current = {}
        mirror = urlsplit(loaders.BMCLAPI).hostname
        self._patch(patch.object(downloads.MinecraftDownloader, 'urls', REAL_URLS))

        def transport(url, **kwargs):
            parsed = urlsplit(url)
            is_profile = parsed.path.endswith('/profile/json')
            is_library = parsed.path.endswith('/source-fixture-1.jar')
            name = ('loader-profile.json' if is_profile else
                    'source-fixture-1.jar' if is_library else Path(parsed.path).name)
            if name == 'version_manifest_v2.json':
                name = 'manifest.json'
            failed = parsed.hostname in self.unavailable and (is_profile or is_library)
            self.routes.append(dict(url=url, host=parsed.hostname, file=name, failed=failed))
            local = 'http://127.0.0.1:%d/%s%s' % (
                self.fixtures.server.server_port, 'missing/' if failed else '', name)
            return REAL_GET(downloads._DownloadSession(), local, **kwargs)

        self._patch(patch.object(loaders, '_response', lambda url: self.checked_response(transport(url))))
        self._patch(patch.object(downloads._DownloadSession, 'get',
                                lambda _session, url, **kw: transport(url, **kw)))
        self.fixtures.payloads['source-fixture-1.jar'] = b'loader-specific transport evidence'
        digest = hashlib.sha1(self.fixtures.payloads['source-fixture-1.jar']).hexdigest()
        policies = ('自动（镜像优先，失败切换官方）', '官方', 'BMCLAPI')
        for loader, host in (('Fabric', 'meta.fabricmc.net'), ('Quilt', 'meta.quiltmc.org')):
            for index, fail in ((0, False), (1, False), (2, False), (0, True), (1, True)):
                general = self.settings_tab(0)
                self.select_choice(general, 'settings.general.mirrors', index)
                number = str(len(self.routes) + 1)
                version = '0.0.' + number
                identity = loader.lower() + '-loader-' + version + '-1.21.8'
                lib_host = 'maven.fabricmc.net' if loader == 'Fabric' else 'maven.quiltmc.org'
                profile = dict(id=identity, inheritsFrom='1.21.8',
                    mainClass='fixture.LoaderMain', libraries=[dict(
                        name='test.acceptance:source-fixture:1',
                        downloads=dict(artifact=dict(sha1=digest,
                            size=len(self.fixtures.payloads['source-fixture-1.jar']),
                            url='https://' + lib_host + '/test/acceptance/source-fixture/1/source-fixture-1.jar')))])
                self.fixtures.payloads['loader-profile.json'] = json.dumps(profile).encode()
                library = self.game_dir / 'libraries/test/acceptance/source-fixture/1/source-fixture-1.jar'
                library.unlink(missing_ok=True)
                self.unavailable = ({mirror} if index == 0 else {host, lib_host}) if fail else set()
                before = len(self.routes)
                page = self.seed_games()
                self.click_ui(page, 'install-1.21.8')
                with patch.object(loaders, 'available_versions', return_value=[version]):
                    self.reveal_control(page, 'component-' + loader)
                    self.click_ui(page, 'component-' + loader)
                    self.wait_for(lambda: not page.controller.loader_busy, 'loader catalogue selection arrives')
                    self.click_ui(page, 'component-version-0')
                self.click_ui(page, 'install-selected-game')
                rejected = index == 1 and fail
                task = self.finished_task(state='失败' if rejected else '已完成')
                self.check(task['source'] == policies[index], 'selected policy reaches actual loader worker')
                calls = self.routes[before:]
                profiles = [row['host'] for row in calls if row['file'] == 'loader-profile.json']
                self.check(profiles and profiles[0] == (mirror if index in (0, 2) else host),
                           'loader profile first host follows settings: ' + repr(profiles))
                metadata = self.game_dir / 'versions' / identity / (identity + '.json')
                if rejected:
                    self.check(set(profiles) == {host} and not metadata.exists() and not library.exists(),
                               'official-only failure cannot fall back or publish a successful instance')
                    continue
                if fail:
                    self.check(host in profiles, 'automatic policy falls back to the publisher after mirror failure')
                libraries = [row['host'] for row in calls if row['file'] == 'source-fixture-1.jar']
                self.check(libraries and libraries[0] == (mirror if index in (0, 2) else lib_host),
                           'loader dependency first host follows settings: ' + repr(libraries))
                if fail:
                    self.check(lib_host in libraries, 'automatic dependency download also falls back to publisher')
                self.check(library.read_bytes() == self.fixtures.payloads['source-fixture-1.jar']
                           and json.loads(metadata.read_text(encoding='utf-8')) == profile,
                           'successful task publishes verified loader-specific bytes and exact profile')
        self.screenshot_ui('loader-source-policy-results')
        self.assert_no_qml_errors()
        self.finish_test()

    @staticmethod
    def checked_response(response):
        response.raise_for_status()
        return response
