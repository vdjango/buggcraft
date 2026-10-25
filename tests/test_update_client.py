import hashlib
import base64
import io
import json
import os
from pathlib import Path
import tempfile
import subprocess
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
    def test_windows_replacement_waits_onefile_parent_and_clears_bootstrap_environment(self):
        with mock.patch.dict(os.environ, {'NUITKA_ONEFILE_PARENT': '123', 'NUITKA_ONEFILE_START': 'old'}), \
                mock.patch('psutil.Process') as process, \
                mock.patch.object(update_client.subprocess, 'Popen') as spawn:
            process.return_value.ppid.return_value = 123
            update_client._spawn_windows_replacement(Path('new.exe'), Path('launcher.exe'), 456)
        args, kwargs = spawn.call_args
        script = base64.b64decode(args[0][-1]).decode('utf-16le')
        encoded = script.split("FromBase64String('", 1)[1].split("'", 1)[0]
        payload = json.loads(base64.b64decode(encoded))
        self.assertEqual(payload['pids'], [456, 123])
        self.assertFalse(any(key.startswith('NUITKA_') for key in kwargs['env']))
        self.assertIn('Move-Item -LiteralPath $backup', script)

    @unittest.skipUnless(os.name == 'nt', 'Windows PowerShell replacement integration')
    def test_windows_replacement_script_replaces_and_restores_on_restart_failure(self):
        with tempfile.TemporaryDirectory(prefix='launcher replacement ') as directory:
            root = Path(directory)
            target, source, marker = root / 'launcher.exe', root / 'new.exe', root / 'restarted.txt'
            for failing in (False, True):
                target.write_bytes(b'original executable')
                source.write_bytes(b'verified new executable')
                with mock.patch.dict(os.environ, {'NUITKA_ONEFILE_PARENT': ''}), \
                        mock.patch.object(update_client.subprocess, 'Popen') as spawn:
                    update_client._spawn_windows_replacement(source, target, 2147483647)
                command = spawn.call_args.args[0]
                script = base64.b64decode(command[-1]).decode('utf-16le')
                start = 'Start-Process -FilePath $d.target -WorkingDirectory (Split-Path -LiteralPath $d.target);'
                self.assertIn(start, script)
                replacement = "throw 'simulated restart failure';" if failing else "'restarted' | Set-Content -LiteralPath '" + str(marker).replace("'", "''") + "';"
                script = script.replace(start, replacement)
                command[-1] = base64.b64encode(script.encode('utf-16le')).decode('ascii')
                subprocess.run(command, check=True, timeout=15, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
                self.assertEqual(target.read_bytes(), b'original executable' if failing else b'verified new executable')
                self.assertFalse(list(root.glob('*.backup-*')))
                if failing:
                    self.assertIn('simulated restart failure', (root / 'launcher.exe.update-error.log').read_text(encoding='utf-8-sig'))
                else:
                    self.assertTrue(marker.exists())

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
