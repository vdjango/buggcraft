"""Single-file builds must retain native multiplayer and portable data paths."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('onefile_build', ROOT / 'build.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


class OnefilePackagingTests(unittest.TestCase):
    def test_onefile_uses_full_native_runtime_and_versioned_archive_cache(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(build.platform, 'system', return_value='Windows'), \
                patch.object(build, 'qml_exclusions', return_value=([], [])):
            native = Path(folder)
            command = build.make_command(onefile=True, native=native)
            self.assertIn('--onefile', command)
            self.assertIn('--onefile-cache-mode=cached', command)
            self.assertIn('--onefile-as-archive', command)
            self.assertIn('--launcher-native=' + str(native.resolve()), command)
            cache = next(value for value in command if value.startswith('--onefile-tempdir-spec='))
            self.assertIn('{CACHE_DIR}/Buggcraft/', cache)
            self.assertNotIn('{TEMP}', cache)
            self.assertIn('--windows-console-mode=disable', command)
            with self.assertRaisesRegex(ValueError, 'native'):
                build.make_command(onefile=True)

    def test_native_changes_invalidate_cache_but_local_bytecode_does_not(self):
        with tempfile.TemporaryDirectory() as folder:
            native = Path(folder)
            library = native / 'bridge.dll'
            library.write_bytes(b'first native release')
            first = build.onefile_cache_tag(native)
            (native / '__pycache__').mkdir()
            (native / '__pycache__/binding.pyc').write_bytes(b'local cache')
            self.assertEqual(build.onefile_cache_tag(native), first)
            library.write_bytes(b'updated native release')
            self.assertNotEqual(build.onefile_cache_tag(native), first)

    def test_linux_payload_includes_native_runtime_without_windows_options(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(build.platform, 'system', return_value='Linux'), \
                patch.object(build, 'qml_exclusions', return_value=([], [])):
            command = build.make_command(onefile=True, native=Path(folder))
            self.assertIn('--onefile', command)
            self.assertIn('--output-filename=Buggcraft', command)
            self.assertIn('--launcher-native=' + str(Path(folder).resolve()), command)
            self.assertIn('--onefile-cache-mode=cached', command)
            self.assertFalse(any(value.startswith('--windows-') for value in command))
            with self.assertRaisesRegex(ValueError, 'native'):
                build.make_command(onefile=True)


if __name__ == '__main__':
    unittest.main()
