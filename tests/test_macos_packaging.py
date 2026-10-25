"""Platform build paths and bundle validation without a macOS build host."""
import importlib.util
import json
import plistlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('macos_build', ROOT / 'build.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


class MacOSPackagingTests(unittest.TestCase):
    def test_mac_command_uses_native_bundle_and_shared_qml_dependency_scan(self):
        with patch.object(build.platform, 'system', return_value='Darwin'), \
                patch.object(build, 'qml_exclusions', return_value=(['--noinclude-dlls=PySide6/qml/QtWebEngine/*'], [])):
            command = build.make_command(output=ROOT / 'dist', jobs=3)
            with self.assertRaisesRegex(ValueError, 'standalone'):
                build.make_command(onefile=True)
        self.assertIn('--macos-create-app-bundle', command)
        self.assertIn('--output-filename=Buggcraft', command)
        self.assertIn('--noinclude-dlls=PySide6/qml/QtWebEngine/*', command)
        self.assertFalse(any('--windows-' in arg for arg in command))

    def test_bundle_validation_precedes_archive_and_manifest_uses_actual_architecture(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            bundle = output / 'main.app'
            (bundle / 'Contents/MacOS').mkdir(parents=True)
            (bundle / 'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleExecutable': 'Buggcraft'}))
            with self.assertRaises(FileNotFoundError):
                build.package_macos(output)
            (bundle / 'Contents/MacOS/Buggcraft').write_bytes(b'native binary')
            calls = []
            def run(command, **kwargs):
                calls.append(command)
                if command[0] == '/usr/bin/ditto':
                    Path(command[-1]).write_bytes(b'archive with preserved symlinks')
            with patch.object(build.subprocess, 'run', side_effect=run), \
                    patch.object(build.platform, 'system', return_value='Darwin'), \
                    patch.object(build.platform, 'machine', return_value='arm64'):
                manifest = build.package_macos(output)
            self.assertEqual(calls[0][:2], ['/usr/bin/codesign', '--verify'])
            self.assertIn('--keepParent', calls[1])
            self.assertEqual(manifest['platform'], 'macos-arm64')
            self.assertEqual(manifest['entrypoint'], 'main.app/Contents/MacOS/Buggcraft')
            self.assertFalse(manifest['notarized'])
            self.assertEqual(json.loads((output / 'release.json').read_text()), manifest)


if __name__ == '__main__':
    unittest.main()
