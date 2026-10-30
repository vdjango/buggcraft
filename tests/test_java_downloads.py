"""Java catalogue identity, checksums, archive extraction and cancellation."""
import hashlib
import io
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

from core.java_downloads import JavaPackage, _package, _temurin, catalogue, install, register


class JavaDownloadTests(unittest.TestCase):
    def test_first_download_sets_auto_java_path_and_preserves_explicit_selection(self):
        from config.settings import SettingsManager

        with tempfile.TemporaryDirectory() as directory:
            settings = SettingsManager(Path(directory) / 'config')
            first = str(Path(directory) / 'java-21.exe')
            second = str(Path(directory) / 'java-17.exe')
            settings.set_setting('java.path', None)
            register(settings, (first, 'Java 21', [21, 0, 1]))
            self.assertEqual(settings.get_version_setting('java.path'), first)
            self.assertEqual(SettingsManager(Path(directory) / 'config').get_setting('java.path'), first)
            settings.set_version_setting('java.name', '自定义 Java 路径')
            register(settings, (second, 'Java 17', [17, 0, 1]))
            self.assertEqual(settings.get_version_setting('java.path'), first)

    def test_tuna_package_uses_catalogued_sha256_and_official_fallback(self):
        payload = [{'release_type': 'ga', 'version': {'major': 25, 'semver': '25.0.2+1'},
                    'binary': {'architecture': 'x64', 'os': 'windows', 'image_type': 'jre',
                               'package': {'link': 'https://github.com/adoptium/test.zip',
                                           'name': 'temurin25.zip', 'checksum': 'a' * 64, 'size': 12}}}]
        with patch('core.java_downloads._json', return_value=payload):
            package, = _temurin(25, 'windows', 'x64', 'jre', '自动（国内优先）')
        self.assertEqual(package.checksum, 'a' * 64)
        self.assertIn('mirrors.tuna.tsinghua.edu.cn', package.urls[0])
        self.assertEqual(package.urls[1], 'https://github.com/adoptium/test.zip')

    def test_package_rejects_http_urls_unverified_hash_and_oversize(self):
        cases = [
            dict(urls=['http://example.test/jre.zip']),
            dict(checksum='not-a-sha256'),
            dict(size=512 * 1024 ** 2 + 1),
            dict(name='../jre.zip'),
        ]
        base = dict(vendor='Test', major=21, version='21.0.1', system='windows',
                    architecture='x64', kind='jre', name='jre.zip',
                    checksum='a' * 64, size=0, urls=['https://cdn.example.test/jre.zip'])
        for override in cases:
            with self.subTest(override=override), self.assertRaises(ValueError):
                _package(**(base | override))

    def test_download_verifies_checksum_and_java_major_before_publishing(self):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w') as value:
            value.writestr('jre/bin/' + ('java.exe' if os.name == 'nt' else 'java'), b'java executable fixture')
        payload = archive.getvalue()
        package = JavaPackage('Test', 25, '25.0.1', 'windows', 'x64', 'jre',
                              'jre.zip', hashlib.sha256(payload).hexdigest(), len(payload),
                              ('https://cdn.example.test/jre.zip',))

        class Response:
            headers = {'Content-Length': str(len(payload))}
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def raise_for_status(self): pass
            def iter_content(self, chunk_size): yield payload

        with tempfile.TemporaryDirectory() as directory, \
                patch('core.java_downloads.java_platform', return_value=('windows', 'x64')), \
                patch('core.java_downloads.requests.get', return_value=Response()) as request, \
                patch('core.java_downloads.JavaPathFinder._get_java_version',
                      return_value=('openjdk version "25.0.1"', (25, 0, 1))):
            rename = Path.rename
            attempts = []
            def transient_lock(path, target):
                attempts.append(path)
                if os.name == 'nt' and len(attempts) < 3:
                    raise PermissionError('Windows scanner fixture')
                return rename(path, target)
            with patch.object(Path, 'rename', transient_lock):
                entry = install(package, directory)
            self.assertTrue(Path(entry[0]).is_file())
            self.assertEqual(entry[2][0], 25)
            self.assertTrue((Path(directory) / package.checksum / 'buggcraft-runtime.json').is_file())
            downloaded = request.call_count
            with patch('core.java_downloads.requests.get', side_effect=AssertionError('Cached Java was downloaded again')):
                reused = install(package, directory)
            self.assertEqual(reused, entry)
            self.assertEqual(Path(reused[0]).read_bytes(), b'java executable fixture')
            self.assertEqual(downloaded, 1)

    def test_cancelled_download_does_not_request_or_publish_files(self):
        package = JavaPackage('Test', 25, '25.0.1', 'windows', 'x64', 'jre',
                              'jre.zip', 'a' * 64, 1, ('https://cdn.example.test/jre.zip',))
        cancel = threading.Event()
        cancel.set()
        with tempfile.TemporaryDirectory() as directory, \
                patch('core.java_downloads.java_platform', return_value=('windows', 'x64')), \
                patch('core.java_downloads.requests.get') as request:
            with self.assertRaises(InterruptedError):
                install(package, directory, cancel=cancel)
            request.assert_not_called()
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_failed_catalogue_still_offers_independent_provider(self):
        package = JavaPackage('Azul Zulu', 25, '25.0.1', 'windows', 'x64', 'jre',
                              'jre.zip', 'a' * 64, 1, ('https://cdn.azul.com/jre.zip',))
        with patch('core.java_downloads.java_platform', return_value=('windows', 'x64')), \
                patch('core.java_downloads._temurin', side_effect=RuntimeError('source offline')), \
                patch('core.java_downloads._azul', return_value=[package]):
            self.assertEqual(catalogue(25), [package])

    def test_corrupt_or_unsafe_archive_is_never_published(self):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w') as value:
            value.writestr('../outside.txt', 'must never extract')
        payload = archive.getvalue()

        class Response:
            headers = {}
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def raise_for_status(self): pass
            def iter_content(self, chunk_size): yield payload

        for checksum in ('a' * 64, hashlib.sha256(payload).hexdigest()):
            package = JavaPackage('Test', 25, '25.0.1', 'windows', 'x64', 'jre',
                                  'jre.zip', checksum, len(payload), ('https://example.test/jre.zip',))
            with self.subTest(checksum=checksum), tempfile.TemporaryDirectory() as directory, \
                    patch('core.java_downloads.java_platform', return_value=('windows', 'x64')), \
                    patch('core.java_downloads.requests.get', return_value=Response()), \
                    patch('core.java_downloads._probe') as probe:
                with self.assertRaises((ValueError, RuntimeError)):
                    install(package, directory)
                self.assertEqual(list(Path(directory).iterdir()), [])
                probe.assert_not_called()
