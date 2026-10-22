"""Mod inventories retain version/dependency evidence without exporting mod binaries."""
import gzip
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/buggcraft'))
from utils.diagnostics import export_diagnostics
from utils.game_diagnostics import game_inventory


class GameDiagnosticsTests(unittest.TestCase):
    def test_forge_fabric_quilt_and_broken_mods_are_reported_with_inherited_loader_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            game = root / 'versions/pack'
            (game / 'mods').mkdir(parents=True)
            fixtures = {'forge.jar': {'META-INF/mods.toml': '[[mods]]\nmodId="fixture"\nversion="1.2"\ndisplayName="Fixture"\n[[dependencies.fixture]]\nmodId="forge"\nversionRange="[47,)"'},
                        'fabric.jar': {'fabric.mod.json': json.dumps({'id': 'fabric-fixture', 'version': '2.0', 'depends': {'minecraft': '~1.20'}})},
                        'quilt.jar': {'quilt.mod.json': json.dumps({'quilt_loader': {'id': 'quilt-fixture', 'version': '3.0'}})}}
            for name, metadata in fixtures.items():
                with ZipFile(game / 'mods' / name, 'w') as jar:
                    for path, content in metadata.items():
                        jar.writestr(path, content)
            (game / 'mods/broken.jar').write_bytes(b'broken zip')
            for name, data in [('pack', {'inheritsFrom': 'base', 'buggcraftModpack': {'loader': 'Forge'}}),
                               ('base', {'javaVersion': {'majorVersion': 17}})]:
                path = root / 'versions' / name / (name + '.json')
                path.parent.mkdir(exist_ok=True)
                path.write_text(json.dumps(data), encoding='utf-8')
            inventory = game_inventory(game)
            mods = {item['file']: item for item in inventory['mods']}
            self.assertEqual(len(mods), 4)
            self.assertEqual(mods['forge.jar']['metadata']['META-INF/mods.toml']['mods'][0]['version'], '1.2')
            self.assertEqual(mods['fabric.jar']['metadata']['fabric.mod.json']['depends']['minecraft'], '~1.20')
            self.assertEqual(mods['quilt.jar']['metadata']['quilt.mod.json']['quilt_loader']['id'], 'quilt-fixture')
            self.assertIn('BadZipFile', mods['broken.jar']['error'])
            self.assertEqual([item['version'] for item in inventory['version_metadata']], ['pack', 'base'])

    def test_export_includes_inventory_and_decompressed_rotations_with_credentials_removed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            game = root / 'game'
            (game / 'logs').mkdir(parents=True)
            (game / 'mods').mkdir()
            with gzip.open(game / 'logs/debug.log.1.gz', 'wb') as log:
                log.write(b'Mod loading failed --accessToken top-secret')
            with ZipFile(game / 'mods/fixture.jar', 'w') as jar:
                jar.writestr('fabric.mod.json', json.dumps({'id': 'fixture', 'version': '1.0', 'token': 'top-secret'}))
                jar.writestr('classes/private.class', b'do not export binary')
            with patch('utils.network_diagnostics.capture_network', return_value={'trace_id': 'test'}):
                target = export_diagnostics(root / 'diagnostics.zip', root, game)
            with ZipFile(target) as archive:
                self.assertIn('game/inventory.json', archive.namelist())
                log = archive.read('game/logs/debug.log.1.gz.decompressed.log')
                self.assertIn(b'Mod loading failed', log)
                self.assertNotIn(b'top-secret', log)
                self.assertNotIn(b'top-secret', archive.read('game/inventory.json'))
                self.assertFalse(any(name.endswith(('.jar', '.class')) for name in archive.namelist()))
                self.assertEqual(json.loads(archive.read('game/inventory.json'))['mods'][0]['file'], 'fixture.jar')
