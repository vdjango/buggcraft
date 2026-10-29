"""Real Qt clicks and local HTTP metadata; production catalogue parsing stays active."""
import json
from threading import Event
from unittest.mock import patch

from test_client_ui_acceptance import ClientUiAcceptanceCase as _UiCase
import test_loader_source_ui as source_ui
from core import loaders

REAL_AVAILABLE_VERSIONS = loaders.available_versions
REAL_GET = loaders.requests.get


class CatalogueSourceRegressionUiTests(_UiCase):
    settings_tab = source_ui.LoaderSourceUiTests.settings_tab
    select_choice = source_ui.LoaderSourceUiTests.select_choice
    choose_box = source_ui.LoaderSourceUiTests.choose_box
    setting_click = source_ui.LoaderSourceUiTests.setting_click
    scroll_control = source_ui.LoaderSourceUiTests.scroll_control
    open_downloads = source_ui.LoaderSourceUiTests.open_downloads
    seed_games = source_ui.LoaderSourceUiTests.seed_games
    reveal_control = source_ui.LoaderSourceUiTests.reveal_control

    def setUp(self):
        super().setUp()
        self.routes = []
        self.fail_mirror = False
        self.fail_all = False
        self.invalid_json = False
        self._patch(patch.object(loaders, 'available_versions', REAL_AVAILABLE_VERSIONS))
        self._patch(patch.object(loaders.requests, 'get', self.transport))

    def transport(self, url, **kwargs):
        mirror = url.startswith(loaders.BMCLAPI + '/')
        failed = (self.fail_all or (mirror and self.fail_mirror)
                  or (mirror and '/quilt-meta/' in url))
        self.routes.append(dict(url=url, failed=failed))
        name = ('invalid.json' if self.invalid_json else 'loader.xml' if url.endswith('.xml') else 'loader.json')
        local = f'http://127.0.0.1:{self.fixtures.server.server_port}/' + ('missing/' if failed else '') + name
        return REAL_GET(local, **kwargs)

    def metadata(self, name):
        versions = {'Forge': ['58.0.2', '58.0.10'], 'NeoForge': ['21.8.2-beta', '21.8.10'],
                    'Fabric': ['0.9.0', '0.18.0'], 'Quilt': ['0.9.0', '0.29.3']}
        values = versions[name]
        records = ([dict(mcversion='1.21.8', version=v) for v in values]
                   if name in ('Forge', 'NeoForge') else [dict(loader=dict(version=v)) for v in values])
        coordinates = ['1.21.8-' + v for v in values] if name == 'Forge' else values
        self.fixtures.payloads['loader.json'] = json.dumps(records).encode()
        self.fixtures.payloads['loader.xml'] = ('<metadata><versioning><versions>'
            + ''.join('<version>' + v + '</version>' for v in coordinates)
            + '</versions></versioning></metadata>').encode()
        self.fixtures.payloads['invalid.json'] = b'{"code": "UPSTREAM_BUSY", "message": "internal detail"}'
        return values[-1]

    def test_settings_sources_feed_all_four_actual_loader_catalogues(self):
        for source_index in (0, 1, 2):
            general = self.settings_tab(0)
            self.select_choice(general, 'settings.general.mirrors', source_index)
            for name in ('Forge', 'NeoForge', 'Fabric', 'Quilt'):
                with self.subTest(source=source_index, loader=name):
                    expected = self.metadata(name)
                    # Reproduce Quilt's missing mirror route and a NeoForge outage.
                    self.fail_mirror = source_index == 0 and name in ('NeoForge', 'Quilt')
                    first = len(self.routes)
                    page = self.seed_games()
                    self.click_ui(page, 'install-1.21.8')
                    self.reveal_control(page, 'component-' + name)
                    self.click_ui(page, 'component-' + name)
                    self.wait_for(lambda: not page.controller.loader_busy, 'real metadata parser completes: ' + name)
                    calls = self.routes[first:]
                    self.check(calls[0]['url'].startswith(loaders.BMCLAPI) == (source_index != 1),
                               'settings controls the first list request')
                    self.check(len(calls) == (2 if self.fail_mirror else 1),
                               'automatic source falls back; explicit source stays selected')
                    if name == 'NeoForge' and source_index != 1:
                        self.check('/neoforge/list/1.21.8' in calls[0]['url'], 'NeoForge uses its dedicated API')
                    if name == 'Quilt' and source_index == 2:
                        self.check(not page.controller.component_versions
                                   and '切换下载源' in page.controller.loader_status,
                                   'explicit mirror reports missing Quilt metadata without inventing a version')
                        continue
                    self.check(page.controller.component_versions[0]['name'] == expected,
                               f'{name} source {source_index} renders latest compatible version')
                    self.click_ui(page, 'component-version-0')
                    self.check(page.controller.loader == name and page.controller.loader_version == expected,
                               'mouse selection returns the actual fetched version to installation form')
        (self.output / 'catalogue-routes.json').write_text(json.dumps(self.routes, indent=2), encoding='utf-8')
        self.screenshot_ui('loader-source-catalogues')
        self.assert_no_qml_errors()
        self.finish_test()

    def test_failed_metadata_page_has_short_message_and_retry_recovers(self):
        expected = self.metadata('NeoForge')
        self.manager.set_setting('settings.general.mirrors', '自动（镜像优先，失败切换官方）')
        self.fail_all = True
        page = self.seed_games()
        self.click_ui(page, 'install-1.21.8')
        self.reveal_control(page, 'component-NeoForge')
        self.click_ui(page, 'component-NeoForge')
        self.wait_for(lambda: not page.controller.loader_busy, 'both failed sources finish')
        label = self.item(page, 'component-list-status')
        self.check('重新加载' in label.property('text') and '切换下载源' in label.property('text'),
                   'visible error tells the player how to recover')
        for raw in ('http', 'ConnectionPool', '{', 'Client Error'):
            self.check(raw not in label.property('text'), 'technical error is absent: ' + raw)
        self.screenshot_ui('loader-failure-readable')
        self.fail_all = False
        self.invalid_json = True
        self.click_ui(page, 'component-reload')
        self.wait_for(lambda: not page.controller.loader_busy, 'service JSON error handled as failure')
        self.check('UPSTREAM_BUSY' not in label.property('text') and not page.controller.component_versions,
                   'service error JSON cannot become a version list or raw UI error')
        self.invalid_json = False
        self.click_ui(page, 'component-reload')
        self.wait_for(lambda: not page.controller.loader_busy, 'reload gets valid metadata')
        self.check(page.controller.component_versions[0]['name'] == expected, 'reload recovers actual versions')
        self.click_ui(page, 'component-version-0')
        self.screenshot_ui('loader-retry-recovered')
        self.assert_no_qml_errors()
        self.finish_test()

    def test_stored_raw_errors_are_readable_on_task_cards_and_available_in_logs(self):
        self.open_downloads()
        tasks = self.window.download_page.tasks_page
        errors = ["下载 asm-util-9.10.1.jar 失败：HTTPSConnectionPool(host='mirror.invalid'): Max retries exceeded (ReadTimeoutError)",
                  '{"code":"UNAVAILABLE","message":"upstream internal detail"}']
        ids = []
        for error in errors:
            task_id = tasks.track_room_preparation('Saved download', self.game_dir, {'version': '1.21.8'}, Event())
            tasks.finish_room_preparation(task_id, False, error)
            ids.append(task_id)
        self.window.download_page.on_progress_clicked()
        def contains(item, name):
            return item.objectName() == name or any(contains(child, name) for child in item.childItems())
        for task_id, raw in zip(ids, errors):
            self.wait_for(lambda: contains(tasks.quick.rootObject(), 'task-status-' + task_id),
                          'persisted task row renders')
            label = self.item(tasks, 'task-status-' + task_id)
            self.check('重试' in label.property('text'), 'task card offers recovery')
            self.check('ConnectionPool' not in label.property('text') and '{' not in label.property('text'),
                       'old task records also have readable presentation')
            self.check(tasks._find_task(task_id)['error'] == raw, 'original stored diagnostic is preserved')
            self.click_ui(tasks, 'task-log-' + task_id)
            self.click_ui(tasks, 'log-text-tab')
            log_text = self.item(tasks, 'task-log-text').property('text')
            self.check('ConnectionPool' not in log_text and '{' not in log_text,
                       'log view stays readable without exposing raw error bodies')
            self.check(tasks._find_task(task_id)['logs'], 'full diagnostic remains preserved in task history storage')
            self.click_ui(tasks, 'task-log-close')
        self.screenshot_ui('task-errors-readable')
        self.assert_no_qml_errors()
        self.finish_test()
