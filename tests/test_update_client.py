import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from core import update_client


class Response:
    def __init__(self, body, url='https://download.bugg.icu/api/launcher/update'):
        self.body = body
        self.headers = {'Content-Length': str(len(body))}
        self.url = url

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def geturl(self):
        return self.url

    def read(self, size=-1):
        result, self.body = self.body[:size], self.body[size:]
        return result


class UpdateClientTests(unittest.TestCase):
    def test_semver_and_platform_targets(self):
        self.assertGreater(update_client.version_key('1.2.0'), update_client.version_key('1.2.0-rc.2'))
        self.assertGreater(update_client.version_key('1.2.0-rc.2'), update_client.version_key('1.2.0-rc.1'))
        self.assertEqual(update_client.platform_id('Windows', 'AMD64'), 'windows-x64')
        self.assertEqual(update_client.platform_id('Darwin', 'arm64'), 'macos-arm64')
        self.assertEqual(update_client.platform_id('Linux', 'aarch64'), None)

    def test_check_accepts_only_newer_trusted_release(self):
        package = b'launcher binary'
        payload = {
            'update_available': True, 'version': '1.4.0', 'platform': 'windows-x64',
            'asset': {'name': 'Buggcraft.exe', 'size': len(package),
                      'sha256': hashlib.sha256(package).hexdigest(),
                      'url': 'https://download.bugg.icu/api/launcher/assets/1.4.0/Buggcraft.exe'},
        }
        with mock.patch.object(update_client.urllib.request, 'urlopen',
                               return_value=Response(json.dumps(payload).encode())):
            result = update_client.check_for_update('1.3.0', target='windows-x64')
        self.assertEqual(result['version'], '1.4.0')

        payload['version'] = '1.3.0'
        with mock.patch.object(update_client.urllib.request, 'urlopen',
                               return_value=Response(json.dumps(payload).encode())):
            self.assertIsNone(update_client.check_for_update('1.3.0', target='windows-x64'))

        payload['version'] = '1.4.0'
        payload['asset']['url'] = 'https://example.invalid/installer.exe'
        with mock.patch.object(update_client.urllib.request, 'urlopen',
                               return_value=Response(json.dumps(payload).encode())):
            with self.assertRaises(ValueError):
                update_client.check_for_update('1.3.0', target='windows-x64')

    def test_download_verifies_size_hash_and_removes_bad_file(self):
        package = b'verified update bytes'
        update = {'asset': {'name': 'Buggcraft.exe', 'size': len(package),
                            'sha256': hashlib.sha256(package).hexdigest(),
                            'url': 'https://download.bugg.icu/api/launcher/assets/1.4.0/Buggcraft.exe'}}
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(update_client.urllib.request, 'urlopen',
                                   return_value=Response(package, 'https://download.bugg.icu/api/launcher/assets')):
                destination = update_client.download_update(update, directory)
            self.assertEqual(Path(destination).read_bytes(), package)

            update['asset']['sha256'] = '0' * 64
            with mock.patch.object(update_client.urllib.request, 'urlopen',
                                   return_value=Response(package, 'https://download.bugg.icu/api/launcher/assets')):
                with self.assertRaisesRegex(ValueError, 'SHA-256'):
                    update_client.download_update(update, directory)
            self.assertEqual([path.name for path in Path(directory).iterdir()], [destination.name])

    def test_macos_archive_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / 'bad.zip'
            import zipfile
            with zipfile.ZipFile(archive, 'w') as output:
                output.writestr('../outside', 'bad')
                output.writestr('Buggcraft.app/Contents/Info.plist', 'bad')
            with self.assertRaisesRegex(ValueError, 'unsafe path'):
                update_client._spawn_macos_replacement(archive, Path(directory) / 'Buggcraft.app', 1)


if __name__ == '__main__':
    unittest.main()
