"""Run the compiled Windows bootstrap against real ZIPs and isolated caches."""
import hashlib
import importlib.util
import json
import os
import shutil
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('launcher_build', ROOT / 'build.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


@unittest.skipUnless(os.name == 'nt', 'Windows bootstrap requires the Windows .NET Framework compiler')
class WindowsBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='buggcraft 安装测试 ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runtime = self.root / 'main.dist'
        self.runtime.mkdir()
        (self.runtime / 'Buggcraft.exe').write_bytes(b'EXE is never executed in installer verification')
        (self.runtime / 'Qt 插件').mkdir()
        (self.runtime / 'Qt 插件/runtime.dll').write_bytes(os.urandom(4096))
        self.manifest, self.manifest_path = build.package_runtime(self.runtime, self.root, [])
        self.cache = self.root / 'cache'

    def compile(self, manifest=None):
        if manifest is not None:
            self.manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
        build.build_bootstrap(self.manifest_path, self.root)

    def launch_installer(self, *args, **kwargs):
        try:
            return subprocess.run(*args, **kwargs)
        except OSError as error:
            if getattr(error, 'winerror', None) == 4551:
                self.skipTest('Windows Application Control blocks the unsigned test installer (WinError 4551)')
            raise

    def run_installer(self, success=True):
        report = self.root / 'result.txt'
        env = dict(os.environ, PATH=os.environ['WINDIR'] + '\\System32')
        env.pop('PYTHONPATH', None)
        env.pop('PYTHONHOME', None)
        run = self.launch_installer([str(self.root / 'Buggcraft-Setup.exe'), '--headless', '--no-launch',
            '--runtime-root', str(self.cache), '--report', str(report)], cwd=self.root,
            env=env, timeout=20, capture_output=True)
        self.assertEqual(run.returncode, 0 if success else 1, report.read_text('utf-8-sig'))
        self.assertEqual(report.read_text('utf-8-sig') == 'verified', success)
        return self.cache / self.manifest['version']

    def test_installs_real_files_from_sidecar_and_works_offline_from_verified_cache(self):
        self.compile()
        installed = self.run_installer()
        log = (self.root / 'Buggcraft-install.log').read_text(encoding='utf-8')
        self.assertIn('OS_64bit=', log)
        self.assertIn('CPU_count=', log)
        self.assertIn('installer started', log)
        for record in self.manifest['files']:
            self.assertEqual((installed / record['path']).read_bytes(), (self.runtime / record['path']).read_bytes())
        (self.root / self.manifest['archive']).unlink()
        self.run_installer()
        self.assertLess((self.root / 'Buggcraft-Setup.exe').stat().st_size, 1_000_000)

    def test_corrupt_cached_library_is_repaired_without_touching_another_version(self):
        self.compile()
        installed = self.run_installer()
        unrelated = self.cache / 'previous-version'
        unrelated.mkdir()
        (unrelated / 'keep.txt').write_text('keep')
        (installed / 'Qt 插件/runtime.dll').write_bytes(b'corrupt')
        self.run_installer()
        self.assertEqual((installed / 'Qt 插件/runtime.dll').read_bytes(), (self.runtime / 'Qt 插件/runtime.dll').read_bytes())
        self.assertEqual((unrelated / 'keep.txt').read_text(), 'keep')

    def test_default_runtime_is_beside_installer_even_from_another_working_directory(self):
        self.compile()
        report = self.root / 'portable-result.txt'
        working = self.root / 'unrelated-working-directory'
        working.mkdir()
        run = self.launch_installer([str(self.root / 'Buggcraft-Setup.exe'), '--headless', '--no-launch',
                              '--report', str(report)], cwd=working, timeout=20, capture_output=True)
        self.assertEqual(run.returncode, 0, report.read_text('utf-8-sig'))
        installed = self.root / 'Buggcraft-runtime' / self.manifest['version']
        self.assertEqual((installed / 'Buggcraft.exe').read_bytes(),
                         (self.runtime / 'Buggcraft.exe').read_bytes())
        self.assertFalse((working / 'Buggcraft-runtime').exists())

    def test_corrupt_download_archive_does_not_install_partial_runtime(self):
        self.compile()
        archive = self.root / self.manifest['archive']
        archive.write_bytes(archive.read_bytes()[:-20])
        self.run_installer(success=False)
        self.assertFalse((self.cache / self.manifest['version']).exists())

    def test_each_file_hash_is_checked_before_activation(self):
        manifest = dict(self.manifest)
        manifest['files'] = [dict(f, sha256='0' * 64) for f in self.manifest['files']]
        self.compile(manifest)
        self.run_installer(success=False)
        self.assertFalse((self.cache / self.manifest['version']).exists())
        self.assertFalse(list(self.cache.glob('.staging-*')))

    def test_archive_extra_file_is_rejected_before_activation(self):
        archive = self.root / self.manifest['archive']
        with zipfile.ZipFile(archive, 'a') as bundle:
            bundle.writestr('../escaped.exe', b'bad')
        manifest = dict(self.manifest)
        manifest['size'] = archive.stat().st_size
        manifest['sha256'] = hashlib.sha256(archive.read_bytes()).hexdigest()
        manifest['version'] = manifest['sha256'][:16]
        self.compile(manifest)
        self.run_installer(success=False)
        self.assertFalse((self.root / 'escaped.exe').exists())
        self.assertFalse((self.cache / manifest['version']).exists())

    def test_malicious_manifest_path_is_rejected(self):
        manifest = dict(self.manifest)
        manifest['files'] = [dict(f, path='../outside.exe') if i == 1 else f
                             for i, f in enumerate(self.manifest['files'])]
        self.compile(manifest)
        self.run_installer(success=False)
        self.assertFalse((self.root / 'outside.exe').exists())

    def test_source_is_not_required_for_build_packaging(self):
        with self.assertRaises(FileNotFoundError):
            build.package_runtime(self.root / 'missing', self.root, [])

    def test_identical_runtime_reuses_content_version(self):
        another = self.root / 'repack'
        another.mkdir()
        manifest, _ = build.package_runtime(self.runtime, another, [])
        self.assertEqual(manifest['sha256'], self.manifest['sha256'])
        self.assertEqual(manifest['version'], self.manifest['version'])

    def test_release_verification_detects_changed_runtime_file(self):
        (self.runtime / 'Buggcraft.exe').write_bytes(b'changed after packaging')
        with self.assertRaisesRegex(ValueError, 'Runtime file changed'):
            build.verify_release(self.runtime, self.root)

    def test_release_verification_detects_damaged_archive(self):
        archive = self.root / self.manifest['archive']
        archive.write_bytes(archive.read_bytes()[:-20])
        with self.assertRaisesRegex(ValueError, 'Runtime archive size mismatch'):
            build.verify_release(self.runtime, self.root)

    def test_download_url_is_tied_to_immutable_content_version(self):
        manifest, _ = build.package_runtime(self.runtime, self.root,
            ['https://downloads.example/{version}/Buggcraft-runtime-windows-x64.zip'])
        self.assertEqual(manifest['urls'], ['https://downloads.example/' +
            manifest['version'] + '/Buggcraft-runtime-windows-x64.zip'])

    def test_release_signing_can_be_required_and_verifies_artifact(self):
        with self.assertRaisesRegex(RuntimeError, 'trusted code-signing certificate'):
            build.sign_artifacts(self.root, None, require=True)
        certificate = self.root / 'publisher.pfx'
        certificate.write_bytes(b'test certificate placeholder')
        signtool = self.root / 'signtool.exe'
        signtool.write_bytes(b'test tool placeholder')
        artifact = self.root / 'Buggcraft-Setup.exe'
        artifact.write_bytes(b'test binary')
        with patch.dict(os.environ, {'BUGGCRAFT_SIGNTOOL': str(signtool), 'BUGGCRAFT_SIGN_PASSWORD': 'test-only'}):
            with patch.object(build.subprocess, 'run') as run:
                result = build.sign_artifacts(self.root, certificate, require=True,
                    timestamp_url='https://timestamp.example', names=['Buggcraft-Setup.exe'])
        self.assertTrue(result['signed'])
        self.assertEqual(len(run.call_args_list), 2)
        self.assertEqual(run.call_args_list[0].args[0][1], 'sign')
        self.assertEqual(run.call_args_list[1].args[0][1:4], ['verify', '/pa', '/all'])
        self.assertIn('/p', run.call_args_list[0].args[0])

    def test_signing_supports_hardware_certificate_store_and_hides_pfx_password_on_failure(self):
        signtool = self.root / 'signtool.exe'
        signtool.write_bytes(b'test tool')
        artifact = self.root / 'Buggcraft-Setup.exe'
        artifact.write_bytes(b'test binary')
        with patch.dict(os.environ, {'BUGGCRAFT_SIGNTOOL': str(signtool)}):
            with patch.object(build.subprocess, 'run') as run:
                result = build.sign_artifacts(self.root, None, thumbprint='a' * 40,
                    machine_store=True, names=['Buggcraft-Setup.exe'])
            self.assertTrue(result['signed'])
            self.assertIn('/sha1', run.call_args_list[0].args[0])
            self.assertIn('/sm', run.call_args_list[0].args[0])
            self.assertEqual(result['hashes']['Buggcraft-Setup.exe'],
                             hashlib.sha256(artifact.read_bytes()).hexdigest())
            password = 'must-not-appear-in-error'
            failure = subprocess.CalledProcessError(1, ['signtool', '/p', password])
            with patch.object(build.subprocess, 'run', side_effect=failure):
                with self.assertRaises(RuntimeError) as caught:
                    build.sign_artifacts(self.root, self.root / 'publisher.pfx',
                                         password=password, names=['Buggcraft-Setup.exe'])
            self.assertNotIn(password, str(caught.exception))

    def test_child_failure_keeps_output_exit_code_and_logs_beside_installer(self):
        source = self.root / 'child.cs'
        source.write_text('''using System;
using System.IO;
class Child { static int Main() {
    Console.Error.WriteLine("simulated native initialization failure");
    File.WriteAllText(Path.Combine(Environment.GetEnvironmentVariable("BUGGCRAFT_LOG_DIR"),
        "buggcraft-child-test.log"), "child diagnostic preserved");
    File.WriteAllText(Path.Combine(Environment.GetEnvironmentVariable("BUGGCRAFT_LOG_DIR"),
        "game-directory-test.txt"), Environment.GetEnvironmentVariable("BUGGCRAFT_LAUNCHER_DIR"));
    return 37;
} }''', encoding='utf-8')
        compiler = Path(os.environ['WINDIR']) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
        subprocess.run([str(compiler), '/nologo', '/target:exe', '/out:' +
            str(self.runtime / 'Buggcraft.exe'), str(source)], check=True, capture_output=True)
        try:
            probe = subprocess.run([str(self.runtime / 'Buggcraft.exe')],
                                   env=dict(os.environ, BUGGCRAFT_LOG_DIR=str(self.root),
                                            BUGGCRAFT_LAUNCHER_DIR=str(self.root)),
                                   capture_output=True, timeout=10)
        except OSError as error:
            if getattr(error, 'winerror', None) == 4551:
                self.skipTest('Windows Application Control blocks the unsigned synthetic child (WinError 4551)')
            raise
        self.assertEqual(probe.returncode, 37)
        self.manifest, self.manifest_path = build.package_runtime(self.runtime, self.root, [])
        self.compile()
        report = self.root / 'child-result.txt'
        unrelated = self.root / 'different-working-directory'
        unrelated.mkdir()
        run = self.launch_installer([str(self.root / 'Buggcraft-Setup.exe'), '--headless',
            '--runtime-root', str(self.cache), '--report', str(report)],
            cwd=unrelated, timeout=20, capture_output=True)
        self.assertEqual(run.returncode, 1, report.read_text('utf-8-sig'))
        self.assertIn('failed:', report.read_text('utf-8-sig'))
        self.assertIn('exit_code=37 (0x00000025)',
            (self.root / 'Buggcraft-install.log').read_text(encoding='utf-8'))
        self.assertIn('simulated native initialization failure',
            (self.root / 'buggcraft-native.log').read_text(encoding='utf-8'))
        self.assertEqual((self.root / 'buggcraft-child-test.log').read_text(), 'child diagnostic preserved')
        self.assertEqual(Path((self.root / 'game-directory-test.txt').read_text(encoding='utf-8-sig')).resolve(), self.root.resolve())
        self.assertFalse((unrelated / 'Buggcraft-install.log').exists())
        archived = self.root / 'error/37'
        self.assertIn('exit_code=37 (0x00000025)',
                      (archived / 'Buggcraft-install.log').read_text(encoding='utf-8'))
        self.assertIn('simulated native initialization failure',
                      (archived / 'buggcraft-native.log').read_text(encoding='utf-8'))
        self.assertEqual((archived / 'buggcraft-child-test.log').read_text(), 'child diagnostic preserved')

    def test_trusted_native_child_failure_archives_output_and_exit_status(self):
        # Exercise the same failure path using a Windows-signed binary so this
        # test also runs when Application Control rejects synthetic test EXEs.
        child = Path(os.environ['WINDIR']) / 'System32/where.exe'
        baseline = subprocess.run([str(child)], capture_output=True, timeout=10)
        self.assertEqual(baseline.returncode, 2)
        self.assertTrue(baseline.stdout)
        shutil.copy2(child, self.runtime / 'where.exe')
        # System binaries load help/error text from their language sidecars.
        for sidecar in child.parent.glob('*/where.exe.mui'):
            target = self.runtime / sidecar.relative_to(child.parent)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(sidecar, target)
        (self.root / 'buggcraft.log').write_text('retained application diagnostic', encoding='utf-8')
        self.manifest, self.manifest_path = build.package_runtime(self.runtime, self.root, [])
        self.manifest['entrypoint'] = 'where.exe'
        self.manifest_path.write_text(json.dumps(self.manifest), encoding='utf-8')
        self.compile()
        report = self.root / 'trusted-child-result.txt'
        run = self.launch_installer([str(self.root / 'Buggcraft-Setup.exe'), '--headless',
                              '--runtime-root', str(self.cache), '--report', str(report)],
                             cwd=self.root, timeout=20, capture_output=True)
        self.assertEqual(run.returncode, 1, report.read_text('utf-8-sig'))
        archived = self.root / 'error/2'
        self.assertIn('exit_code=2 (0x00000002)',
                      (archived / 'Buggcraft-install.log').read_text(encoding='utf-8'))
        output = (archived / 'buggcraft-native.log').read_text(encoding='utf-8')
        self.assertIn('[stdout]', output)
        self.assertIn('WHERE', output)
        self.assertEqual((archived / 'buggcraft.log').read_text(encoding='utf-8'),
                         'retained application diagnostic')


if __name__ == '__main__':
    unittest.main()
