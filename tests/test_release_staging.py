"""Check that release downloads match the built package, excluding build logs."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('stage_release', ROOT / 'scripts/stage_release.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseStagingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.output = Path(temporary.name)

    def package(self, platform):
        archive = self.output / release.ARCHIVES[platform]
        with zipfile.ZipFile(archive, 'w') as bundle:
            bundle.writestr('app/runtime.txt', 'packaged runtime')
        manifest = dict(platform=platform, archive=archive.name, size=archive.stat().st_size,
                        sha256=hashlib.sha256(archive.read_bytes()).hexdigest())
        (self.output / 'release.json').write_text(json.dumps(manifest), encoding='utf-8')
        (self.output / 'build.log').write_text('compiler diagnostics', encoding='utf-8')
        return archive

    def test_windows_collects_offline_pair_diagnostics_and_verifiable_checksums(self):
        self.package('windows-x64')
        (self.output / 'Buggcraft-Setup.exe').write_bytes(b'compiled installer')
        (self.output / 'signing-status.json').write_text('{"signed": false}', encoding='utf-8')
        destination = release.stage(self.output, 'windows-x64', ROOT)
        self.assertEqual({p.name for p in destination.iterdir()}, {
            'Buggcraft-runtime-windows-x64.zip', 'Buggcraft-Setup.exe',
            'release-windows-x64.json', 'signing-status-windows-x64.json',
            'collect-launcher-diagnostics.ps1', 'TESTING.md', 'SHA256SUMS-windows-x64.txt'})
        for line in (destination / 'SHA256SUMS-windows-x64.txt').read_text().splitlines():
            expected, name = line.split('  ', 1)
            self.assertEqual(hashlib.sha256((destination / name).read_bytes()).hexdigest(), expected)

    def test_each_mac_architecture_has_distinct_download_names(self):
        for platform in ('macos-x86_64', 'macos-arm64'):
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as temporary:
                self.output = Path(temporary)
                archive = self.package(platform)
                destination = release.stage(self.output, platform, ROOT)
                self.assertEqual({p.name for p in destination.iterdir()}, {
                    archive.name, 'release-' + platform + '.json', 'TESTING.md',
                    'SHA256SUMS-' + platform + '.txt'})

    def test_corrupt_archive_is_rejected_before_creating_download_directory(self):
        archive = self.package('macos-arm64')
        archive.write_bytes(b'corrupted runtime')
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            release.stage(self.output, 'macos-arm64', ROOT)
        self.assertFalse((self.output / 'release').exists())

    def test_wrong_architecture_or_archive_path_cannot_be_published(self):
        self.package('macos-arm64')
        with self.assertRaisesRegex(ValueError, 'platform or archive'):
            release.stage(self.output, 'macos-x86_64', ROOT)
        manifest = json.loads((self.output / 'release.json').read_text())
        manifest['archive'] = '../outside.zip'
        (self.output / 'release.json').write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'platform or archive'):
            release.stage(self.output, 'macos-arm64', ROOT)

    def test_missing_installer_and_stale_destination_are_rejected(self):
        self.package('windows-x64')
        with self.assertRaises(FileNotFoundError):
            release.stage(self.output, 'windows-x64', ROOT)
        self.assertFalse((self.output / 'release').exists())
        self.package('macos-arm64')
        (self.output / 'release').mkdir()
        (self.output / 'release/old.exe').write_bytes(b'old')
        with self.assertRaises(FileExistsError):
            release.stage(self.output, 'macos-arm64', ROOT)
