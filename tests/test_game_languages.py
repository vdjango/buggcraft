"""Use each installed game's language index and preserve language codes at launch."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/buggcraft'))
from core.game_languages import available_languages, normalize_language


class GameLanguagesTests(unittest.TestCase):
    def test_full_catalogue_includes_native_names_and_non_chinese_languages(self):
        options = {item['value']: item['title'] for item in available_languages()}
        self.assertGreater(len(options), 100)
        self.assertIn('日本語', options['ja_jp'])
        self.assertIn('Français', options['fr_fr'])
        self.assertEqual(normalize_language('日本語'), 'ja_jp')
        self.assertEqual(normalize_language('fr_fr'), 'fr_fr')
        self.assertEqual(normalize_language('../bad'), 'zh_cn')

    def test_inherited_instance_uses_its_actual_asset_index(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name, metadata in [('pack', {'inheritsFrom': 'base'}), ('base', {'assetIndex': {'id': 'fixture'}})]:
                path = root / 'versions' / name / (name + '.json')
                path.parent.mkdir(parents=True)
                path.write_text(json.dumps(metadata))
            path = root / 'assets/indexes/fixture.json'
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({'objects': {'minecraft/lang/ja_jp.json': {},
                                                    'minecraft/lang/fr_fr.json': {},
                                                    'minecraft/lang/deprecated.json': {},
                                                    'other/file.json': {}}}))
            self.assertEqual({item['value'] for item in available_languages(root, 'pack')},
                             {'ja_jp', 'fr_fr', 'en_us'})
            path.write_text('corrupt index')
            self.assertGreater(len(available_languages(root, 'pack')), 100)
