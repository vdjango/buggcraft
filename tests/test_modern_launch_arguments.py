"""New official auth arguments and Java metadata work with launcher-lib 7.x."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/buggcraft'))
import minecraft_launcher_lib
from core.launch_options import complete_auth_arguments, offline_uuid, required_java


class ModernLaunchTests(unittest.TestCase):
    def test_official_style_26_3_arguments_have_no_unresolved_auth_placeholders(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / 'versions/26.3/26.3.json'
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({'id': '26.3', 'type': 'release', 'assets': '34',
                'mainClass': 'net.minecraft.client.main.Main', 'libraries': [],
                'javaVersion': {'majorVersion': 25}, 'arguments': {'jvm': ['-cp', '${classpath}'],
                'game': ['--uuid', '${auth_uuid}', '--accessToken', '${auth_access_token}',
                         '--clientId', '${clientid}', '--xuid', '${auth_xuid}']}}), encoding='utf-8')
            options = {'username': 'Fixture', 'uuid': offline_uuid('Fixture'), 'token': '0',
                       'executablePath': 'java'}
            command = complete_auth_arguments(minecraft_launcher_lib.command.get_minecraft_command('26.3', root, options))
            self.assertFalse(any('${' in part or part in ('{uuid}', '{token}') for part in command))
            self.assertEqual(command[command.index('--uuid') + 1], options['uuid'])
            self.assertEqual(command[command.index('--accessToken') + 1], '0')
            self.assertEqual(required_java(root, '26.3'), 25)

    def test_uuid_matches_java_offline_identity_and_is_stable(self):
        self.assertEqual(offline_uuid('Notch'), 'b50ad385-829d-3141-a216-7e7d7539ba7f')
        self.assertEqual(offline_uuid('玩家'), offline_uuid('玩家'))
        self.assertNotEqual(offline_uuid('Fixture'), offline_uuid('fixture'))

    def test_inherited_version_uses_base_java_and_rejects_cycles(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name, metadata in [('pack', {'inheritsFrom': '26.3'}),
                                   ('26.3', {'javaVersion': {'majorVersion': 25}})]:
                path = root / 'versions' / name / (name + '.json')
                path.parent.mkdir(parents=True)
                path.write_text(json.dumps(metadata), encoding='utf-8')
            self.assertEqual(required_java(root, 'pack'), 25)
            path.write_text(json.dumps({'inheritsFrom': 'pack'}), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, '循环'):
                required_java(root, 'pack')
