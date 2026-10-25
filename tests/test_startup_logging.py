"""Startup diagnostics must survive failures before GUI imports."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class StartupLoggingTests(unittest.TestCase):
    def test_packaged_startup_schedules_update_check_with_selected_channel(self):
        source = Path(__file__).resolve().parents[1] / 'src/buggcraft'
        with tempfile.TemporaryDirectory(prefix='buggcraft-update-startup-') as temporary:
            env = dict(os.environ, PYTHONPATH=str(source),
                       BUGGCRAFT_LOG_DIR=temporary, QT_QPA_PLATFORM='offscreen')
            code = '''import runpy, sys
from pathlib import Path
from unittest.mock import Mock, patch
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QWidget
import config.settings as settings
import core.update_client as updates
import ui.launcher_updates as update_ui
root = Path(sys.argv[1])
(root / 'app-version.txt').write_text('1.2.3-rc.1', encoding='ascii')
with patch.object(settings, 'get_conf_or_cache_manager', return_value=('test', str(root))):
    module = runpy.run_module('main', run_name='update_startup_probe')
schedule = module['_schedule_launcher_update_checks']
schedule.__globals__.update(IS_PACKAGED=True, RESOURCE_DIR=root)
app = QApplication([])
for setting, channel in [('stable', 'stable'), ('development', 'beta')]:
    window = QWidget()
    manager = Mock()
    manager.get_setting.return_value = setting
    with patch.object(settings, '_settings_manager_instance', manager), \
            patch.object(update_ui, 'check_for_update', return_value=None) as check:
        schedule(window, app)
        assert window._update_check_timer.isActive()
        assert window._update_check_timer.interval() == 4 * 60 * 60 * 1000
        assert window.launcher_updates.startup_timer.interval() == 10000
        window.launcher_updates.startup_timer.timeout.emit()
        worker, = window._update_workers
        assert worker.wait(5000), 'Update worker did not finish'
        app.processEvents()
        check.assert_called_once_with('1.2.3-rc.1', channel)
        assert window._update_workers == []
        assert '1.2.3-rc.1' in window.launcher_updates.status
    window._update_check_timer.stop()
    window.deleteLater()
app.processEvents()
'''
            run = subprocess.run([sys.executable, '-c', code, temporary], env=env,
                                 cwd=temporary, capture_output=True, timeout=30)
            self.assertEqual(run.returncode, 0,
                             (run.stdout + run.stderr).decode('utf-8', errors='replace'))

    def test_early_import_failure_is_logged_in_selected_directory_and_retained(self):
        source = Path(__file__).resolve().parents[1] / 'src/buggcraft'
        with tempfile.TemporaryDirectory(prefix='buggcraft-diagnostics-') as temporary:
            root = Path(temporary)
            logs, working = root / 'logs', root / 'unrelated-working-directory'
            working.mkdir()
            env = dict(os.environ, PYTHONPATH=str(source), BUGGCRAFT_LOG_DIR=str(logs))
            code = '''import importlib.abc, runpy, sys
class MissingGui(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'PySide6':
            raise ImportError('simulated missing GUI dependency')
sys.meta_path.insert(0, MissingGui())
runpy.run_module('main', run_name='startup_logging_probe')
'''
            for attempt in range(2):
                run = subprocess.run([sys.executable, '-c', code], env=env, cwd=working,
                                     capture_output=True, timeout=15)
                self.assertNotEqual(run.returncode, 0)
                log = (logs / 'buggcraft.log').read_text(encoding='utf-8')
                self.assertEqual(log.count('Startup diagnostics:'), attempt + 1)
                self.assertEqual(log.count('Unhandled exception'), attempt + 1)
                self.assertIn('simulated missing GUI dependency', log)
                self.assertIn('architecture=', log)
                self.assertIn('CPU_count=', log)
                self.assertTrue((logs / 'buggcraft-crash.log').is_file())
            self.assertFalse((working / 'buggcraft.log').exists())


if __name__ == '__main__':
    unittest.main()
