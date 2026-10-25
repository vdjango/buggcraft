import hashlib
import base64
import io
import json
import os
from pathlib import Path
import tempfile
import subprocess
import sys
import time
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
    @unittest.skipUnless(os.name == 'nt', 'Real Windows updater process integration')
    def test_background_helper_survives_creator_exit_replaces_and_restarts(self):
        compiler = Path(os.environ['WINDIR']) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
        if not compiler.is_file():
            self.skipTest('.NET Framework C# compiler unavailable')
        with tempfile.TemporaryDirectory(prefix='launcher restart ') as directory:
            root = Path(directory)
            marker, source, target = root / 'restarted.txt', root / 'new.exe', root / 'launcher.exe'
            handshake = root / '.buggcraft-update-ready-probe'
            fixture = root / 'RestartProbe.cs'
            fixture.write_text('using System; using System.IO; class Program { [STAThread] static void Main() {'
                               'File.WriteAllText(@"' + str(marker).replace('"', '""') + '", "restarted");'
                               'File.WriteAllText(Environment.GetEnvironmentVariable("BUGGCRAFT_UPDATE_HANDSHAKE"), "ready"); } }')
            result = subprocess.run([str(compiler), '/nologo', '/target:winexe', '/out:' + str(source), str(fixture)],
                                    capture_output=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertEqual(result.returncode, 0, result.stdout)
            expected = source.read_bytes()
            target.write_bytes(b'old launcher')
            creator = root / 'creator.py'
            creator.write_text('import os,sys\nfrom pathlib import Path\n'
                               'sys.path.insert(0,sys.argv[1])\n'
                               'from core.update_client import _spawn_windows_replacement\n'
                               'os.environ["BUGGCRAFT_UPDATE_HANDSHAKE"] = ""\n'
                               '_spawn_windows_replacement(Path(sys.argv[2]),Path(sys.argv[3]),os.getpid())\n')
            env = dict(os.environ, NUITKA_ONEFILE_PARENT='')
            subprocess.run([sys.executable, str(creator), str(Path(update_client.__file__).resolve().parents[1]),
                            str(source), str(target)], env=env, check=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
            for _ in range(150):
                if marker.exists() and not list(root.glob('*.backup-*')):
                    break
                time.sleep(.1)
            self.assertTrue(marker.exists(), 'The background helper did not replace and restart the executable')
            self.assertEqual(target.read_bytes(), expected)
            for _ in range(50):
                if not list(root.glob('*.backup-*')):
                    break
                time.sleep(.1)
            self.assertFalse(list(root.glob('*.backup-*')))

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
        self.assertEqual(Path(payload['handshake']).resolve().parent, Path('launcher.exe').resolve().parent)
        self.assertFalse(any(key.startswith('NUITKA_') for key in kwargs['env']))
        self.assertIn('Move-Item -LiteralPath $backup', script)
        self.assertIn('BUGGCRAFT_UPDATE_HANDSHAKE', script)
        self.assertIn('BUGGCRAFT_UPDATE_INSTALLED', script)

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
                start = "$started=Start-Process -FilePath $d.target -WorkingDirectory (Split-Path -LiteralPath $d.target) -PassThru;"
                self.assertIn(start, script)
                if failing:
                    replacement = "throw 'simulated restart failure';"
                else:
                    handshake = json.loads(base64.b64decode(
                        script.split("FromBase64String('", 1)[1].split("'", 1)[0]))['handshake']
                    replacement = "'restarted' | Set-Content -LiteralPath '" + str(marker).replace("'", "''") + "';" + \
                                  "'ready' | Set-Content -LiteralPath '" + handshake.replace("'", "''") + "';"
                script = script.replace(start, replacement)
                command[-1] = base64.b64encode(script.encode('utf-16le')).decode('ascii')
                result = subprocess.run(command, timeout=15, capture_output=True,
                                         creationflags=subprocess.CREATE_NO_WINDOW)
                log = root / 'launcher.exe.update-error.log'
                self.assertEqual(result.returncode, 0,
                                 log.read_text(encoding='utf-8-sig') if log.exists() else
                                 result.stdout.decode(errors='replace') + result.stderr.decode(errors='replace'))
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
        self.assertEqual(update_client.platform_id('Linux', 'aarch64'), 'linux-arm64')
        self.assertEqual(update_client.platform_id('Linux', 'arm64'), 'linux-arm64')

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
