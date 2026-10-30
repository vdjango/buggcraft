"""Imported loader versions must not send duplicate libraries to Java."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/buggcraft'))

from core.launch_preparation import deduplicate_classpath, inherited_command


class LaunchClasspathTests(unittest.TestCase):
    def test_neoforge_inherited_modpack_deduplicates_shared_gson(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            versions = {
                '1.21.1': {
                    'id': '1.21.1', 'type': 'release', 'assets': '17',
                    'mainClass': 'net.minecraft.client.main.Main',
                    'libraries': [{'name': 'com.google.code.gson:gson:2.10.1'}],
                    'arguments': {'jvm': ['-cp', '${classpath}'], 'game': []},
                },
                'neoforge': {
                    'id': 'neoforge', 'inheritsFrom': '1.21.1',
                    'mainClass': 'cpw.mods.bootstraplauncher.BootstrapLauncher',
                    'libraries': [
                        {'name': 'com.google.code.gson:gson:2.10.1'},
                        {'name': 'com.google.code.gson:gson:2.10.1'},
                    ],
                },
                'pack': {'id': 'pack', 'inheritsFrom': 'neoforge'},
            }
            for version, metadata in versions.items():
                directory = root / 'versions' / version
                directory.mkdir(parents=True)
                (directory / (version + '.json')).write_text(json.dumps(metadata), encoding='utf-8')
            command = deduplicate_classpath(inherited_command(root, 'pack', {}, '1.21.1'))
            entries = command[command.index('-cp') + 1].split(os.pathsep)
            self.assertEqual(sum(path.endswith('gson-2.10.1.jar') for path in entries), 1)
            self.assertTrue(entries[-1].endswith(os.path.join('versions', '1.21.1', '1.21.1.jar')))

    def test_standalone_command_keeps_order_and_module_path(self):
        library = str(Path('game') / 'libraries' / 'gson-2.10.1.jar')
        other = str(Path('game') / 'libraries' / 'other.jar')
        classpath = os.pathsep.join((library, other, library))
        command = ['java', '-cp', classpath, '-p', 'module.jar',
                   '-DlegacyClassPath=' + classpath, 'cpw.mods.bootstraplauncher.BootstrapLauncher']
        fixed = deduplicate_classpath(command)
        self.assertEqual(fixed[2].split(os.pathsep), [library, other])
        self.assertEqual(fixed[5], '-DlegacyClassPath=' + os.pathsep.join((library, other)))
        self.assertEqual(fixed[fixed.index('-p') + 1], 'module.jar')
        self.assertEqual(command[2], classpath)

    def test_inline_classpath_tolerates_optional_arguments(self):
        command = ['java', None, '--class-path=first.jar' + os.pathsep + 'first.jar', 'Main']
        self.assertEqual(deduplicate_classpath(command),
                         ['java', None, '--class-path=first.jar', 'Main'])

    def test_final_command_deduplicates_module_path_and_legacy_classpath(self):
        first = str(Path('game') / 'libraries' / 'gson.jar')
        alternate = str(Path('game') / 'libraries' / 'other.jar')
        repeated = os.pathsep.join((first, alternate, first))
        command = ['java', '-cp', repeated, '-p', repeated,
                   '--module-path=' + repeated, '-DlegacyClassPath=' + repeated, 'Main']
        fixed = deduplicate_classpath(command)
        unique = os.pathsep.join((first, alternate))
        self.assertEqual(fixed[fixed.index('-cp') + 1], unique)
        self.assertEqual(fixed[fixed.index('-p') + 1], unique)
        self.assertIn('--module-path=' + unique, fixed)
        self.assertIn('-DlegacyClassPath=' + unique, fixed)
        self.assertEqual(command[2], repeated)


if __name__ == '__main__':
    unittest.main()
