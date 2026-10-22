"""Font selection and release exclusions without bundled font files."""
import importlib.util
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/buggcraft'))

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication
from ui.fonts import system_font

spec = importlib.util.spec_from_file_location('font_build', ROOT / 'build.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


class SystemFontTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_system_font_preserves_application_family_and_requested_style(self):
        original = self.app.font()
        replacement = QFont(original)
        replacement.setFamily('sans-serif')
        try:
            self.app.setFont(replacement)
            with patch('PySide6.QtGui.QFontDatabase.addApplicationFont',
                       side_effect=AssertionError('Must not load bundled fonts')):
                font = system_font(13, QFont.Weight.Bold)
            self.assertEqual(font.family(), self.app.font().family())
            self.assertEqual(font.pointSize(), 13)
            self.assertEqual(font.weight(), QFont.Weight.Bold)
        finally:
            self.app.setFont(original)

    def test_releases_exclude_fonts_on_windows_and_macos(self):
        for platform in ('Windows', 'Darwin'):
            with self.subTest(platform=platform), \
                    patch.object(build.platform, 'system', return_value=platform), \
                    patch.object(build, 'qml_exclusions', return_value=([], [])):
                command = build.make_command()
                self.assertIn('--noinclude-data-files=resources/fonts/*', command)


if __name__ == '__main__':
    unittest.main()
