"""Qt must load from the shipped bundle without a developer Qt installation."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'src/buggcraft'
sys.path.insert(0, str(SOURCE))
from qt_runtime import setup_qt_environment, configure_quick_renderer
from PySide6.QtCore import QLibraryInfo


class QtRuntimeTests(unittest.TestCase):
    def test_windows_raster_backend_does_not_override_an_explicit_backend(self):
        with patch('qt_runtime.platform.system', return_value='Windows'), \
                patch.dict(os.environ, {}, clear=True):
            configure_quick_renderer()
            self.assertEqual(os.environ['QT_QUICK_BACKEND'], 'software')
            os.environ['QT_QUICK_BACKEND'] = 'rhi'
            configure_quick_renderer()
            self.assertEqual(os.environ['QT_QUICK_BACKEND'], 'rhi')
        with patch('qt_runtime.platform.system', return_value='Darwin'), \
                patch.dict(os.environ, {}, clear=True):
            configure_quick_renderer()
            self.assertNotIn('QT_QUICK_BACKEND', os.environ)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='buggcraft-qt-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_packaged_runtime_does_not_borrow_plugins_from_developer_install(self):
        # Real host Qt exists, while the simulated downloaded bundle is empty.
        self.assertTrue(Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath)).is_dir())
        with patch.dict(os.environ, {}, clear=False):
            self.assertFalse(setup_qt_environment(self.root, self.root / 'missing', packaged=True))

    @unittest.skipUnless(os.name == 'nt', 'Exercises the Windows qwindows platform plugin')
    def test_nuitka_plugin_layout_starts_a_real_windows_application(self):
        host_plugins = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath))
        plugin_root = self.root / 'PySide6/qt-plugins'
        (plugin_root / 'platforms').mkdir(parents=True)
        shutil.copy2(host_plugins / 'platforms/qwindows.dll', plugin_root / 'platforms/qwindows.dll')
        env = dict(os.environ, PYTHONPATH=str(SOURCE),
                   QT_PLUGIN_PATH=str(self.root / 'stale'),
                   QT_QPA_PLATFORM_PLUGIN_PATH=str(self.root / 'stale/platforms'),
                   QT_QPA_PLATFORM='windows')
        code = '''import json, os, sys
from pathlib import Path
from qt_runtime import setup_qt_environment
root = Path(sys.argv[1])
assert setup_qt_environment(root, root / 'missing', packaged=True)
from PySide6.QtWidgets import QApplication, QWidget
app = QApplication([])
window = QWidget()
window.setWindowTitle('Qt runtime verification')
window.show()
app.processEvents()
assert window.isVisible()
window.close()
print(json.dumps({'plugins': os.environ['QT_PLUGIN_PATH'],
                  'platforms': os.environ['QT_QPA_PLATFORM_PLUGIN_PATH']}))
'''
        result = subprocess.run([sys.executable, '-c', code, str(self.root)],
                                cwd=self.root, env=env, capture_output=True, text=True, errors='replace', timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        paths = json.loads(result.stdout)
        self.assertEqual(Path(paths['plugins']), plugin_root)
        self.assertEqual(Path(paths['platforms']), plugin_root / 'platforms')

    @unittest.skipUnless(os.name == 'nt', 'Exercises Windows plugin discovery')
    def test_alternate_bundle_layout_is_discovered(self):
        plugin_root = self.root / 'internal/qt/plugins'
        (plugin_root / 'platforms').mkdir(parents=True)
        host_plugins = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath))
        shutil.copy2(host_plugins / 'platforms/qwindows.dll', plugin_root / 'platforms/qwindows.dll')
        with patch.dict(os.environ, {}, clear=False):
            self.assertTrue(setup_qt_environment(self.root, self.root / 'missing', packaged=True))
            self.assertEqual(Path(os.environ['QT_PLUGIN_PATH']), plugin_root)


if __name__ == '__main__':
    unittest.main()
