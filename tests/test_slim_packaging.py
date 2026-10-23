"""Keep unsupported media and PDF engines out of both platform releases."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('slim_build', ROOT / 'build.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


class SlimPackagingTests(unittest.TestCase):
    def test_accidental_media_and_pdf_files_prevent_packaging(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / 'Buggcraft.exe').write_bytes(b'application')
            for name in ('av/_core.pyd', 'av.libs/avcodec.dll',
                         'pylibsrtp/_binding.pyd',
                         'notifypy/notify.py', 'loguru/_logger.py',
                         'PySide6/qt-plugins/imageformats/qpdf.dll'):
                with self.subTest(name=name):
                    path = directory / name
                    path.parent.mkdir(exist_ok=True, parents=True)
                    path.write_bytes(b'unused')
                    with self.assertRaisesRegex(ValueError, 'Unneeded dependencies'):
                        build.package_runtime(directory, directory, [])
                    self.assertFalse((directory / 'release.json').exists())
                    path.unlink()
            build.validate_runtime_inventory(directory)

    def test_media_and_pdf_are_excluded_on_both_platforms(self):
        for platform in ('Windows', 'Darwin'):
            with self.subTest(platform=platform), \
                    patch.object(build.platform, 'system', return_value=platform), \
                    patch.object(build, 'qml_exclusions', return_value=([], [])):
                command = build.make_command()
                excluded = {name for argument in command if argument.startswith('--nofollow-import-to=')
                            for name in argument.split('=', 1)[1].split(',')}
                self.assertTrue({'asyncssh', 'aioice', 'aiortc', 'av', 'pylibsrtp', 'hookup._rtc'} <= excluded)
                self.assertIn('--nofollow-import-to=notifypy,loguru,plyer,multiprocessing,concurrent.futures.process,_uuid', command)
                self.assertIn('--noinclude-dlls=PySide6/qt-plugins/imageformats/*qpdf*', command)
                self.assertFalse(any(arg in command for arg in ('--include-package=aiortc', '--include-package=av')))
                self.assertTrue(any('hookup/THIRD_PARTY_NOTICES.txt' in arg for arg in command))
                self.assertEqual('--noinclude-dlls=opengl32sw.dll' in command, platform == 'Windows')

    def test_vendored_source_matches_recorded_hashes(self):
        root = ROOT / 'compatibility/legacy_hookup/_rtc'
        manifest = json.loads((root / 'UPSTREAM.json').read_text(encoding='utf-8'))
        for name, record in manifest['files'].items():
            with self.subTest(module=name):
                # Git may check out LF sources as CRLF on Windows.
                data = (root / name).read_text(encoding='utf-8').encode()
                self.assertEqual(hashlib.sha256(data).hexdigest(), record['generated_sha256'])


if __name__ == '__main__':
    unittest.main()
