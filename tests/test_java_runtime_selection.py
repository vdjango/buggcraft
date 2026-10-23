"""Select actual compatible runtimes, preserving global and per-instance choices."""
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from _qml_test_support import LauncherQmlCase
from core.java_runtime import JavaRuntimeUnavailable, select_java
from core.launch_options import required_java
from config.settings import SettingsManager
from config.javafinder import JavaPathFinder


class JavaRuntimeSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.settings = SettingsManager(self.root / 'config')
        self.paths = {}
        for version in (8, 21, 25, 26):
            path = self.root / f'java-{version}.exe'
            path.touch()
            self.paths[version] = str(path)
        self.settings.set_setting('java.path', self.paths[21])
        self.settings.set_setting('java.installations', [
            [self.paths[n], 'untrusted cached version', [99]] for n in (26, 8, 25)])
        probe = patch('core.java_runtime.JavaPathFinder._get_java_version', side_effect=lambda path:
                      (f'Java {next(n for n, p in self.paths.items() if p == path)}',
                       (next(n for n, p in self.paths.items() if p == path), 0, 1)))
        self.probe_patcher = probe
        self.probe = probe.start()
        self.addCleanup(probe.stop)

    def metadata(self, version, **data):
        target = self.root / 'versions' / version / (version + '.json')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data), encoding='utf-8')

    def test_26_1_and_later_select_verified_java_25_without_changing_preferences(self):
        for version in ('26.1', '26.2', '26.3', '26.3-forge-test'):
            with self.subTest(version=version):
                selected = select_java(self.settings, self.root, version)
                self.assertEqual((selected.path, selected.major, selected.switched), (self.paths[25], 25, True))
                self.assertEqual(self.settings.get_setting('java.path'), self.paths[21])

    def test_usable_selected_runtime_is_retained_and_java_8_is_understood(self):
        self.metadata('1.20.1', javaVersion={'majorVersion': 17})
        self.assertEqual(select_java(self.settings, self.root, '1.20.1').path, self.paths[21])
        self.assertEqual(self.probe.call_count, 1)
        self.settings.set_setting('java.path', self.paths[8])
        self.metadata('1.12.2', javaVersion={'majorVersion': 8})
        with patch('core.java_runtime.JavaPathFinder._get_java_version', return_value=('1.8.0_451', (1, 8, 0, 451))):
            self.assertEqual(select_java(self.settings, self.root, '1.12.2').major, 8)

    def test_stale_cached_versions_and_missing_files_do_not_count(self):
        self.settings.set_setting('java.installations', [[self.paths[8], 'Java 25', [25]],
                                                        [str(self.root / 'missing.exe'), 'Java 25', [25]]])
        with self.assertRaises(JavaRuntimeUnavailable) as failure:
            select_java(self.settings, self.root, '26.3')
        self.assertEqual(failure.exception.required, 25)
        self.assertIn(self.paths[21], str(failure.exception))
        self.assertIn('Java 21', str(failure.exception))

    def test_parent_requirement_cannot_be_lowered_by_loader_metadata(self):
        self.metadata('custom', javaVersion={'majorVersion': 17}, inheritsFrom='26.1')
        self.assertEqual(required_java(self.root, 'custom'), 25)
        self.metadata('future', javaVersion={'majorVersion': 26}, inheritsFrom='26.1')
        self.assertEqual(required_java(self.root, 'future'), 26)

    def test_real_java_version_output_formats_include_major_only_and_javaw(self):
        java = self.root / 'java.exe'
        java.touch()
        javaw = self.root / 'javaw.exe'
        javaw.touch()
        cases = [('java version "25" 2025-09-16', (25, 0, 0)),
                 ('openjdk 25 2025-09-16', (25, 0, 0)),
                 ('openjdk version "25.0.1" 2025-10-21', (25, 0, 1)),
                 ('openjdk version "25-ea"', (25, 0, 0)),
                 ('openjdk version "25.0.1-ea+8"', (25, 0, 1)),
                 ('java version "1.8.0_451"', (1, 8, 451))]
        # This test exercises the actual probe/parser, bypassing the selection fixture's stub.
        self.probe_patcher.stop()
        for output, expected in cases:
            with self.subTest(output=output), patch('config.javafinder.subprocess.run', return_value=
                    SimpleNamespace(returncode=0, stderr=output, stdout='')) as run:
                raw, parsed = JavaPathFinder()._get_java_version(str(javaw))
                self.assertEqual((raw, parsed), (output, expected))
                self.assertEqual(run.call_args.args[0], [str(java), '-version'])


class LaunchErrorQmlTests(LauncherQmlCase):
    def test_startup_uses_configured_alternative_before_system_scan(self):
        self.manager.set_setting('java.path', None)
        self.manager.set_setting('minecraft.version.enable', '26.3')
        java25 = self.directory / 'java25.exe'
        java25.touch()
        self.manager.set_setting('java.installations', [[str(java25), 'cached', [25]]])
        with patch('core.java_runtime.JavaPathFinder._get_java_version', return_value=('25', (25, 0, 1))), \
                patch.object(self.window, 'load_java_path') as scan, \
                patch.object(self.window.java_runtime_full, 'exec') as prompt:
            # The fixture disables the startup timer's callback; call the original explicitly.
            from windows.main_window import MinecraftLauncher
            self.patches[2].stop()
            MinecraftLauncher.minecraft_not_java_runtime(self.window)
        scan.assert_not_called()
        prompt.assert_not_called()

    def test_java_failure_has_actionable_qml_dialog_and_does_not_duplicate_on_exit(self):
        self.window.minecraft_java_required('26.3', 25, '当前 Java：21\n当前路径：C:/Java21/bin/javaw.exe')
        dialog = self.window._launch_error_dialog
        self.pump()
        self.assertTrue(dialog.isVisible())
        self.assertIn('26.3', dialog.controller.message)
        self.assertIn('Java 25', dialog.controller.message)
        self.assertIn('Java21', dialog.controller.detail)
        self.assertEqual(dialog.controller.actions, ['下载 Java', 'Java 设置', '关闭'])
        self.snapshot('java-25-required', dialog)
        self.window.minecraft_handle_stopped(1)
        self.assertIs(self.window._launch_error_dialog, dialog)
        self.assertEqual(dialog.controller.title, '缺少适合的 Java')
        with patch('windows.main_window.webbrowser.open') as browser:
            dialog.controller.action('下载 Java')
        self.assertIn('version=25', browser.call_args.args[0])
        self.window.minecraft_java_required('26.3', 25, 'Java 21')
        dialog.controller.action('Java 设置')
        self.pump()
        self.assertTrue(self.window.settings_page.java_page.isVisible())
        self.assert_no_qml_errors()

    def test_general_launch_errors_and_unexpected_exits_are_visible(self):
        self.window.minecraft_handle_error('测试：找不到客户端 JAR')
        dialog = self.window._launch_error_dialog
        self.assertTrue(dialog.isVisible())
        self.assertIn('JAR', dialog.controller.message)
        dialog.accept()
        self.window._launch_error_reported = False
        self.window.minecraft_handle_stopped(42)
        self.assertTrue(dialog.isVisible())
        self.assertIn('42', dialog.controller.message)
        self.assertEqual(dialog.controller.actions, ['查看日志', '关闭'])
        self.assert_no_qml_errors()
