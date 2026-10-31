"""Read declared JAR identities without relying on names or extracting content."""
from pathlib import Path
import sys
import tempfile
import unittest
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / 'buggcraft'))
from core.mod_identity import jar_mods


class JarIdentityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def jar(self, **entries):
        path = self.root / 'unrelated-and-renamed.jar'
        with ZipFile(path, 'w') as archive:
            for name, text in entries.items():
                archive.writestr(name, text)
        return path

    def test_forge_uses_internal_id_and_manifest_version_after_rename(self):
        path = self.jar(**{
            'META-INF/mods.toml': '[[mods]]\nmodId="actual_mod"\ndisplayName="Actual Mod"\nversion="${file.jarVersion}"\n',
            'META-INF/MANIFEST.MF': 'Manifest-Version: 1.0\r\nImplementation-Version: 1.2.\r\n 3\r\n',
            '../must-not-extract.txt': 'untrusted',
        })
        self.assertEqual(jar_mods(path), [dict(id='actual_mod', name='Actual Mod', version='1.2.3', loader='Forge')])
        renamed = path.with_name('anything.jar')
        path.rename(renamed)
        self.assertEqual(jar_mods(renamed)[0]['id'], 'actual_mod')
        self.assertEqual(sorted(item.name for item in self.root.iterdir()), ['anything.jar'])

    def test_neoforge_multi_mod_archive(self):
        path = self.jar(**{'META-INF/neoforge.mods.toml':
            '[[mods]]\nmodId="first"\nversion="2"\n[[mods]]\nmodId="second"\nversion="3"\n'})
        self.assertEqual([(item['id'], item['loader']) for item in jar_mods(path)],
                         [('first', 'NeoForge'), ('second', 'NeoForge')])

    def test_legacy_chinese_encoding_still_reads_internal_id(self):
        path = self.jar(**{'META-INF/mods.toml':
            '[[mods]]\nmodId="biome_improvements"\ndisplayName="生态改进"\nversion="0.1.10"\n'.encode('gb18030')})
        self.assertEqual(jar_mods(path)[0]['id'], 'biome_improvements')

    def test_fabric_quilt_and_legacy_forge(self):
        fixtures = [
            ('fabric.mod.json', '{"id":"fabric_id","name":"Fabric Mod","version":"1.0"}', 'fabric_id', 'Fabric'),
            ('quilt.mod.json', '{"quilt_loader":{"id":"quilt_id","version":"1.0","metadata":{"name":"Quilt Mod"}}}', 'quilt_id', 'Quilt'),
            ('mcmod.info', '[{"modid":"legacy","name":"Legacy Mod","version":"1.0"}]', 'legacy', 'Forge'),
            ('mcmod.info', '{"modList":[{"modid":"legacy","version":"1.0"}]}', 'legacy', 'Forge'),
        ]
        for filename, contents, identity, loader in fixtures:
            with self.subTest(filename=filename, contents=contents):
                result = jar_mods(self.jar(**{filename: contents}))
                self.assertEqual((result[0]['id'], result[0]['version'], result[0]['loader']), (identity, '1.0', loader))

    def test_malformed_or_oversized_metadata_cannot_block_other_valid_metadata(self):
        for invalid in ('{' * 270000, b'\xff\xfe', '{"quilt_loader":4}', '{'):
            with self.subTest(invalid=str(invalid)[:30]):
                path = self.jar(**{'quilt.mod.json': invalid,
                    'fabric.mod.json': '{"id":"valid","version":"1"}'})
                self.assertEqual(jar_mods(path)[0]['id'], 'valid')

    def test_invalid_archive_or_unknown_metadata_returns_no_invented_identity(self):
        path = self.root / 'actual_mod-1.2.3.jar'
        path.write_bytes(b'not a ZIP')
        self.assertEqual(jar_mods(path), [])
        self.assertEqual(jar_mods(self.jar(**{'fabric.mod.json': '{"id":12,"version":"1"}'})), [])
        self.assertEqual(jar_mods(self.root / 'missing.jar'), [])


if __name__ == '__main__':
    unittest.main()
