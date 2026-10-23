"""Keep the packaged bridge's libraries and relative paths usable at runtime."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('launcher_build', ROOT / 'build.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


class NativeBridgeStagingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.package = self.root / 'install'
        self.runtime = self.root / 'runtime'
        self.name = 'buggcraft-bridge.exe' if os.name == 'nt' else 'buggcraft-bridge'
        for folder in ('bin', 'lib', 'share/licenses'):
            (self.package / folder).mkdir(parents=True)
        (self.package / 'bin' / self.name).write_bytes(b'native bridge')

    def test_bridge_dependencies_and_licenses_keep_relative_paths_and_hashes(self):
        (self.package / 'bin/ssh.dll').write_bytes(b'Windows dependency')
        (self.package / 'lib/libssh.dylib').write_bytes(b'macOS dependency')
        (self.package / 'share/licenses/ssh.txt').write_text('license')
        (self.package / 'bin/buggcraft-core.exe').write_bytes(b'server only')
        (self.package / 'bin/buggcraft-core').write_bytes(b'server only')
        build.stage_native_bridge(self.runtime, self.package)
        staged = self.runtime / 'native'
        manifest = json.loads((staged / 'manifest.json').read_text())
        self.assertEqual(manifest['schema'], 1)
        self.assertEqual(set(manifest['files']), {
            'bin/' + self.name, 'bin/ssh.dll', 'lib/libssh.dylib', 'share/licenses/ssh.txt'})
        for relative, digest in manifest['files'].items():
            self.assertEqual(hashlib.sha256((staged / relative).read_bytes()).hexdigest(), digest)

    def test_incomplete_install_cannot_erase_existing_packaged_bridge(self):
        staged = self.runtime / 'native'
        staged.mkdir(parents=True)
        (staged / 'existing').write_bytes(b'keep')
        (self.package / 'bin' / self.name).unlink()
        with self.assertRaises(FileNotFoundError):
            build.stage_native_bridge(self.runtime, self.package)
        self.assertEqual((staged / 'existing').read_bytes(), b'keep')

    def test_replacement_removes_stale_native_files_and_preserves_launcher(self):
        staged = self.runtime / 'native'
        staged.mkdir(parents=True)
        (staged / 'old-library.dll').write_bytes(b'stale')
        (self.runtime / 'launcher.data').write_bytes(b'launcher')
        build.stage_native_bridge(self.runtime, self.package)
        self.assertFalse((staged / 'old-library.dll').exists())
        self.assertEqual((self.runtime / 'launcher.data').read_bytes(), b'launcher')
        self.assertTrue((staged / 'bin' / self.name).is_file())

    def test_library_only_install_preserves_binding_and_relative_paths(self):
        (self.package / 'bin' / self.name).unlink()
        name = 'buggcraft_bridge.dll' if os.name == 'nt' else (
            'libbuggcraft_bridge.dylib' if sys.platform == 'darwin' else 'libbuggcraft_bridge.so')
        folder = 'bin' if os.name == 'nt' else 'lib'
        (self.package / folder / name).write_bytes(b'library')
        binding = self.package / 'share/buggcraft-native/python/buggcraft_bridge.py'
        binding.parent.mkdir(parents=True)
        binding.write_text('# ffi')
        build.stage_native_bridge(self.runtime, self.package)
        self.assertTrue((self.runtime / 'native' / folder / name).is_file())
        self.assertTrue((self.runtime / 'native' / binding.relative_to(self.package)).is_file())

    def test_missing_library_binding_does_not_erase_existing_install(self):
        staged = self.runtime / 'native'
        staged.mkdir(parents=True)
        (staged / 'existing').write_bytes(b'keep')
        name = 'buggcraft_bridge.dll' if os.name == 'nt' else (
            'libbuggcraft_bridge.dylib' if sys.platform == 'darwin' else 'libbuggcraft_bridge.so')
        (self.package / 'bin' / name).write_bytes(b'library')
        with self.assertRaises(FileNotFoundError):
            build.stage_native_bridge(self.runtime, self.package)
        self.assertEqual((staged / 'existing').read_bytes(), b'keep')

    def test_source_inside_destination_cannot_be_deleted(self):
        package = self.runtime / 'native'
        (package / 'bin').mkdir(parents=True)
        executable = package / 'bin' / self.name
        executable.write_bytes(b'keep')
        with self.assertRaises(ValueError):
            build.stage_native_bridge(self.runtime, package)
        self.assertEqual(executable.read_bytes(), b'keep')
