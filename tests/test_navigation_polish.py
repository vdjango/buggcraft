"""Exercise scrolling, import navigation and persistent window appearance."""
import json
from unittest.mock import patch

from PySide6.QtCore import QObject, QPointF
from PySide6.QtTest import QTest

from _qml_test_support import LauncherQmlCase, Qt
from config.settings import SettingsManager, launcher_opacity


class NavigationPolishTests(LauncherQmlCase):
    def test_history_filters_logs_and_failed_task_action_use_shared_list(self):
        downloads = self.window.download_page
        page = downloads.tasks_page
        page._tasks = [dict(id='failed-fixture', version='1.21.8-Forge', game_dir=str(self.game_dir),
                            state='失败', status='下载失败', error='Local HTTP fixture', maximum=100,
                            progress=30, created_at='2026-10-23', logs=['download failed fixture']),
                       dict(id='completed-fixture', version='1.20.1', game_dir=str(self.game_dir),
                            state='已完成', status='安装完成', maximum=100, progress=100,
                            created_at='2026-10-23', logs=['complete'])]
        page.refresh_tasks()
        downloads.on_progress_clicked()
        self.pump(120)
        listing = self.item(page.host, 'download-history-list')
        self.assertEqual(listing.property('count'), 2)
        self.snapshot('history-mixed-states')
        page.view_controller.setFilter('失败')
        self.pump()
        self.assertEqual(listing.property('count'), 1)
        # QApplication.sendEvent does not run the platform mouse-focus path.
        # Model the focus a real click gives this embedded QQuickWidget before
        # asserting keyboard behavior inside the modal.
        page.host.quick.setFocus(Qt.MouseFocusReason)
        self.click(page.host, 'task-log-failed-fixture')
        dialog = page.host.quick.rootObject().findChild(QObject, 'task-log-dialog')
        self.assertIsNotNone(dialog)
        self.wait_until(lambda: dialog.property('activeFocus'))
        self.assertTrue(page.view_controller._log_timer.isActive())
        self.assertIn('download failed fixture', page.view_controller.logLines)
        # Close through the real overlay, then exercise the failed-task action.
        QTest.keyClick(page.host.quick, Qt.Key_Escape)
        self.wait_until(lambda: not page.view_controller._log_timer.isActive())
        self.assertFalse(page.view_controller._log_timer.isActive())
        with patch.object(page, 'start_install') as retry:
            self.click(page.host, 'task-action-failed-fixture')
        self.assertEqual(retry.call_args.args[:2], ('1.21.8-Forge', str(self.game_dir)))
        self.assert_no_qml_errors()

    def test_opacity_defaults_clamps_saves_applies_and_survives_restart(self):
        page = self.window.settings_page.general_page
        self.assertEqual(launcher_opacity(self.manager), 85)
        self.assertAlmostEqual(self.window.windowOpacity(), .85, delta=.005)
        self.window.switch_pages('设置')
        self.window.settings_page.general_tab_btn_clicked()
        self.pump()
        slider = self.item(page, 'setting-opacity-slider')
        self.assertTrue(slider.isVisible())
        self.assertEqual((slider.property('from'), slider.property('to')), (35, 100))
        self.snapshot('opacity-setting')
        for value, expected in ((12, 35), (85, 85), (150, 100), (35, 35)):
            page.controller.setValue('launcher.opacity', value)
            self.pump()
            self.assertEqual(self.manager.get_setting('launcher.opacity'), expected)
            self.assertAlmostEqual(self.window.windowOpacity(), expected / 100, delta=.005)
            self.assertEqual(SettingsManager(self.manager.config_path).get_setting('launcher.opacity'), expected)
        # Test keyboard interaction with the actual QML slider, including the limit.
        slider = self.item(page, 'setting-opacity-slider')
        slider.forceActiveFocus()
        QTest.keyClick(page.quick, Qt.Key_Left)
        self.pump()
        self.assertEqual(self.manager.get_setting('launcher.opacity'), 35)
        QTest.keyClick(page.quick, Qt.Key_Right)
        self.pump()
        self.assertEqual(self.manager.get_setting('launcher.opacity'), 36)
        for invalid in (None, 'broken', float('inf')):
            self.manager.set_setting('launcher.opacity', invalid)
            self.assertEqual(launcher_opacity(self.manager), 85)
        self.manager.set_setting('launcher.opacity', 85)
        self.assert_no_qml_errors()

    def test_header_centers_visible_content_and_sidebars_shift_without_resizing(self):
        header = self.window.title_bar
        for selected in (False, True):
            self.window.switch_pages('实例' if selected else '开始')
            self.pump()
            button = self.item(header, 'instances-button')
            content = self.item(header, 'instances-button-content')
            center = content.mapToItem(button, content.boundingRect().center())
            self.assertAlmostEqual(center.x(), button.width() / 2, delta=1)
            self.assertAlmostEqual(center.y(), button.height() / 2, delta=1)
            if not selected:
                label = self.item(header, 'instances-button-label')
                center = label.mapToItem(button, label.boundingRect().center())
                self.assertAlmostEqual(center.x(), button.width() / 2, delta=1)
            self.snapshot('header-selected-' + str(selected))
        self.window.switch_pages('下载')
        self.pump()
        sidebar = self.window.download_page.tab_buttons_widget.quick.rootObject()
        column = sidebar.childItems()[0]
        self.assertEqual(column.x(), 12)
        self.assertEqual(column.width(), 155)
        self.assertEqual(self.window.download_page.stack.width(), 686)
        self.assert_no_qml_errors()

    def test_catalogue_scroll_appends_once_keeps_position_and_import_back_keeps_results(self):
        downloads = self.window.download_page
        controller = downloads.content_page.controller
        downloads.open_content('shader', 'browse')
        self.wait_until(lambda: not controller.busy)
        def search(query, *args, **kwargs):
            offset = kwargs['offset']
            return dict(hits=[dict(project_id=str(i), title='Shader ' + str(i), source='Modrinth')
                              for i in range(offset, offset + 20)], has_more=offset < 40)
        with patch.object(controller.catalogue, 'search', side_effect=search) as fetch:
            controller.search('scroll fixture')
            self.wait_until(lambda: not controller.busy)
            self.pump(150)
            listing = self.item(downloads.games_page, 'content-project-list')
            self.assertEqual(fetch.call_count, 1)
            listing.setProperty('contentY', listing.property('contentHeight') - listing.height())
            position = listing.property('contentY')
            self.wait_until(lambda: len(controller.results) == 40 and not controller.busy)
            self.pump(250)
            self.assertEqual(fetch.call_count, 2)
            self.assertAlmostEqual(listing.property('contentY'), position, delta=2)
            self.snapshot('catalogue-auto-appended')
            with patch.object(controller, 'choosePack'):
                self.click(downloads.games_page, 'download-import-pack')
            self.click(downloads.content_page, 'pack-import-back')
            self.assertEqual(controller.query, 'scroll fixture')
            self.assertEqual(controller.kind, 'shader')
            self.assertEqual(downloads.games_page.controller.category, 'shader')
            self.assertEqual(len(controller.results), 40)
            self.assertAlmostEqual(listing.property('contentY'), position, delta=2)
            self.assertEqual(fetch.call_count, 2)
        self.assert_no_qml_errors()

    def test_file_versions_scroll_automatically_and_detail_hides_categories(self):
        downloads = self.window.download_page
        controller = downloads.content_page.controller
        downloads.open_content('mod', 'browse')
        self.wait_until(lambda: not controller.busy)
        files = [dict(id=str(i), name='File ' + str(i), game_versions=['1.21.8'], files=[])
                 for i in range(75)]
        with patch.object(controller.catalogue, 'versions', return_value=files) as fetch:
            self.click(downloads.games_page, 'content-project-0')
            self.wait_until(lambda: not controller.busy and not controller.details_busy)
            self.assertFalse(self.item(downloads.games_page, 'download-categories').isVisible())
            self.pump(200)
            self.assertEqual(len(controller.versions), 30)
            self.click(downloads.games_page, 'content-detail-tab-1')
            listing = self.item(downloads.games_page, 'content-version-list')
            listing.setProperty('contentY', listing.property('contentHeight') - listing.height())
            position = listing.property('contentY')
            self.wait_until(lambda: len(controller.versions) == 60)
            self.pump(200)
            self.assertEqual(len(controller.versions), 60)
            self.assertAlmostEqual(listing.property('contentY'), position, delta=2)
            self.assertEqual(fetch.call_count, 1)
            listing.setProperty('contentY', listing.property('contentHeight') - listing.height())
            self.wait_until(lambda: len(controller.versions) == 75)
            self.assertFalse(controller.viewState['has_more_versions'])
            self.snapshot('versions-auto-appended')
        self.click(downloads.games_page, 'content-back')
        self.assertTrue(self.item(downloads.games_page, 'download-categories').isVisible())
        self.assert_no_qml_errors()

    def test_failed_append_stops_requests_until_explicit_retry(self):
        downloads = self.window.download_page
        controller = downloads.content_page.controller
        downloads.open_content('resourcepack', 'browse')
        self.wait_until(lambda: not controller.busy)
        initial = dict(hits=[dict(project_id=str(i), title=str(i)) for i in range(20)], has_more=True)
        with patch.object(controller.catalogue, 'search', side_effect=[initial, RuntimeError('offline')]) as fetch:
            controller.search('failure')
            self.wait_until(lambda: not controller.busy)
            self.pump()
            listing = self.item(downloads.games_page, 'content-project-list')
            listing.setProperty('contentY', listing.property('contentHeight') - listing.height())
            self.wait_until(lambda: controller.status.startswith('获取失败'))
            self.pump(450)
            self.assertEqual(fetch.call_count, 2)
            self.assertEqual(len(controller.results), 20)
        self.assert_no_qml_errors()
