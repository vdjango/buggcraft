"""Reproduce JAR-less imported instances with the real command generator."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/buggcraft'))
import minecraft_launcher_lib
from core.launch_preparation import prepare_inherited, prepare_standalone, inherited_command, version_chain


class InheritedLaunchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name, data in [('1.20.1', {'id': '1.20.1', 'type': 'release', 'assets': '5', 'mainClass': 'net.minecraft.client.main.Main',
                'libraries': [], 'arguments': {'jvm': ['-cp', '${classpath}'], 'game': []}}),
                ('forge', {'id': 'forge', 'inheritsFrom': '1.20.1',
                           'mainClass': 'cpw.mods.bootstraplauncher.BootstrapLauncher', 'libraries': []}),
                ('整合包', {'id': '整合包', 'inheritsFrom': 'forge', 'jar': '1.20.1'})]:
            self.write(name, data)
        (self.root / 'versions/1.20.1/1.20.1.jar').write_bytes(b'client fixture')

    def write(self, name, data):
        path = self.root / 'versions' / name / (name + '.json')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding='utf8')

    def test_jarless_modpack_prepares_loader_libraries_without_generic_alias_installer(self):
        with patch('core.launch_preparation.verified_installation', return_value=True), \
                patch('minecraft_launcher_lib.install.install_minecraft_version', side_effect=AssertionError('alias installer')), \
                patch('minecraft_launcher_lib.install.install_libraries') as libraries:
            owner = prepare_inherited(self.root, '整合包', {})
        self.assertEqual(owner, '1.20.1')
        self.assertEqual([call.args[0] for call in libraries.call_args_list], ['整合包'])
        command = inherited_command(self.root, '整合包', {}, owner)
        self.assertIn('cpw.mods.bootstraplauncher.BootstrapLauncher', command)
        self.assertIn(str(self.root / 'versions/1.20.1/1.20.1.jar'), command)
        self.assertFalse((self.root / 'versions/整合包/整合包.jar').exists())

    def test_hmcl_style_inheritance_without_jar_uses_actual_ancestor(self):
        self.write('整合包', {'id': '整合包', 'inheritsFrom': 'forge'})
        with patch('core.launch_preparation.verified_installation', return_value=True), \
                patch('minecraft_launcher_lib.install.install_libraries'):
            owner = prepare_inherited(self.root, '整合包', {})
        corrected = inherited_command(self.root, '整合包', {}, owner)
        self.assertIn(str(self.root / 'versions/1.20.1/1.20.1.jar'), corrected)
        self.assertNotIn(str(self.root / 'versions/整合包/整合包.jar'), corrected)

    def test_forge_module_scan_excludes_actual_core_when_alias_has_another_name(self):
        self.write('forge', {'id': 'forge', 'inheritsFrom': '1.20.1',
                            'mainClass': 'cpw.mods.bootstraplauncher.BootstrapLauncher',
                            'arguments': {'jvm': ['-DignoreList=bootstraplauncher,${version_name}.jar'],
                                          'game': ['--launchTarget', 'forgeclient']}})
        command = inherited_command(self.root, '整合包', {}, '1.20.1')
        ignore = next(item for item in command if item.startswith('-DignoreList='))
        self.assertIn('1.20.1.jar', ignore.split('=', 1)[1].split(','))
        self.assertIn('整合包.jar', ignore.split('=', 1)[1].split(','))
        self.assertIn('-cp', command)
        self.assertIn('forgeclient', command)

    def test_missing_core_repairs_vanilla_ancestor_only(self):
        jar = self.root / 'versions/1.20.1/1.20.1.jar'
        jar.unlink()
        with patch('core.launch_preparation.verified_installation', return_value=False), \
                patch('core.launch_preparation.MinecraftDownloader.install', side_effect=lambda _: jar.write_bytes(b'repaired')) as install, \
                patch('minecraft_launcher_lib.install.install_libraries'):
            prepare_inherited(self.root, '整合包', {})
        install.assert_called_once_with('1.20.1')

    def test_cycles_and_traversal_cannot_reach_installation(self):
        self.write('forge', {'inheritsFrom': '整合包'})
        with self.assertRaisesRegex(ValueError, '循环'):
            version_chain(self.root, '整合包')
        self.write('forge', {'inheritsFrom': '../outside'})
        with self.assertRaisesRegex(ValueError, '标识'):
            version_chain(self.root, '整合包')

    def test_combined_pack_repairs_its_own_core_without_reinstalling_ancestors(self):
        metadata = dict(id='Combined', clientVersion='26.1', libraries=[],
                        downloads={'client': {'url': 'https://example.com/client.jar'}},
                        buggcraftModpack={'minecraft': '26.1'})
        self.write('Combined', metadata)
        with patch('core.launch_preparation.verified_installation', return_value=False), \
                patch('minecraft_launcher_lib.install.install_libraries') as libraries, \
                patch('core.launch_preparation.MinecraftDownloader.install', side_effect=AssertionError('vanilla installer')), \
                patch('core.launch_preparation.MinecraftDownloader.install_metadata') as repair:
            prepare_standalone(self.root, 'Combined', {})
        libraries.assert_called_once_with('Combined', [], str(self.root), {})
        repair.assert_called_once_with('Combined', metadata, preserve_client=True)
        self.assertFalse((self.root / 'versions/26.1').exists())
