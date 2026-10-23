"""Render every production page with nonempty data and exercise QML actions."""
import json
from unittest.mock import Mock, patch

from _qml_test_support import LauncherQmlCase, QQuickWidget, QTest, Qt
from PySide6.QtWidgets import QAbstractButton, QLineEdit, QPlainTextEdit


class AllLauncherPagesTests(LauncherQmlCase):
    def test_same_main_button_handles_default_stop_and_multiple_start(self):
        from types import SimpleNamespace
        page = self.window.started_page
        launcher = page.launcher
        worker = SimpleNamespace(process=SimpleNamespace(pid=12345), start_thread=None)
        launcher._sessions = [dict(id=1, phase='running', launcher=worker,
            instance=(str(self.game_dir), '1.21.8', str(self.game_dir / 'versions/1.21.8')))]
        launcher.selected_id = 1
        try:
            for multiple in (False, True):
                self.manager.set_setting('launcher.allow_multiple', multiple)
                page.refresh_game_sessions()
                self.pump()
                self.assertEqual(page.controller.view['launchTitle'], '启动游戏' if multiple else '停止游戏')
                self.assertEqual(self.item(page, 'game-session-actions').isVisible(), multiple)
                with patch.object(page, 'started_game') as start:
                    self.click(page, 'launch-game')
                start.assert_called_once_with(additional=multiple)
                self.snapshot('home-multiple-' + str(multiple))
            names = []
            def collect(item):
                names.append(item.objectName())
                for child in item.childItems():
                    collect(child)
            collect(page.quick.rootObject())
            self.assertNotIn('launch-additional-game', names)
        finally:
            launcher._sessions = []
        self.assert_no_qml_errors()

    def test_all_pages_render_without_widgets_controls_or_qml_errors(self):
        downloads = self.window.download_page
        games = downloads.games_page.controller
        games.versions = [dict(id='1.21.8', type='release', releaseTime='2026-01-01')]
        games.changed.emit()
        tasks = downloads.tasks_page
        tasks._tasks = [dict(id='fixture', version='1.21.8', game_dir=str(self.game_dir),
                            state='已完成', status='安装完成', progress=144, maximum=144,
                            created_at='2026-10-23', logs=['fixture log'])]
        tasks.refresh_tasks()
        self.window.switch_pages('开始')
        self.snapshot('home')
        self.window.switch_pages('下载')
        for index in range(2):
            downloads.activate_index(index)
            self.pump()
            self.snapshot('download-' + str(index))
        downloads.open_content('modpack', 'browse')
        self.wait_until(lambda: not downloads.content_page.controller.busy)
        downloads.content_page.controller.chooseProject(0)
        self.wait_until(lambda: not downloads.content_page.controller.busy)
        self.snapshot('content')
        downloads.open_content('modpack', 'import')
        self.snapshot('import')
        self.window.switch_pages('设置')
        for index in range(4):
            self.window.settings_page.activate_index(index)
            self.pump()
            self.snapshot('settings-' + str(index))
        self.window.switch_pages('实例')
        for index in range(2):
            self.window.version_page.activate_index(index)
            self.pump()
            self.snapshot('instances-' + str(index))
        for dialog in (self.window.started_page.login_dialog,
                       self.window.java_runtime_full, self.window.gamed_version_full):
            dialog.show()
            self.pump()
            self.snapshot(type(dialog).__name__, dialog)
            dialog.hide()
        self.window._show_debug_output()
        self.window.minecraft_handle_output('detail fixture')
        self.pump(120)
        self.assertIn('detail fixture', self.window._debug_dialog.controller.log)
        widgets = self.window.findChildren(QQuickWidget)
        self.assertGreaterEqual(len(widgets), 18)
        for widget in widgets:
            self.assertEqual(widget.status(), QQuickWidget.Ready,
                             '\n'.join(error.toString() for error in widget.errors()))
        self.assertEqual(self.window.findChildren(QAbstractButton), [])
        self.assertEqual(self.window.findChildren(QLineEdit), [])
        self.assertEqual(self.window.findChildren(QPlainTextEdit), [])
        self.assert_no_qml_errors()

    def test_hidden_pages_are_loaded_on_demand(self):
        self.assertEqual(self.window.started_page.quick.status(), QQuickWidget.Ready)
        self.assertEqual(self.window.settings_page.java_page.quick.status(), QQuickWidget.Null)
        self.assertEqual(self.window.started_page.login_dialog.quick.status(), QQuickWidget.Null)
        self.window.switch_pages('设置')
        self.window.settings_page.java_tab_btn_clicked()
        self.pump()
        self.assertEqual(self.window.settings_page.java_page.quick.status(), QQuickWidget.Ready)
        self.assert_no_qml_errors()

    def test_stale_version_cannot_be_selected_and_empty_directory_clears_home(self):
        header = self.window.title_bar
        (self.game_dir / 'versions/1.20.1/1.20.1.json').unlink()
        header.controller.selectVersion('1.20.1')
        self.assertEqual(self.manager.get_setting('minecraft.version.enable'), '1.21.8')
        self.assertNotIn('1.20.1', header.controller.versions)
        empty = str(self.directory / 'empty')
        self.manager.set_setting('minecraft.directory.installed', [empty])
        instances = self.window.version_page.versions_page.controller
        instances.reload()
        instances.selectDirectory(empty)
        self.assertIsNone(self.manager.get_setting('minecraft.version.enable'))
        self.assertIsNone(self.window.launcher.minecraft_version)
        self.assertEqual(self.window.started_page.controller.view['launchTitle'], '选择游戏')
        self.click(header, 'version-picker')
        self.assertTrue(header.quick.rootObject().property('versionPopupVisible'))
        QTest.keyClick(header._picker.quick, Qt.Key_Escape)
        self.pump()
        self.assertFalse(header.quick.rootObject().property('versionPopupVisible'))
        self.assert_no_qml_errors()

    def test_collapse_crops_original_image_and_keeps_content_in_place_on_all_pages(self):
        from PySide6.QtCore import QPoint
        expanded = self.window.size()
        right = self.window.x() + self.window.width()
        cropped = self.window.cache_expanded.copy(self.window.menu_width, 0,
                      expanded.width() - self.window.menu_width, expanded.height())
        self.assertEqual(self.window.cache_collapsed.toImage(), cropped.toImage())
        for name in self.window.tab_names:
            self.window.switch_pages(name)
            self.pump()
            self.assertEqual(self.window.title_bar.controller.active, name)
            page = self.window.content_stack.currentWidget()
            content = getattr(page, 'stack', page)
            def position():
                if page is self.window.started_page:
                    button = self.item(page, 'launch-game')
                    return self.window.pos() + page.quick.mapTo(self.window, button.mapToScene(button.boundingRect().center()).toPoint())
                return self.window.pos() + content.mapTo(self.window, QPoint(0, 0))
            origin = position()
            width = content.width()
            for _ in range(8):
                self.window.title_bar.controller.toggleMenu()
                self.pump()
                collapsed = self.window.menu_collapsed
                self.assertEqual(self.window.width(), expanded.width() - (self.window.menu_width if collapsed else 0))
                self.assertEqual(self.window.height(), expanded.height())
                self.assertEqual(self.window.x() + self.window.width(), right)
                self.assertEqual(position(), origin, name)
                if page is not self.window.started_page:
                    self.assertEqual(content.width(), width, name)
                self.assertEqual(collapsed, self.window.title_bar.controller.collapsed)
            self.snapshot('sidebar-' + name)
        self.assert_no_qml_errors()

    def test_game_category_buttons_switch_to_real_content(self):
        downloads = self.window.download_page
        downloads.on_download_clicked()
        self.pump()
        categories = self.item(downloads.games_page, 'download-categories')
        geometry = (categories.x(), categories.y(), categories.width(), categories.height())
        for index, kind in enumerate(('mod', 'resourcepack', 'shader', 'modpack'), 1):
            self.click(downloads.games_page, 'content-kind-' + str(index))
            self.wait_until(lambda: not downloads.content_page.controller.busy)
            self.assertIs(downloads.stack.currentWidget(), downloads.games_page)
            self.assertEqual(downloads.navigation.index, 0)
            self.assertEqual(downloads.navigation.entries, ['游戏下载', '下载记录'])
            self.assertEqual(downloads.games_page.controller.category, kind)
            self.assertEqual(downloads.content_page.controller.kind, kind)
            self.assertEqual(len(downloads.content_page.controller.results), 1)
            self.assertEqual((categories.x(), categories.y(), categories.width(), categories.height()), geometry)
            self.assertEqual(downloads.games_page.quick.rootObject().property('state').toVariant()['category'], kind)
        self.click(downloads.games_page, 'content-kind-0')
        self.assertEqual(downloads.games_page.controller.category, 'game')
        self.assertIs(downloads.stack.currentWidget(), downloads.games_page)
        self.assert_no_qml_errors()

    def test_settings_preserve_sections_radios_and_collapsed_state_after_save(self):
        self.window.switch_pages('设置')
        self.window.settings_page.global_tab_btn_clicked()
        page = self.window.settings_page.global_version_page
        self.pump()
        groups = page.controller.groups
        self.assertEqual([group['title'] for group in groups], [
            '版本隔离', '游戏 Java', '游戏内存分配', '启动器可见性',
            '游戏窗口分辨率', '进程优先级', '游戏调试模式'])
        isolation = self.item(page, 'setting-group-minecraft.isolation')
        self.assertTrue(isolation.property('expanded'))
        self.click(page, 'setting-option-minecraft.isolation-0')
        self.assertFalse(self.manager.get_setting('minecraft.isolation'))
        self.click(page, 'setting-group-minecraft.isolation-header')
        self.assertFalse(self.item(page, 'setting-group-minecraft.isolation').property('expanded'))
        page.controller.setValue('launcher.window_size', '最大化')
        self.pump()
        self.assertFalse(self.item(page, 'setting-group-minecraft.isolation').property('expanded'))
        self.assertEqual(self.item(page, 'setting-group-minecraft.isolation').height(), 60)
        self.assertTrue(page.memory_timer.isActive())
        self.window.settings_page.general_tab_btn_clicked()
        self.pump()
        self.assertFalse(page.memory_timer.isActive())
        self.assert_no_qml_errors()

    def test_settings_descriptions_and_game_list_use_existing_bounds_and_row_style(self):
        from PySide6.QtCore import QPointF
        self.window.switch_pages('设置')
        self.window.settings_page.global_tab_btn_clicked()
        page = self.window.settings_page.global_version_page
        self.pump()
        for index in range(2):
            description = self.item(page, 'setting-option-minecraft.isolation-' + str(index) + '-description')
            self.assertLessEqual(description.mapToScene(QPointF(description.width(), 0)).x(), page.width() - 15)
        downloads = self.window.download_page
        downloads.games_page.controller.versions = [dict(id='1.20.1', type='release', releaseTime='2026-01-01')]
        downloads.on_download_clicked()
        self.pump()
        row = self.item(downloads.games_page, 'install-1.20.1')
        self.assertEqual(row.height(), 70)
        self.assertEqual(row.property('radius'), 0)
        self.assertTrue(row.property('icon').toString().endswith('offline_login.png'))
        self.assert_no_qml_errors()

    def test_import_entry_returns_to_previous_catalogue_without_duplicate_sidebar_route(self):
        downloads = self.window.download_page
        downloads.open_content('mod', 'browse')
        self.wait_until(lambda: not downloads.content_page.controller.busy)
        with patch.object(downloads.content_page.controller, 'choosePack') as choose:
            self.click(downloads.games_page, 'download-import-pack')
        choose.assert_called_once()
        self.assertEqual(downloads.content_page.controller.view, 'import')
        self.assertIs(downloads.stack.currentWidget(), downloads.content_page)
        self.click(downloads.content_page, 'pack-import-back')
        self.pump()
        self.assertIs(downloads.stack.currentWidget(), downloads.games_page)
        self.assertEqual(downloads.games_page.controller.category, 'mod')
        self.assertEqual(downloads.content_page.controller.kind, 'mod')
        self.assertEqual(len(downloads.content_page.controller.results), 1)
        self.assert_no_qml_errors()

    def test_memory_uses_one_section_and_manual_slider_enables_without_changing_scope(self):
        page = self.window.settings_page.global_version_page
        self.window.switch_pages('设置')
        self.window.settings_page.global_tab_btn_clicked()
        page.controller.setValue('minecraft.auto_allocate_memory', False)
        self.pump()
        groups = page.controller.groups
        memory = next(group for group in groups if group['kind'] == 'memory')
        self.assertTrue(memory['memory']['enabled'])
        self.assertFalse(any(group['key'] == 'memory.allocation' for group in groups))
        page.controller.setValue('memory.allocation', 3072)
        self.pump()
        self.assertEqual(self.manager.get_setting('memory.allocation'), 3072)
        self.assertGreater(page.controller.memoryInfo['total'], 0)
        self.assertEqual([section['title'] for section in self.window.settings_page.about_page.controller.view['sections']],
                         ['关于', '鸣谢', '依赖', '法律声明'])
        self.assert_no_qml_errors()

    def test_version_picker_changes_selected_game_once(self):
        from PySide6.QtTest import QSignalSpy
        spy = QSignalSpy(self.window.title_bar.version_changed)
        header = self.window.title_bar
        picker = self.item(header, 'version-picker')
        self.click(header, 'version-picker')
        self.assertTrue(header.quick.rootObject().property('versionPopupVisible'))
        QTest.keyClick(header._picker.quick, Qt.Key_Down)
        QTest.keyClick(header._picker.quick, Qt.Key_Return)
        self.pump()
        self.assertEqual(self.window.launcher.minecraft_version, '1.20.1')
        self.assertEqual(spy.count(), 1)
        self.assert_no_qml_errors()

    def test_header_preserves_button_sizes_and_scrolls_current_version_into_popup(self):
        for index in range(16):
            name = 'zz-fixture-' + str(index).zfill(2)
            target = self.game_dir / 'versions' / name / (name + '.json')
            target.parent.mkdir(parents=True)
            target.write_text(json.dumps({'id': name}), encoding='utf-8')
        header = self.window.title_bar
        header.refresh_versions()
        header.controller.selectVersion(header.controller.versions[-1])
        selected_version = header.controller.selected
        self.pump()
        for name, width in (('version-picker', 125), ('instances-button', 110)):
            button = self.item(header, name)
            self.assertEqual((button.width(), button.height()), (width, 32))
        self.click(header, 'version-picker')
        popup = header._picker
        self.assertEqual((popup.width(), popup.height()), (310, 420))
        self.assertEqual(header.controller.versions[0], selected_version)
        self.assertEqual(self.item(header, 'version-picker').property('text'), '版本')
        selected = self.item(popup.host, 'choice-option-0')
        self.assertTrue(selected.property('selected'))
        center = selected.mapToScene(selected.boundingRect().center())
        self.assertGreater(center.y(), 0)
        self.assertLess(center.y(), popup.height())
        self.assertTrue(self.app.screenAt(popup.pos()).availableGeometry().contains(popup.geometry()))
        self.snapshot('version-dropdown', popup)
        QTest.keyClick(popup.quick, Qt.Key_End)
        self.pump()
        first = self.item(popup.host, 'choice-option-' + str(len(header.controller.versions) - 1))
        self.assertFalse(first.property('selected'))
        self.assertTrue(first.property('keyboardFocused'))
        QTest.keyClick(popup.quick, Qt.Key_Escape)
        self.assertEqual(header.controller.selected, selected_version)
        self.window.switch_pages('实例')
        self.pump()
        self.assertTrue(self.item(header, 'instances-button').property('selected'))
        self.assert_no_qml_errors()

    def test_loader_dialog_loads_and_enforces_exclusions(self):
        page = self.window.download_page.games_page
        page.controller.versions = [dict(id='1.20.1', type='release', releaseTime='2026-01-01')]
        page.controller.changed.emit()
        self.window.download_page.on_download_clicked()
        self.pump()
        self.click(page, 'install-1.20.1')
        page.controller.selectLoader('Forge')
        self.wait_until(lambda: not page.controller.loader_busy)
        blocked = {item['name']: item['reason'] for item in page.controller.view['components']}
        self.assertIn('Forge', blocked['Fabric'])
        page.controller.selectLoader('Fabric')
        self.assertEqual(page.controller.loader, 'Forge')
        self.snapshot('install-game')
        self.assert_no_qml_errors()

    def test_version_popup_reuses_host_and_repeated_mouse_keyboard_and_cancel_work(self):
        header = self.window.title_bar
        popup = None
        for index in range(18):
            previous = header.controller.selected
            self.click(header, 'version-picker')
            self.assertTrue(header.controller.picker_open)
            if popup is None:
                popup = header._picker
            self.assertIs(header._picker, popup)
            # Exercise the QWidget hit-testing path with the popup present.
            self.app.widgetAt(popup.mapToGlobal(popup.rect().center()))
            if index % 3 == 0:
                QTest.keyClick(popup.quick, Qt.Key_Escape)
                expected = previous
            elif index % 3 == 1:
                QTest.keyClick(popup.quick, Qt.Key_End)
                QTest.keyClick(popup.quick, Qt.Key_Return)
                expected = header.controller.versions[-1]
            else:
                self.click(popup.host, 'choice-option-0')
                expected = header.controller.versions[0]
            self.pump()
            self.assertFalse(header.controller.picker_open)
            self.assertEqual(header.controller.selected, expected)
        self.assert_no_qml_errors()

    def test_header_close_button_finishes_handler_before_unloading(self):
        self.click(self.window.title_bar, 'close-launcher')
        self.assertFalse(self.window.isVisible())
        self.assertTrue(self.window._closing)
        self.assertEqual(self.window.title_bar.quick.status(), QQuickWidget.Null)
        self.assert_no_qml_errors()

    def test_settings_save_to_correct_scope(self):
        general = self.window.settings_page.general_page.controller
        general.setValue('launcher.allow_multiple', True)
        self.assertTrue(self.manager.get_setting('launcher.allow_multiple'))
        global_settings = self.window.settings_page.global_version_page.controller
        global_settings.setValue('launcher.window_size', '最大化')
        self.assertEqual(self.manager.get_setting('launcher.window_size'), '最大化')
        instance = self.window.version_page.settings_page.controller
        instance.setValue('instance.enable', True)
        instance.setValue('launcher.window_size', '与启动器一致')
        self.assertEqual(self.manager.get_version_setting('launcher.window_size'), '与启动器一致')
        self.assertEqual(self.manager.get_setting('launcher.window_size'), '最大化')


if __name__ == '__main__':
    import unittest
    unittest.main()
