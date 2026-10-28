import threading
import hashlib
import io
import json
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import requests
from unittest.mock import ANY, patch
from _qml_test_support import LauncherQmlCase
from core.content import ContentCatalogue

CATALOGUE_SEARCH = ContentCatalogue.search


class ContentBrowserTests(LauncherQmlCase):
    def setUp(self):
        super().setUp()
        from core.downloads import _MirrorHealth
        # These cases verify the UI and real downloads from a loopback server.
        # Mirror ranking has separate tests; never probe public hosts here.
        for patcher in (
            patch('core.downloads._CONTENT_HEALTH', _MirrorHealth()),
            patch('core.downloads._rank_content_candidates', side_effect=lambda urls, source: urls),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def confirm_download(self, controller, instance=None):
        dialog = controller._download_dialog
        self.assertIsNotNone(dialog)
        if instance is not None:
            dialog.controller.actionRequested.emit('目标:' + instance)
        dialog.controller.actionRequested.emit('确认下载')
        self.pump(30)

    def test_detail_prefers_compatible_file_but_keeps_all_files_and_project_advice(self):
        controller = self.window.download_page.content_page.controller
        controller.kind = 'resourcepack'
        controller.selected_project = dict(project_id='fresh-animations', source='Modrinth', game_versions=['1.21.8'])
        files = [dict(id='latest-' + str(i), name='26.1+', game_versions=['26.1']) for i in range(35)]
        files.append(dict(id='matching', name='Current game', game_versions=['1.21.8', '1.20.1']))
        controller._query_finished(controller.request_id, 'versions', files, '')
        self.assertEqual(controller.viewState['selected_file']['id'], 'matching')
        self.assertEqual(controller.viewState['selected_file']['compatibility_state'], 'compatible')
        self.assertIn('1.21.8', controller.viewState['project_compatibility'])
        controller.selectVersion(1)
        self.assertIn('游戏版本不支持', controller.viewState['selected_file']['compatibility'])
        self.assertIn('此项目有支持', controller.viewState['project_compatibility'])
        controller.loadMoreVersions()
        self.assertEqual(len(controller.versions), len(files))

    def test_detail_shows_loading_while_both_network_requests_are_pending(self):
        downloads = self.window.download_page
        controller = downloads.content_page.controller
        downloads.open_content('resourcepack', 'browse')
        self.wait_until(lambda: not controller.busy)
        release = threading.Event()
        def pending(*args, **kwargs):
            release.wait(3)
            return []
        try:
            with patch.object(controller.catalogue, 'versions', side_effect=pending), \
                    patch.object(controller.catalogue, 'project', side_effect=pending):
                self.click(downloads.games_page, 'content-project-0')
                self.assertTrue(controller.busy)
                self.assertTrue(controller.details_busy)
                self.pump(100)
                self.assertTrue(self.item(downloads.games_page, 'content-project-loading').isVisible())
                self.assertIn('正在加载', self.item(downloads.games_page, 'content-compatibility').property('text'))
                self.assertFalse(self.item(downloads.games_page, 'download-content-version').isEnabled())
                release.set()
                self.wait_until(lambda: not controller.busy and not controller.details_busy)
        finally:
            release.set()
        self.assert_no_qml_errors()

    def test_download_button_writes_verified_files_to_selected_instance_for_all_kinds(self):
        payload = b'local content integration fixture'
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        get = requests.get
        def local_get(url, **kwargs):
            self.assertTrue(url.startswith('https://mod.mcimirror.top/test-'))
            return get(f'http://127.0.0.1:{server.server_port}/fixture', **kwargs)
        downloads = self.window.download_page
        controller = downloads.content_page.controller
        try:
            with patch('core.downloads._DownloadSession.get', side_effect=local_get):
                for isolated in (False, True):
                    self.manager.set_setting('minecraft.isolation', isolated)
                    for kind, folder, extension in (('mod', 'mods', 'jar'), ('resourcepack', 'resourcepacks', 'zip'), ('shader', 'shaderpacks', 'zip')):
                        downloads.open_content(kind, 'browse')
                        self.wait_until(lambda: not controller.busy)
                        self.click(downloads.games_page, 'content-project-0')
                        self.wait_until(lambda: not controller.busy)
                        filename = f'test-{kind}-{isolated}.{extension}'
                        version = dict(name=filename, files=[dict(url='https://cdn.modrinth.com/' + filename,
                            filename=filename, size=len(payload), hashes={'sha1': hashlib.sha1(payload).hexdigest()})])
                        controller._query_finished(controller.request_id, 'versions', [version], '')
                        self.pump()
                        self.click(downloads.games_page, 'content-detail-tab-1')
                        self.click(downloads.games_page, 'download-content-version')
                        self.assertIsNotNone(controller._download_dialog)
                        self.click(controller._download_dialog.host, 'content-download-confirm')
                        self.wait_until(lambda: not downloads.tasks_page._workers)
                        self.assertEqual(downloads.tasks_page._tasks[0]['state'], '已完成')
                        target = self.game_dir / 'versions/1.21.8' if isolated else self.game_dir
                        self.assertEqual((target / folder / filename).read_bytes(), payload)
                        other = self.game_dir if isolated else self.game_dir / 'versions/1.21.8'
                        self.assertFalse((other / folder / filename).exists())
                        self.assertIs(downloads.stack.currentWidget(), downloads.tasks_page)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(1)
        self.assert_no_qml_errors()

    def test_all_content_categories_share_game_catalogue_and_show_clickable_rows(self):
        downloads = self.window.download_page
        page = downloads.games_page
        page.controller.versions = [dict(id='1.21.8', type='release', releaseTime='2026-01-01')]
        downloads.on_download_clicked()
        self.pump()
        game_row = self.item(page, 'install-1.21.8')
        geometry = (game_row.width(), game_row.height(), game_row.property('radius'))
        for index, kind in enumerate(('mod', 'resourcepack', 'shader', 'modpack'), 1):
            self.click(page, 'content-kind-' + str(index))
            controller = downloads.content_page.controller
            self.wait_until(lambda: not controller.busy)
            row = self.item(page, 'content-project-0')
            self.assertTrue(row.isVisible(), kind)
            self.assertEqual((row.width(), row.height(), row.property('radius')), geometry)
            self.assertIn('示例项目', row.property('title'))
            self.click(page, 'content-project-0')
            self.wait_until(lambda: not controller.busy)
            self.assertEqual(controller.view, 'detail')
            self.assertTrue(self.item(page, 'content-details').isVisible())
            self.click(page, 'content-detail-tab-1')
            self.assertTrue(self.item(page, 'content-version-0').isVisible())
            self.snapshot('catalogue-' + kind)
            self.click(page, 'content-back')
        self.assert_no_qml_errors()

    def test_partial_results_are_visible_before_slow_provider_completes(self):
        downloads = self.window.download_page
        controller = downloads.content_page.controller
        catalogue = ContentCatalogue()
        release = threading.Event()
        def slow(*args):
            if not release.wait(3):
                raise TimeoutError('slow provider test gate')
            return [dict(project_id='slow', title='Slow result')]
        try:
            with patch.object(controller, 'catalogue', catalogue), \
                    patch.object(catalogue, 'search', CATALOGUE_SEARCH.__get__(catalogue)), \
                    patch.object(catalogue.clients['Modrinth'], 'search', return_value=[dict(project_id='fast', title='Fast result')]), \
                    patch.object(catalogue.clients['CurseForge'], 'search', side_effect=slow):
                downloads.open_content('mod', 'browse')
                self.wait_until(lambda: len(controller.results) == 1)
                self.assertTrue(controller.busy)
                self.assertTrue(self.item(downloads.games_page, 'content-project-0').isVisible())
                self.assertIn('Fast result', self.item(downloads.games_page, 'content-project-0').property('title'))
                release.set()
                self.wait_until(lambda: not controller.busy)
                self.assertEqual(len(controller.results), 2)
        finally:
            release.set()
            controller.pool.waitForDone(4000)

    def test_header_selection_keeps_files_and_updates_advice_and_install_directory(self):
        downloads = self.window.download_page
        controller = downloads.content_page.controller
        downloads.open_content('mod', 'browse')
        self.wait_until(lambda: not controller.busy)
        controller.chooseProject(0)
        self.wait_until(lambda: not controller.busy)
        self.window.title_bar.controller.selectVersion('1.20.1')
        self.wait_until(lambda: not controller.busy)
        self.assertIsNotNone(controller.selected_project)
        self.assertEqual(controller.selected_version, 0)
        self.assertEqual(controller.viewState['target'], str(self.game_dir / 'versions/1.20.1'))
        with patch.object(downloads.tasks_page, 'start_install', return_value=True) as enqueue:
            controller.downloadSelected()
            self.confirm_download(controller)
        self.assertEqual(enqueue.call_args.kwargs['content']['target'], str(self.game_dir / 'versions/1.20.1'))

    def test_mod_resource_and_shader_targets_follow_shared_or_isolated_setting(self):
        downloads = self.window.download_page
        controller = downloads.content_page.controller
        for isolated in (False, True):
            self.manager.set_setting('minecraft.isolation', isolated)
            for kind in ('mod', 'resourcepack', 'shader'):
                downloads.open_content(kind, 'browse')
                self.wait_until(lambda: not controller.busy)
                controller.chooseProject(0)
                self.wait_until(lambda: not controller.busy)
                with patch.object(downloads.tasks_page, 'start_install', return_value=True) as enqueue:
                    controller.downloadSelected()
                    self.confirm_download(controller)
                expected = self.game_dir / 'versions/1.21.8' if isolated else self.game_dir
                self.assertEqual(Path(enqueue.call_args.kwargs['content']['target']), expected)

    def test_network_error_is_displayed_and_retry_recovers(self):
        controller = self.window.download_page.content_page.controller
        with patch.object(controller.catalogue, 'search', side_effect=ValueError('network fixture')):
            self.window.download_page.open_content('resourcepack', 'browse')
            self.wait_until(lambda: not controller.busy)
        self.assertIn('获取失败', controller.status)
        self.assertIn('network fixture', controller.status)
        controller.search('retry')
        self.wait_until(lambda: not controller.busy)
        self.assertEqual(len(controller.results), 1)

    def test_all_kinds_are_not_filtered_by_the_current_instances_game_or_loader(self):
        controller = self.window.download_page.content_page.controller
        for kind in ('mod', 'resourcepack', 'shader', 'modpack'):
            controller.setKind(kind)
            controller.setView('browse')
            self.wait_until(lambda: not controller.busy)
            with patch.object(controller.catalogue, 'search', return_value=[]) as search:
                controller.search('Fixture')
                self.wait_until(lambda: not controller.busy)
            search.assert_called_once_with('Fixture', kind, '', '', '自动', progress=ANY,
                                           offset=0, limit=20, page_info=True)
            controller.results = [dict(project_id='fixture', source='Modrinth')]
            with patch.object(controller.catalogue, 'versions', return_value=[]) as versions:
                controller.chooseProject(0)
                self.wait_until(lambda: not controller.busy)
            self.assertEqual(versions.call_args.args[1:], ('', '', kind))

    def test_kind_change_invalidates_inflight_response(self):
        controller = self.window.download_page.content_page.controller
        started, release = threading.Event(), threading.Event()
        def slow(*args, **kwargs):
            started.set()
            if not release.wait(2):
                raise TimeoutError('test search gate')
            return [dict(project_id='stale', title='Old result', source='Modrinth')]
        try:
            with patch.object(controller.catalogue, 'search', side_effect=slow):
                controller.search('')
                self.assertTrue(started.wait(1))
                controller.setKind('resourcepack')
                self.assertFalse(controller.busy)
                release.set()
                self.wait_until(lambda: controller.pool.activeThreadCount() == 0)
                self.pump()
                self.assertEqual(controller.results, [])
                self.assertIsNone(controller.selected_project)
                self.assertEqual(controller.selected_version, -1)
        finally:
            release.set()

    def test_source_change_clears_selection_and_preserves_project_provider(self):
        controller = self.window.download_page.content_page.controller
        controller._query_finished(controller.request_id, 'search', [dict(project_id='10', title='Sample', source='CurseForge')], '')
        controller.chooseProject(0)
        self.wait_until(lambda: not controller.busy)
        self.assertEqual(controller.selected_project['source'], 'CurseForge')
        self.assertEqual(controller.selected_version, 0)
        with patch.object(controller.pool, 'start'):
            controller.setSource('Modrinth')
        self.assertEqual(controller.results, [])
        self.assertEqual(controller.selected_version, -1)
        self.assertIsNone(controller.selected_project)

    def test_resource_download_targets_current_instance(self):
        downloads = self.window.download_page
        controller = downloads.content_page.controller
        controller.kind = 'resourcepack'
        controller.versions = [dict(name='Fixture', compatibility_state='compatible', files=[])]
        controller.selected_version = 0
        with patch.object(downloads.tasks_page, 'start_install', return_value=True) as enqueue:
            controller.downloadSelected()
            self.assertIsNotNone(controller._download_dialog)
            self.assertEqual(controller._download_dialog.controller.data['instance'], '1.21.8')
            self.assertFalse(controller._download_dialog.controller.data['targetExpanded'])
            self.click(controller._download_dialog.host, 'content-download-target-toggle')
            self.assertTrue(self.item(controller._download_dialog.host, 'content-download-target').isVisible())
            self.snapshot('content-download-confirm', controller._download_dialog)
            controller._download_dialog.controller.actionRequested.emit('目标:1.20.1')
            self.assertEqual(controller._download_dialog.controller.data['instance'], '1.20.1')
            self.confirm_download(controller)
        job = enqueue.call_args.kwargs['content']
        self.assertEqual(job['kind'], 'resourcepack')
        self.assertEqual(job['target'], str(self.game_dir / 'versions/1.20.1'))
        self.assertIs(downloads.stack.currentWidget(), downloads.tasks_page)

    def test_mod_loader_mismatch_is_distinct_and_blocks_install(self):
        controller = self.window.download_page.content_page.controller
        controller.kind = 'mod'
        row = controller._version_row(dict(name='Fabric build', game_versions=['1.21.8'], loaders=['fabric']))
        self.assertEqual(row['compatibility_state'], 'incompatible')
        self.assertIn('Minecraft 1.21.8 版本号受支持', row['compatibility'])
        self.assertIn('加载器不匹配', row['compatibility'])
        controller.versions = [row]
        controller.selected_version = 0
        with patch.object(self.window.download_page.tasks_page, 'start_install') as enqueue:
            controller.downloadSelected()
            self.assertFalse(self.item(controller._download_dialog.host, 'content-download-confirm').isEnabled())
            controller._download_dialog.controller.actionRequested.emit('确认下载')
            controller._download_dialog.reject()
        enqueue.assert_not_called()
        self.assertIsNone(controller._download_dialog)

    def test_game_version_mismatch_names_supported_versions_and_blocks_install(self):
        controller = self.window.download_page.content_page.controller
        controller.kind = 'resourcepack'
        row = controller._version_row(dict(name='New game build', game_versions=['1.20.1'], loaders=[]))
        self.assertEqual(row['compatibility_state'], 'incompatible')
        self.assertIn('游戏版本不支持', row['compatibility'])
        self.assertIn('当前实例是 Minecraft 1.21.8', row['compatibility'])
        controller.versions = [row]
        controller.selected_version = 0
        self.assertFalse(controller.viewState['installable'])

    def test_compatibility_does_not_confuse_missing_game_metadata_or_loaders(self):
        controller = self.window.download_page.content_page.controller
        cases = [
            (dict(game_versions=['1.20.1'], loaders=['fabric']), 'incompatible', ['游戏版本不支持', '加载器不匹配']),
            (dict(game_versions=[], loaders=['fabric']), 'incompatible', ['未声明支持的 Minecraft', '加载器不匹配']),
            (dict(game_versions=['1.21.8'], loaders=[]), 'unknown', ['未声明支持的模组加载器']),
        ]
        for version, state, expected in cases:
            row = controller._version_row(version)
            self.assertEqual(row['compatibility_state'], state)
            for text in expected:
                self.assertIn(text, row['compatibility'])
            self.assertNotIn('版本号受支持', row['compatibility'])

    def test_project_requires_game_and_loader_supported_by_the_same_file(self):
        controller = self.window.download_page.content_page.controller
        controller.selected_project = dict(game_versions=['1.21.8'])
        controller._all_versions = [dict(game_versions=['1.21.8'], loaders=['fabric']),
                                    dict(game_versions=['1.20.1'], loaders=['forge'])]
        self.assertIn('同一个文件同时支持', controller._project_compatibility())
        self.assertNotIn('已找到同时支持', controller._project_compatibility())

    def test_dialog_switch_target_revalidates_compatibility_and_respects_target_isolation(self):
        downloads = self.window.download_page
        controller = downloads.content_page.controller
        name = 'Fabric target'
        folder = self.game_dir / 'versions' / name
        folder.mkdir()
        metadata = dict(id=name, inheritsFrom='1.20.1', libraries=[{'name': 'net.fabricmc:fabric-loader:0.16.0'}])
        (folder / (name + '.json')).write_text(json.dumps(metadata), encoding='utf-8')
        self.manager.set_setting('minecraft.setting.' + name + '.enable', True)
        self.manager.set_setting('minecraft.setting.' + name + '.minecraft.isolation', False)
        controller.versions = [controller._version_row(dict(name='Fabric file', game_versions=['1.20.1'], loaders=['fabric']))]
        controller.selected_version = 0
        with patch.object(downloads.tasks_page, 'start_install', return_value=True) as enqueue:
            controller.downloadSelected()
            dialog = controller._download_dialog
            self.assertFalse(dialog.controller.data['targetValid'])
            dialog.controller.actionRequested.emit('确认下载')
            enqueue.assert_not_called()
            dialog.controller.actionRequested.emit('目标:' + name)
            self.assertTrue(dialog.controller.data['targetValid'])
            self.assertEqual(dialog.controller.data['compatibilityState'], 'compatible')
            self.assertEqual(dialog.controller.data['target'], str(self.game_dir))
            self.confirm_download(controller)
        self.assertEqual(enqueue.call_args.kwargs['content']['target'], str(self.game_dir))
        self.assertEqual(self.manager.get_setting('minecraft.version.enable'), '1.21.8')

    def test_dialog_snapshots_destination_and_rechecks_deleted_instance_before_confirm(self):
        controller = self.window.download_page.content_page.controller
        controller.kind = 'resourcepack'
        controller.versions = [dict(name='Fixture', game_versions=['1.21.8'])]
        controller.selected_version = 0
        with patch.object(self.window.download_page.tasks_page, 'start_install', return_value=True) as enqueue:
            controller.downloadSelected()
            dialog = controller._download_dialog
            controller.kind = 'shader'
            self.manager.set_setting('minecraft.directory.enable', str(self.directory / 'other'))
            self.confirm_download(controller)
            self.assertEqual(enqueue.call_args.kwargs['content']['kind'], 'resourcepack')
            self.assertEqual(enqueue.call_args.args[1], str(self.game_dir))
            controller._content_download_dialog_action(dialog, {}, '确认下载')
            enqueue.assert_called_once()
        self.manager.set_setting('minecraft.directory.enable', str(self.game_dir))
        controller.kind = 'resourcepack'
        controller.refreshContext()
        controller.downloadSelected()
        dialog = controller._download_dialog
        (self.game_dir / 'versions/1.21.8/1.21.8.json').unlink()
        with patch.object(self.window.download_page.tasks_page, 'start_install') as enqueue:
            dialog.controller.actionRequested.emit('确认下载')
            enqueue.assert_not_called()
            self.assertFalse(dialog.controller.data['targetValid'])
        dialog.reject()

    def test_room_target_always_uses_isolated_directory(self):
        name = '1.20.1'
        path = self.game_dir / 'versions' / name / (name + '.json')
        path.write_text(json.dumps(dict(id=name, buggcraftRoom={})), encoding='utf-8')
        self.manager.set_setting('minecraft.isolation', False)
        self.assertEqual(self.manager.get_minecraft_isolation_directory(directory=str(self.game_dir), version=name), str(path.parent))

    def test_intro_requires_version_selection_and_cancel_never_enqueues(self):
        downloads = self.window.download_page
        controller = downloads.content_page.controller
        downloads.open_content('resourcepack', 'browse')
        self.wait_until(lambda: not controller.busy)
        self.click(downloads.games_page, 'content-project-0')
        self.wait_until(lambda: not controller.busy)
        with patch.object(downloads.tasks_page, 'start_install') as enqueue:
            self.click(downloads.games_page, 'download-content-version')
            self.assertIsNone(controller._download_dialog)
            self.click(downloads.games_page, 'download-content-version')
            self.click(controller._download_dialog.host, 'content-download-close')
            self.assertIsNone(controller._download_dialog)
            enqueue.assert_not_called()
        self.assert_no_qml_errors()

    def test_search_pagination_preserves_rows_query_and_source_without_counts(self):
        controller = self.window.download_page.content_page.controller
        pages = [dict(hits=[dict(project_id=str(i), title='Project ' + str(i), source='Modrinth')
                           for i in range(20)], has_more=True, warnings=[]),
                 dict(hits=[dict(project_id=str(i), title='Project ' + str(i), source='Modrinth')
                           for i in range(19, 25)], has_more=False, warnings=[])]
        with patch.object(controller.catalogue, 'search', side_effect=pages) as search:
            controller.search('multi version')
            self.wait_until(lambda: not controller.busy)
            self.assertTrue(controller.has_more)
            self.assertEqual(controller.status, '')
            controller.loadMore()
            self.wait_until(lambda: not controller.busy)
        self.assertEqual(len(controller.results), 25)
        self.assertFalse(controller.has_more)
        self.assertEqual(controller.status, '')
        self.assertEqual([call.kwargs['offset'] for call in search.call_args_list], [0, 20])
        self.assertEqual([call.args[0] for call in search.call_args_list], ['multi version'] * 2)

    def test_detail_keeps_results_and_shows_all_versions_with_advice_without_blocking(self):
        downloads = self.window.download_page
        controller = downloads.content_page.controller
        downloads.open_content('mod', 'browse')
        self.wait_until(lambda: not controller.busy)
        records = [dict(id=str(i), name='File ' + str(i), game_versions=['1.20.1', '1.20.2'],
                        loaders=['fabric'], files=[]) for i in range(65)]
        with patch.object(controller.catalogue, 'versions', return_value=records):
            self.click(downloads.games_page, 'content-project-0')
            self.wait_until(lambda: not controller.busy and not controller.details_busy)
        self.assertEqual(len(controller.versions), 30)
        self.assertEqual(controller.versions[0]['compatibility_state'], 'incompatible')
        self.assertIn('1.20.2', controller.versions[0]['game_versions_label'])
        self.assertTrue(controller.viewState['can_install'])
        self.assertFalse(controller.viewState['installable'])
        self.assertTrue(self.item(downloads.games_page, 'download-content-version').isEnabled())
        self.snapshot('resource-detail-description')
        self.click(downloads.games_page, 'content-detail-tab-1')
        controller.loadMoreVersions()
        self.assertEqual(len(controller.versions), 60)
        controller.loadMoreVersions()
        self.assertEqual(len(controller.versions), 65)
        self.assertFalse(controller.viewState['has_more_versions'])
        self.snapshot('resource-detail-versions')
        with patch.object(downloads.tasks_page, 'start_install', return_value=False) as install:
            controller.downloadSelected()
            self.assertFalse(self.item(controller._download_dialog.host, 'content-download-confirm').isEnabled())
            controller._download_dialog.reject()
        install.assert_not_called()
        self.click(downloads.games_page, 'content-back')
        self.assertEqual(controller.view, 'browse')
        self.assertEqual(len(controller.results), 1)
        self.assert_no_qml_errors()

    def test_curseforge_version_paging_uses_provider_offset_after_cached_files(self):
        controller = self.window.download_page.content_page.controller
        controller.results = [dict(project_id='10', source='CurseForge')]
        records = [dict(id=str(i), name='File ' + str(i)) for i in range(50)]
        with patch.object(controller.catalogue, 'versions', side_effect=[records, [dict(id='50', name='Last')]]) as versions:
            controller.chooseProject(0)
            self.wait_until(lambda: not controller.busy)
            controller.loadMoreVersions()
            self.assertEqual(len(controller.versions), 50)
            self.assertEqual(versions.call_count, 1)
            controller.loadMoreVersions()
            self.wait_until(lambda: not controller.busy)
        self.assertEqual(versions.call_args.kwargs, {'offset': 50, 'page_info': True})
        self.assertEqual(len(controller.versions), 51)
        self.assertFalse(controller.viewState['has_more_versions'])

    def test_auto_refresh_only_on_reentering_major_download_page(self):
        downloads = self.window.download_page
        controller = downloads.content_page.controller
        downloads.open_content('shader', 'browse')
        self.wait_until(lambda: not controller.busy)
        with patch.object(controller.catalogue, 'search', return_value=[]) as search:
            downloads.on_progress_clicked()
            downloads.on_navigation(0)
            self.pump()
            search.assert_not_called()
            self.window.switch_pages('设置')
            self.window.switch_pages('下载')
            self.wait_until(lambda: not controller.busy)
            self.assertEqual(search.call_count, 1)
            self.window.switch_pages('下载')
            self.pump()
            self.assertEqual(search.call_count, 1)

    def test_file_search_is_opt_in_and_finds_any_supported_game_version(self):
        controller = self.window.download_page.content_page.controller
        controller.results = [dict(project_id='fixture', source='Modrinth')]
        files = [dict(id=str(i), name='File ' + str(i), game_versions=['26.3'], loaders=['fabric'])
                 for i in range(60)]
        files += [dict(id='old', name='Older multi-version release', game_versions=['1.20.1', '1.20.2'], loaders=['forge'])]
        with patch.object(controller.catalogue, 'versions', return_value=files):
            controller.chooseProject(0)
            self.wait_until(lambda: not controller.busy)
        self.assertEqual(controller.file_query, '')
        self.assertEqual(len(controller.versions), 30)
        controller.setFileQuery('1.20.2 forge')
        self.assertEqual([item['id'] for item in controller.versions], ['old'])
        self.assertEqual(controller.selected_version, 0)
        controller.setFileQuery('')
        self.assertEqual(len(controller.versions), 30)
        self.assertTrue(controller.viewState['has_more_versions'])

    def test_both_provider_downloads_automatically_install_and_select_instance(self):
        payload = b''
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        get = requests.get
        def local_get(url, **kwargs):
            self.assertTrue(url.startswith(('https://mod.mcimirror.top/fixture-',
                                            'https://cdn.modrinth.com/fixture-')))
            from utils.http_identity import USER_AGENT
            self.assertEqual(kwargs['headers']['User-Agent'], USER_AGENT)
            return get(f'http://127.0.0.1:{server.server_port}/pack', **kwargs)
        def install_game(downloader, identity):
            target = downloader.root / 'versions' / identity / (identity + '.json')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(dict(id=identity)), encoding='utf-8')
            target.with_suffix('.jar').write_bytes(b'fixture client jar')
        downloads = self.window.download_page
        controller = downloads.content_page.controller
        manifests = [
            ('CurseForge', 'zip', 'manifest.json', dict(manifestType='minecraftModpack', manifestVersion=1,
                 name='CurseForge fixture', minecraft={'version': '1.21.8', 'modLoaders': []}, files=[])),
            ('Modrinth', 'mrpack', 'modrinth.index.json', dict(formatVersion=1, game='minecraft',
                 name='Modrinth fixture', versionId='1', dependencies={'minecraft': '1.21.8'}, files=[]))]
        with patch('core.downloads._DownloadSession.get', side_effect=local_get), \
                patch('core.modpacks.MinecraftDownloader.install', autospec=True, side_effect=install_game):
            for provider, extension, manifest_name, manifest in manifests:
                stream = io.BytesIO()
                with zipfile.ZipFile(stream, 'w') as archive:
                    archive.writestr(manifest_name, json.dumps(manifest))
                    archive.writestr('overrides/config/example.txt', provider)
                payload = stream.getvalue()
                downloads.open_content('modpack', 'browse')
                self.wait_until(lambda: not controller.busy)
                name = 'fixture-' + provider + '.' + extension
                version = dict(name=name, source=provider, files=[dict(filename=name, size=len(payload),
                    url='https://cdn.modrinth.com/' + name, hashes={'sha1': hashlib.sha1(payload).hexdigest()})])
                controller.results = [dict(project_id='fixture', title=provider, source=provider)]
                with patch.object(controller.catalogue, 'versions', return_value=[version]):
                    controller.chooseProject(0)
                    self.wait_until(lambda: not controller.busy)
                controller.downloadSelected()
                self.confirm_download(controller)
                self.wait_until(lambda: not downloads.tasks_page._workers)
                task = downloads.tasks_page._tasks[0]
                self.assertEqual(task['state'], '已完成')
                self.assertEqual(task['status'], '整合包导入完成')
                instance = self.game_dir / 'versions' / task['version']
                self.assertEqual((instance / 'config/example.txt').read_text(), provider)
                metadata = json.loads((instance / (task['version'] + '.json')).read_text(encoding='utf-8'))
                self.assertEqual(metadata['buggcraftModpack']['source'], provider)
                self.assertEqual(self.manager.get_setting('minecraft.version.enable'), task['version'])
                self.assertEqual(task['modpack'], task['downloaded_files'][0])
                self.assertTrue(task['archive_sha256'])
                self.pump(120)
                action = self.item(downloads.tasks_page.host, 'task-action-' + task['id'])
                self.assertEqual(action.property('text'), '已导入')
                self.assertFalse(action.isEnabled())
                self.assertIs(downloads.stack.currentWidget(), downloads.tasks_page)
        self.assert_no_qml_errors()
