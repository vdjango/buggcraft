"""Keep transitive binary dependencies while trimming excluded Qt modules."""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('unix_build', Path(__file__).resolve().parents[1] / 'build.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


class UnixQtTrimmingTests(unittest.TestCase):
    def test_elf_dependencies_keep_transitive_qt_and_non_qt_libraries(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'runtime'
            root.mkdir()
            for name in ('Buggcraft', 'libQt6Quick.so.6', 'libQt6Core.so.6',
                         'libQt6Pdf.so.6', 'libssl.so.3'):
                (root / name).write_bytes(b'\x7fELFfixture')
            imports = {'Buggcraft': ['libQt6Quick.so.6'],
                       'libQt6Quick.so.6': ['libQt6Core.so.6'],
                       'libQt6Core.so.6': [], 'libssl.so.3': []}

            def scan(command, **kwargs):
                needed = imports[Path(command[-1]).name]
                return SimpleNamespace(stdout='\n'.join(f'(NEEDED) Shared library: [{name}]' for name in needed))

            with patch.object(build.platform, 'system', return_value='Linux'), \
                    patch.object(build.subprocess, 'run', side_effect=scan):
                removed = build.trim_unix_qt_libraries(root, Path(folder) / 'unused')
            self.assertEqual([entry['name'] for entry in removed], ['libQt6Pdf.so.6'])
            self.assertTrue((root / 'libQt6Core.so.6').is_file())
            self.assertTrue((root / 'libssl.so.3').is_file())

    def test_macho_frameworks_keep_transitive_dependencies_and_remove_whole_unused_framework(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'Buggcraft.app'
            root.mkdir()
            (root / 'Buggcraft').write_bytes(b'\xcf\xfa\xed\xfefixture')
            for name in ('QtQuick', 'QtCore', 'QtPdf'):
                path = root / (name + '.framework') / 'Versions/A' / name
                path.parent.mkdir(parents=True)
                path.write_bytes(b'\xcf\xfa\xed\xfefixture')
                (path.parent / 'Resources.txt').write_text('framework data')
            imports = {'Buggcraft': ['QtQuick'], 'QtQuick': ['QtCore'], 'QtCore': []}

            def scan(command, **kwargs):
                names = imports[Path(command[-1]).name]
                lines = [command[-1] + ':'] + [
                    f'  @rpath/{name}.framework/Versions/A/{name} (compatibility version 1.0.0)'
                    for name in names]
                return SimpleNamespace(stdout='\n'.join(lines))

            with patch.object(build.platform, 'system', return_value='Darwin'), \
                    patch.object(build.subprocess, 'run', side_effect=scan):
                removed = build.trim_unix_qt_libraries(root, Path(folder) / 'unused')
            self.assertEqual([entry['name'] for entry in removed], ['QtPdf.framework'])
            self.assertTrue((root / 'QtCore.framework').is_dir())
            self.assertFalse((root / 'QtPdf.framework').exists())

    @unittest.skipUnless(sys.platform.startswith('linux') and shutil.which('cc') and shutil.which('readelf'),
                         'Requires Linux native compiler and readelf')
    def test_real_elf_application_still_runs_after_trim(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'runtime'
            root.mkdir()
            source = Path(folder) / 'lib.c'
            source.write_text('int answer(void) { return 42; }\n')
            for name in ('libQt6Wanted.so.6', 'libQt6Unused.so.6'):
                subprocess.run(['cc', '-shared', '-fPIC', str(source), '-o', str(root / name),
                                '-Wl,-soname,' + name], check=True)
            source.write_text('int answer(void); int main(void) { return answer() == 42 ? 0 : 1; }\n')
            subprocess.run(['cc', str(source), '-L' + str(root), '-l:libQt6Wanted.so.6',
                            '-Wl,-rpath,$ORIGIN', '-o', str(root / 'Buggcraft')], check=True)
            removed = build.trim_unix_qt_libraries(root, Path(folder) / 'unused')
            self.assertEqual([entry['name'] for entry in removed], ['libQt6Unused.so.6'])
            subprocess.run([str(root / 'Buggcraft')], check=True)
