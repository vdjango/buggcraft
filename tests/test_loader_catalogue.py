"""Catalogue contracts from the official Maven metadata and BMCLAPI documentation."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / 'buggcraft'))
from core import loaders


class LoaderCatalogueTests(unittest.TestCase):
    def response(self, content=None, records=None):
        response = Mock()
        response.content = content
        response.json.return_value = records
        return response

    def test_forge_mirror_accepts_build_objects_and_preserves_branch(self):
        records = [
            {'mcversion': '1.7.10', 'version': '10.13.4.1614', 'branch': '1.7.10'},
            {'mcversion': '1.7.10', 'version': '10.13.4.1558', 'branch': None},
            {'mcversion': '1.7.10', 'version': '10.13.4.1614', 'branch': '1.7.10'},
            {'mcversion': '1.8', 'version': '11.14.0.1281'},
            None,
        ]
        with patch.object(loaders.requests, 'get', return_value=self.response(records=records)) as get:
            versions = loaders.available_versions('Forge', '1.7.10', 'BMCLAPI')
        self.assertEqual(versions, ['10.13.4.1614-1.7.10', '10.13.4.1558'])
        self.assertEqual(get.call_count, 1)
        self.assertIn('/forge/minecraft/1.7.10', get.call_args.args[0])

    def test_official_forge_maven_filters_game_and_sorts_builds_numerically(self):
        metadata = b'''<metadata><versioning><versions>
        <version>1.20.1-47.2.9</version><version>1.19.4-45.1.0</version>
        <version>1.20.1-47.10.0</version><version>1.20.1-47.2.10</version>
        </versions></versioning></metadata>'''
        with patch.object(loaders.requests, 'get', return_value=self.response(content=metadata)):
            versions = loaders.available_versions('Forge', '1.20.1', '官方')
        self.assertEqual(versions, ['47.10.0', '47.2.10', '47.2.9'])

    def test_forge_automatic_fallback_parses_mirror_contract(self):
        offline = Mock()
        offline.raise_for_status.side_effect = OSError('offline')
        mirror = self.response(records=[{'mcversion': '1.20.1', 'version': '47.4.0'}])
        with patch.object(loaders.requests, 'get', side_effect=[offline, mirror]) as get:
            self.assertEqual(loaders.available_versions('Forge', '1.20.1', '自动'), ['47.4.0'])
        self.assertEqual(get.call_count, 2)

    def test_no_matching_build_reports_no_compatible_version(self):
        response = self.response(records=[{'mcversion': '1.20.1', 'version': '47.4.0'}])
        with patch.object(loaders.requests, 'get', return_value=response):
            with self.assertRaisesRegex(ValueError, '暂无适用于 Minecraft 1.21.8'):
                loaders.available_versions('Forge', '1.21.8', 'BMCLAPI')

    def test_installed_forge_profile_is_resolved_from_its_library_coordinate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            actual = 'legacy-custom-forge-profile'
            version = root / 'versions' / actual
            version.mkdir(parents=True)
            (version / (actual + '.json')).write_text(
                '{\"libraries\":[{\"name\":\"net.minecraftforge:forge:1.20.1-47.2.0:client\"}]}',
                encoding='utf-8')
            self.assertEqual(loaders._installed_forge_version(root, '1.20.1', '47.2.0'), actual)


if __name__ == '__main__':
    unittest.main(verbosity=2)
