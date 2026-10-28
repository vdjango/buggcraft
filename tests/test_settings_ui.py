"""Visible settings acceptance: input events, persistence and scope isolation."""
import os
import shutil
import time
import math
from unittest.mock import patch

from PySide6.QtCore import QPoint, QPointF, QTimer, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication

from config.settings import SettingsManager
from test_client_ui_acceptance import ClientUiAcceptanceCase
from _qml_test_support import QTest, qt_mouse_move


class ClientUiSettingsTests(ClientUiAcceptanceCase):
    def settings_tab(self, index):
        self.navigate('launcher-nav-settings')
        self.click_ui(self.window.settings_page.tab_buttons_widget,
                      'navigation-option-' + str(index))
        page = self.window.settings_page.stack.currentWidget()
        page.ensure_loaded()
        self.pause_ui()
        return page

    def scroll_control(self, page, name):
        """Scroll with real wheel events rather than moving QML content directly."""
        for _ in range(80):
            item = self.item(page, name)
            self.assertTrue(item.isVisible(), name)
            position = item.mapToScene(item.boundingRect().center())
            if 8 < position.y() < page.quick.height() - 8:
                return item
            delta = -120 if position.y() >= page.quick.height() - 8 else 120
            point = QPoint(5, page.quick.height() // 2)
            qt_mouse_move(page.quick, point)
            event = QWheelEvent(QPointF(point), QPointF(page.quick.mapToGlobal(point)),
                                QPoint(), QPoint(0, delta), Qt.NoButton,
                                Qt.NoModifier, Qt.NoScrollPhase, False)
            event.setTimestamp(int(time.monotonic() * 1000))
            self.record('wheel', name, f'{delta}, y={position.y():.0f}')
            QApplication.sendEvent(page.quick, event)
            self.pump(35)
        root = page.quick.rootObject()
        flick = root.property('contentItem')
        self.screenshot_ui('unreachable-' + name)
        self.fail(f'Control cannot be reached: {name}; page={page.quick.height()}, '
                  f'y={position.y()}, contentHeight={flick.property("contentHeight")}, '
                  f'contentY={flick.property("contentY")}')

    def setting_click(self, page, name):
        self.scroll_control(page, name)
        return self.click_ui(page, name)

    def select_choice(self, page, key, index):
        self.choose_box(page, 'setting-select-' + key, index)

    def choose_box(self, page, name, index, commit=True):
        self.setting_click(page, name)
        self.check(self.item(page, name).property('tutorialPopupVisible'), 'choice popup opens: ' + name)
        # Move Qt's simulated pointer away so hover does not replace keyboard
        # highlighting during asynchronous popup layout.
        qt_mouse_move(page.quick, QPoint(3, 3))
        self.pause_ui()
        self.key_ui(page, Qt.Key_Home, name + '-first')
        for _ in range(index):
            self.key_ui(page, Qt.Key_Down, name + '-next')
        highlighted = self.item(page, name).property('highlightedIndex')
        if highlighted != index:
            self.screenshot_ui('choice-highlight-failure')
        self.check(highlighted == index,
                   'choice highlight reaches requested option: ' + name + ' ' + str(index)
                   + ', actual=' + str(highlighted))
        self.key_ui(page, Qt.Key_Return if commit else Qt.Key_Escape, name + '-finish')

    def persisted(self):
        return SettingsManager(self.directory / 'config')

    def slider_limit(self, page, name, upper):
        self.scroll_control(page, name)
        self.click_ui(page, name)
        slider = self.item(page, name)
        count = math.ceil((slider.property('to') - slider.property('from')) /
                          slider.property('stepSize')) + 2
        key = Qt.Key_Right if upper else Qt.Key_Left
        self.record('keyRepeat', name, f'{key}: {count}')
        for _ in range(count):
            QTest.keyClick(page.quick, key)
        self.pause_ui()
        self.check(slider is self.item(page, name) and slider.property('activeFocus'),
                   'slider retains its control and keyboard focus while saving')
        return int(slider.property('to') if upper else slider.property('from'))

    def test_general_download_sources_multi_open_and_saved_controls(self):
        page = self.settings_tab(0)
        self.setting_click(page, 'setting-toggle-launcher.allow_multiple')
        self.check(self.manager.get_setting('launcher.allow_multiple') is True,
                   'multi-open toggle saves immediately')
        self.navigate('launcher-nav-home')
        self.check(self.window.started_page.settings_manager.get_setting('launcher.allow_multiple') is True,
                   'home receives multi-open setting after navigation')
        self.check(not self.window.started_page.controller.view['allowMultiple'],
                   'session controls stay hidden until a game is running')
        page = self.settings_tab(0)
        self.setting_click(page, 'setting-toggle-launcher.allow_multiple')
        self.check(self.persisted().get_setting('launcher.allow_multiple') is False,
                   'disabled multi-open state survives a fresh settings read')
        for key, values in (
                ('settings.general.mirrors', ['自动（官方优先，失败切换镜像）', '官方', 'BMCLAPI']),
                ('settings.general.content_mirror', ['自动测速', 'MCIM', '官方'])):
            for index, expected in enumerate(values):
                self.select_choice(page, key, index)
                self.check(self.persisted().get_setting(key) == expected,
                           key + ' selected and persisted: ' + expected)
            self.setting_click(page, 'setting-select-' + key)
            self.key_ui(page, Qt.Key_Home, key + '-uncommitted')
            self.key_ui(page, Qt.Key_Escape, key + '-cancel')
            self.check(self.manager.get_setting(key) == values[-1],
                       'Escape preserves committed download source')
        self.screenshot_ui('settings-download-sources')
        for upper, value in ((False, 35), (True, 100)):
            self.slider_limit(page, 'setting-opacity-slider', upper)
            self.check(self.persisted().get_setting('launcher.opacity') == value,
                       'opacity keyboard boundary persists: ' + str(value))
        self.assert_no_qml_errors()
        self.finish_test()

    def test_global_and_instance_memory_java_and_launch_preferences(self):
        page = self.settings_tab(1)
        self.setting_click(page, 'setting-option-minecraft.isolation-0')
        self.check(self.manager.get_minecraft_isolation_directory() == str(self.game_dir),
                   'shared isolation setting resolves to game root')
        self.setting_click(page, 'setting-option-java.path-1')
        expected_java = self.manager.get_setting('java.installations')[0][0]
        self.check(self.manager.get_setting('java.path') == expected_java,
                   'listed Java selection is saved globally')
        self.setting_click(page, 'setting-toggle-minecraft.auto_allocate_memory')
        slider = self.scroll_control(page, 'setting-memory-slider')
        self.check(slider.isEnabled(), 'manual memory enables the real slider')
        maximum = int(slider.property('to'))
        for upper, expected in ((False, 512), (True, maximum)):
            self.slider_limit(page, 'setting-memory-slider', upper)
            self.check(self.manager.get_setting('memory.allocation') == expected,
                       f'memory expected={expected}, actual={self.manager.get_setting("memory.allocation")}, '
                       f'control={self.item(page,"setting-memory-slider").property("value")}, '
                       f'focus={self.item(page,"setting-memory-slider").property("activeFocus")}')
        self.select_choice(page, 'launcher.visibility', 1)
        self.select_choice(page, 'launcher.window_size', 2)
        self.setting_click(page, 'setting-option-launcher.process_priority-2')
        self.setting_click(page, 'setting-option-launcher.debug-0')
        for key, value in (('launcher.visibility', '游戏启动后最小化'),
                           ('launcher.window_size', '最大化'),
                           ('launcher.process_priority', '系统流畅优先'),
                           ('launcher.debug', '是')):
            self.check(self.persisted().get_setting(key) == value,
                       'global launch preference saved: ' + key)
        self.screenshot_ui('settings-global-launch-preferences')

        self.click_ui(self.window.title_bar, 'instances-button')
        instances = self.window.version_page.versions_page
        self.click_ui(instances, 'instance-row-1.21.8')
        self.click_ui(instances, 'instance-settings-1.21.8')
        page = self.window.version_page.settings_page
        self.check(not self.item(page, 'setting-option-minecraft.isolation-1').isEnabled(),
                   'inherited instance preferences cannot be edited')
        self.setting_click(page, 'setting-toggle-instance.enable')
        self.setting_click(page, 'setting-option-minecraft.isolation-1')
        self.check(self.manager.get_minecraft_isolation_directory() == str(self.game_dir / 'versions/1.21.8'),
                   'independent instance isolation resolves to its own directory')
        self.setting_click(page, 'setting-option-launcher.process_priority-0')
        self.check(self.manager.get_version_setting('launcher.process_priority') == '游戏性能优先',
                   'instance preference overrides global priority')
        self.check(self.manager.get_setting('launcher.process_priority') == '系统流畅优先',
                   'instance edit preserves the global priority')
        self.screenshot_ui('settings-independent-instance')
        self.setting_click(page, 'setting-toggle-instance.enable')
        self.check(self.manager.get_version_setting('launcher.process_priority') == '系统流畅优先',
                   'disabling independent settings restores global priority')
        self.setting_click(page, 'setting-toggle-instance.enable')
        self.check(self.persisted().get_version_setting('launcher.process_priority') == '游戏性能优先',
                   'reenabling restores the persisted instance override')
        self.assert_no_qml_errors()
        self.finish_test()

    def test_custom_java_cancel_invalid_file_and_real_runtime_registration(self):
        java = shutil.which('java')
        if not java:
            self.skipTest('Install Java to validate the actual executable from the UI')
        java = os.path.realpath(java)
        page = self.settings_tab(1)
        original = self.manager.get_setting('java.path')

        def choose_custom(path):
            group = next(g for g in page.controller.groups if g['key'] == 'java.path')
            name = 'setting-option-java.path-' + str(len(group['options']) - 1)
            with patch('ui.pages.qml_settings.QFileDialog.getOpenFileName', return_value=(path, '')):
                self.setting_click(page, name)

        choose_custom('')
        self.check(self.manager.get_setting('java.path') == original,
                   'canceling custom Java preserves the current selection')
        errors = []
        dismissed = []

        def dismiss_invalid():
            dialog = QApplication.activeModalWidget()
            if dialog is None:
                return
            dismissal_timer.stop()
            try:
                self.screenshot_ui('settings-invalid-java', dialog)
                self.click_ui(dialog.host, 'dialog-action-0')
                dismissed.append(True)
            except Exception as exc:
                errors.append(exc)
            finally:
                if dialog is not None and dialog.isVisible():
                    dialog.reject()

        # Scrolling to the option can take longer on hosted macOS ARM. Keep
        # polling until the real modal opens instead of firing once too early.
        dismissal_timer = QTimer(self.window)
        dismissal_timer.setInterval(50)
        dismissal_timer.timeout.connect(dismiss_invalid)
        dismissal_timer.start()
        try:
            choose_custom(str(self.directory / 'missing-java.exe'))
        finally:
            dismissal_timer.stop()
            dismissal_timer.deleteLater()
        if errors:
            raise errors[0]
        self.check(bool(dismissed), 'invalid Java warning was dismissed through its UI')
        self.check(self.manager.get_setting('java.path') == original,
                   'invalid Java warning preserves the existing selection')
        choose_custom(java)
        self.check(self.persisted().get_setting('java.path') == java,
                   'actual Java version detection registers the selected executable')
        choose_custom(java)
        self.check(sum(item[0] == java for item in self.manager.get_setting('java.installations')) == 1,
                   'choosing the same Java does not duplicate its registration')
        self.screenshot_ui('settings-real-java-selected')
        page = self.settings_tab(2)
        with patch('ui.pages.qml_lists.open_folder', return_value=True) as opened:
            self.setting_click(page, 'java-folder-' + java)
        opened.assert_called_once_with(os.path.dirname(java))
        self.setting_click(page, 'java-remove-' + java)
        self.check(not any(item[0] == java for item in self.manager.get_setting('java.installations')),
                   'Java removal updates the stored runtime list')
        self.check(self.manager.get_setting('java.path') != java,
                   'removing selected Java restores a recommended available runtime')
        self.screenshot_ui('settings-java-removed')
        self.assert_no_qml_errors()
        self.finish_test()
