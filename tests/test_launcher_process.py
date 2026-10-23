"""Launch-core tests use short-lived local child processes; no Java or network is needed."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / 'buggcraft'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
from PySide6.QtWidgets import QApplication
from config.settings import SettingsManager
from core.launcher import MinecraftLibLauncher


class LauncherProcessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.work = Path(self.temporary.name)
        self.root = self.work / 'minecraft'
        self.root.mkdir()
        self.manager = SettingsManager(str(self.work / 'config'))
        self.manager.set_setting('minecraft.directory.enable', str(self.root))
        self.manager.set_setting('minecraft.version.enable', 'fixture')
        self.manager.set_setting('java.path', sys.executable)
        self.manager.set_setting('memory.allocation', 3072)
        self.manager.set_setting('minecraft.auto_allocate_memory', False)
        self.record = self.work / 'launched.json'
        self.program = self.work / 'fake game.py'
        self.program.write_text(
            'import json, os, pathlib, sys\n'
            'pathlib.Path(sys.argv[1]).write_text(json.dumps({"args":sys.argv[2:],"cwd":os.getcwd()}))\n'
            'print("final child output", flush=True)\n', encoding='utf-8')
        with patch('core.launcher.get_settings_manager', return_value=self.manager):
            self.launcher = MinecraftLibLauncher(str(self.work))
        self.launcher.set_options(uuid='fixture-uuid', username='Fixture', token='fixture-token',
                                  version='fixture', width=900, height=540)
        self.addCleanup(self._cleanup_launcher)
        self.options = None

    def _cleanup_launcher(self):
        if self.launcher.process and self.launcher.process.poll() is None:
            self.launcher.process.kill()
            self.launcher.process.wait(5)
        if self.launcher.process:
            for stream in (self.launcher.process.stdin, self.launcher.process.stdout, self.launcher.process.stderr):
                if stream and not stream.closed:
                    stream.close()

    def _command(self, version, directory, options):
        self.options = options
        return [sys.executable, str(self.program), str(self.record), '--gameDir',
                options['gameDirectory'], '--accessToken', options.get('token', '')]

    def _start(self):
        with patch('core.launcher.verified_installation', return_value=True), \
                patch('core.launcher.minecraft_launcher_lib.command.get_minecraft_command', side_effect=self._command), \
                patch('core.launcher.psutil.Process'), \
                patch('core.launcher.subprocess.Popen', wraps=subprocess.Popen) as popen:
            self.launcher._start_game()
            return popen.call_args.kwargs

    def test_game_directory_cwd_and_options_track_isolation_setting(self):
        for isolated in (True, False):
            self.manager.set_setting('minecraft.isolation', isolated)
            process = self._start()
            data = self.root / 'versions/fixture' if isolated else self.root
            launch = json.loads(self.record.read_text(encoding='utf-8'))
            self.assertEqual(Path(self.options['gameDirectory']), data)
            self.assertEqual(Path(process['cwd']), data)
            # macOS reports /private/var for the /var temporary-directory alias.
            self.assertEqual(Path(launch['cwd']).resolve(), data.resolve())
            self.assertEqual(launch['args'][launch['args'].index('--gameDir') + 1], str(data))
            self.assertIn('--width', launch['args'])
            self.assertIn('--height', launch['args'])
            self.assertIn('-Xmx3072M', self.options['jvmArguments'])
            self.assertIn('soundCategory_music:0.0', (data / 'options.txt').read_text(encoding='utf-8'))
            self.assertFalse(self.launcher.running)
            self.assertIsNone(self.launcher.process)

    def test_automatic_memory_is_used_without_mutating_manual_preference(self):
        self.manager.set_setting('minecraft.auto_allocate_memory', True)
        with patch('core.launcher.AdvancedMemoryRecommender.calculate', return_value=(4096, 'unit test')):
            self._start()
        self.assertIn('-Xmx4096M', self.options['jvmArguments'])
        self.assertEqual(self.manager.get_setting('memory.allocation'), 3072)

    def test_prelaunch_command_runs_in_instance_directory_and_preserves_arguments(self):
        before = self.work / 'prelaunch.py'
        before.write_text("from pathlib import Path\nPath('prelaunch-ok').write_text('done')\n")
        self.manager.set_setting('game.launch_pre_command', f'"{sys.executable}" "{before}"')
        self.manager.set_setting('game.launch_args', '--sample "two words"')
        self.manager.set_setting('game.launch_jvm_args', '-Dfixture="two words"')
        self._start()
        data = self.root / 'versions/fixture'
        self.assertEqual((data / 'prelaunch-ok').read_text(), 'done')
        launch = json.loads(self.record.read_text(encoding='utf-8'))
        self.assertEqual(launch['args'][-2:], ['--sample', 'two words'])
        self.assertIn('-Dfixture=two words', self.options['jvmArguments'])

    def test_failed_prelaunch_command_never_starts_game(self):
        before = self.work / 'failed.py'
        before.write_text('raise SystemExit(7)\n')
        self.manager.set_setting('game.launch_pre_command', f'"{sys.executable}" "{before}"')
        with self.assertRaisesRegex(RuntimeError, '退出码 7'):
            self._start()
        self.assertFalse(self.record.exists())
        self.assertIsNone(self.launcher.process)

    def test_prelaunch_timeout_never_starts_game(self):
        self.manager.set_setting('game.launch_pre_command', 'timeout fixture')
        with patch('core.launcher.subprocess.run', side_effect=subprocess.TimeoutExpired('timeout fixture', 120)):
            with self.assertRaisesRegex(RuntimeError, '120 秒'):
                self._start()
        self.assertFalse(self.record.exists())

    def test_debug_command_redacts_secret_and_final_output_is_delivered(self):
        output = []
        self.launcher.signals.output.connect(output.append)
        process = self._start()
        if os.name == 'nt':
            self.assertTrue(process['creationflags'] & subprocess.CREATE_NO_WINDOW)
        self.assertNotIn('fixture-token', '\n'.join(output))
        self.assertIn('final child output', output)

    def test_offline_launch_always_supplies_uuid_and_token_without_changing_online_identity(self):
        from core.launch_options import offline_uuid
        self.launcher.set_options(username='Fixture', uuid=None, token=None)
        self._start()
        self.assertEqual(self.options['uuid'], offline_uuid('Fixture'))
        self.assertEqual(self.options['token'], '0')
        self.launcher.set_options(username='Fixture', uuid='existing-account-uuid', token='existing-token')
        self._start()
        self.assertEqual(self.options['uuid'], 'existing-account-uuid')
        self.assertEqual(self.options['token'], 'existing-token')

    def test_java_requirement_from_metadata_rejects_old_java_before_spawning(self):
        metadata = self.root / 'versions/fixture/fixture.json'
        metadata.parent.mkdir(parents=True)
        metadata.write_text(json.dumps({'id': 'fixture', 'javaVersion': {'majorVersion': 25}}), encoding='utf-8')
        with patch('config.javafinder.JavaPathFinder._get_java_version', return_value=('21', (21, 0, 8))):
            with self.assertRaisesRegex(ValueError, 'Java 25'):
                self._start()
        self.assertFalse(self.record.exists())
        with patch('config.javafinder.JavaPathFinder._get_java_version', return_value=('25', (25, 0, 3))):
            self._start()
        self.assertTrue(self.record.exists())

    def test_configured_java_25_is_passed_to_command_without_overwriting_selected_java(self):
        metadata = self.root / 'versions/fixture/fixture.json'
        metadata.parent.mkdir(parents=True)
        metadata.write_text(json.dumps({'javaVersion': {'majorVersion': 25}}), encoding='utf-8')
        java25 = self.work / 'java25.exe'
        java25.touch()
        self.manager.set_setting('java.installations', [[str(java25), 'cached', [25]]])
        with patch('config.javafinder.JavaPathFinder._get_java_version', side_effect=lambda path:
                   ('25', (25, 0, 1)) if path == str(java25) else ('21', (21, 0, 1))):
            self._start()
        self.assertEqual(self.options['executablePath'], str(java25))
        self.assertEqual(self.manager.get_version_setting('java.path'), sys.executable)
        self.assertTrue(self.record.exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
