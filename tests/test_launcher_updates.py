"""Drive the settings controls and asynchronous update/install flow."""
import threading
from pathlib import Path
from unittest.mock import Mock, patch

from _qml_test_support import LauncherQmlCase, ROOT
from ui import launcher_updates as updater


class LauncherUpdateTests(LauncherQmlCase):
    def setUp(self):
        super().setUp()
        # macOS packaged downloads run from within an .app; source test runners
        # are ordinary Python processes and must supply that bundle context.
        argv = patch.object(updater.sys, 'argv', [str(self.directory / 'Buggcraft.app/Contents/MacOS/Buggcraft')])
        argv.start()
        self.addCleanup(argv.stop)
        self.app_proxy = Mock()
        self.updates = updater.LauncherUpdateController(self.window, self.app_proxy, ROOT / 'resources')
        self.page = self.window.settings_page.general_page
        self.page.controller.bind_updates(self.updates)
        self.window.switch_pages('设置')
        self.window.settings_page.general_tab_btn_clicked()
        self.pump()

    def tearDown(self):
        self.updates.shutdown()
        super().tearDown()

    def test_manual_button_shows_latest_and_channel_switch_checks_without_restart(self):
        status = self.item(self.page, 'launcher-update-status')
        self.assertIn(self.updates.version, status.property('text'))
        with patch.object(updater, 'check_for_update', return_value=None) as check:
            self.click(self.page, 'launcher-check-updates')
            self.wait_until(lambda: not self.updates.busy)
            check.assert_called_once_with(self.updates.version, 'stable')
            self.assertIn('最新可用版本', self.item(self.page, 'launcher-update-status').property('text'))
            self.click(self.page, 'launcher-update-channel-development')
            self.wait_until(lambda: not self.updates.busy)
            self.assertEqual(self.manager.get_setting('settings.general.update'), 'development')
            self.assertEqual(check.call_args.args, (self.updates.version, 'beta'))
            self.assertIn('开发版', self.item(self.page, 'launcher-update-status').property('text'))
        self.snapshot('launcher-updates-latest')
        self.assert_no_qml_errors()

    def test_old_channel_response_is_discarded_and_workers_do_not_overlap(self):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        stale = {'version': '9.0.0', 'notes': 'stable fixture'}
        def check(version, channel):
            if channel == 'stable':
                entered.set()
                release.wait(4)
                return stale
            return None
        with patch.object(updater, 'check_for_update', side_effect=check) as request, \
                patch.object(self.updates, 'offer') as offer:
            self.updates.check()
            self.wait_until(entered.is_set)
            self.updates.check()
            self.assertEqual(len(self.updates.workers), 1)
            self.page.controller.setValue('settings.general.update', 'development')
            release.set()
            self.wait_until(lambda: not self.updates.busy)
            self.assertEqual([call.args[1] for call in request.call_args_list], ['stable', 'beta'])
            offer.assert_not_called()
            self.assertEqual(self.updates.workers, [])

    def test_network_failure_visible_and_manual_retry_can_prompt_again(self):
        update = {'version': '9.0.0', 'notes': 'fixture'}
        with patch.object(updater, 'check_for_update', side_effect=OSError('offline')), \
                patch.object(updater.QMessageBox, 'warning') as warning:
            self.updates.check(manual=True)
            self.wait_until(lambda: not self.updates.busy)
            self.assertIn('失败', self.updates.status)
            warning.assert_called_once()
        with patch.object(updater, 'check_for_update', return_value=update), \
                patch.object(self.updates, 'offer') as offer:
            self.updates.prompted.add(update['version'])
            self.updates.check(manual=True)
            self.wait_until(lambda: not self.updates.busy)
            offer.assert_called_once_with(update, True)

    def test_download_install_quits_only_after_verified_package(self):
        package = self.directory / 'verified.exe'
        package.write_bytes(b'verified update fixture')
        update = {'version': '9.0.0'}
        def download(manifest, directory, progress):
            progress(32, 64)
            return package
        with patch.object(updater, 'download_update', side_effect=download), \
                patch.object(updater.platform, 'system', return_value='Darwin'), \
                patch.object(updater.QMessageBox, 'warning') as warning, \
                patch.object(self.updates, 'open_download_page') as fallback, \
                patch.object(updater, 'apply_update') as install:
            self.updates.download(update)
            self.wait_until(lambda: not self.updates.busy)
            install.assert_called_once_with(package)
            self.app_proxy.quit.assert_called_once()
            self.assertIn('重启', self.updates.status)
            warning.assert_not_called()
            fallback.assert_not_called()
        self.app_proxy.quit.reset_mock()
        with patch.object(updater, 'download_update', side_effect=ValueError('SHA-256 mismatch')), \
                patch.object(updater, 'apply_update') as install, \
                patch.object(updater.QMessageBox, 'warning'), \
                patch.object(self.updates, 'open_download_page') as fallback:
            self.updates.download(update)
            self.wait_until(lambda: not self.updates.busy)
            install.assert_not_called()
            self.app_proxy.quit.assert_not_called()
            fallback.assert_called_once_with(update)
            self.assertIn('校验失败', self.updates.status)
