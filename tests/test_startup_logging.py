"""Startup diagnostics must survive failures before GUI imports."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class StartupLoggingTests(unittest.TestCase):
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
