"""Native discovery must follow the installed launcher, never its cwd or Qt."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from hookup import native_library
from hookup import native_routes


class NativeLibraryPathTests(unittest.TestCase):
    def test_shallow_portable_path_does_not_assume_source_checkout_depth(self):
        root = Path(Path.cwd().anchor)
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(native_library, '__file__', str(root / 'hookup/native_library.py')), \
                patch.object(native_routes, '__file__', str(root / 'hookup/native_routes.py')), \
                patch.object(sys, 'executable', str(root / 'Buggcraft.exe')):
            self.assertIsNone(native_library.library_path())
            self.assertIsNone(native_routes.executable())
        with tempfile.TemporaryDirectory() as temporary:
            library = Path(temporary) / 'native/bin/buggcraft_bridge.dll'
            library.parent.mkdir(parents=True)
            library.touch()
            with patch.object(native_library, '__file__', str(root / 'hookup/native_library.py')):
                with self.assertRaises(FileNotFoundError):
                    native_library.load_library(library)

    def test_installed_launcher_in_unicode_directory_precedes_developer_build(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / '中文 启动器'
            name = 'buggcraft_bridge.dll' if os.name == 'nt' else (
                'libbuggcraft_bridge.dylib' if sys.platform == 'darwin' else 'libbuggcraft_bridge.so')
            library = root / 'native' / ('bin' if os.name == 'nt' else 'lib') / name
            library.parent.mkdir(parents=True)
            library.write_bytes(b'packaged')
            with patch.dict(os.environ, {}, clear=True), patch.object(sys, 'executable', str(root / 'launcher')):
                self.assertEqual(native_library.library_path(), library.resolve())

    def test_binding_is_loaded_from_same_install_tree_with_absolute_library_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / '中文 目录' / 'native'
            library = root / 'lib' / 'libbuggcraft_bridge.so'
            library.parent.mkdir(parents=True)
            library.touch()
            binding = root / 'share/buggcraft-native/python/buggcraft_bridge.py'
            binding.parent.mkdir(parents=True)
            binding.write_text('class Bridge:\n    def __init__(self, path): self.path = path\n')
            loaded = native_library.load_library(library)
            self.assertEqual(loaded.path, library.resolve())

    def test_explicit_absolute_override_does_not_depend_on_working_directory(self):
        path = (Path(tempfile.gettempdir()) / '中文 库' / 'bridge.dll').resolve()
        with patch.dict(os.environ, BUGGCRAFT_BRIDGE_LIBRARY=str(path)):
            self.assertEqual(native_library.library_path(), path)
